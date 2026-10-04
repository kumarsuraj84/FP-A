"""
Read-only verification of an installed `cred` schema: owners, role attributes, the full privilege matrix, public grants, guard triggers,
initial policy, and that no data exists yet. It reads the catalog only and writes nothing to the database.

    Run it in your own terminal: it asks for the admin connection (password hidden, never stored), or uses FPA_PG_ADMIN_URL if set.
    python tools/creditors_mart/verify_install.py fpa_pilot        # prints the result and writes docs/creditors_pilot/MART_REAL_INSTALL_EVIDENCE.md

The report names the database and the roles only. It never contains a credential, a host or a password.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROLES = ["cred_owner", "cred_loader", "cred_verifier", "cred_promoter", "cred_api_reader", "cred_finance_reader"]
TABLES = ["run", "vendor_snapshot", "open_item", "identity_snapshot", "control_result", "run_event", "load_rejection", "live_run", "promotion", "policy_change"]
FACT = ["vendor_snapshot", "open_item", "identity_snapshot"]
VIEWS = ["v_live_run", "v_open_item", "v_exposure_summary", "v_vendor_counts", "v_live_controls", "v_open_item_named", "v_open_item_any_run", "v_open_item_named_any_run",
         "v_exposure_summary_any_run", "v_vendor_counts_any_run", "v_control_result_any_run", "v_run_status", "v_promotion_history"]

# who may do what (everything not listed is expected to be refused); the owner's own privileges as table owner are not listed
TABLE_RIGHTS = {  # table -> role -> privileges
    "run": {"cred_loader": {"INSERT", "SELECT"}},
    "vendor_snapshot": {"cred_loader": {"INSERT", "SELECT"}},
    "open_item": {"cred_loader": {"INSERT", "SELECT"}},
    "identity_snapshot": {"cred_loader": {"INSERT", "SELECT"}},
    "control_result": {"cred_loader": {"SELECT"}},
    "load_rejection": {"cred_loader": {"INSERT"}},
}
VIEW_RIGHTS = {
    "v_live_run": {"cred_verifier", "cred_promoter", "cred_api_reader", "cred_finance_reader"},
    "v_open_item": {"cred_api_reader", "cred_finance_reader"},
    "v_exposure_summary": {"cred_api_reader", "cred_finance_reader"},
    "v_vendor_counts": {"cred_api_reader", "cred_finance_reader"},
    "v_live_controls": {"cred_api_reader", "cred_finance_reader"},
    "v_open_item_named": {"cred_finance_reader"},
    "v_open_item_any_run": {"cred_verifier"},
    "v_exposure_summary_any_run": {"cred_verifier"},
    "v_vendor_counts_any_run": {"cred_verifier"},
    "v_control_result_any_run": {"cred_verifier", "cred_promoter"},
    "v_run_status": {"cred_promoter"},
    "v_promotion_history": {"cred_promoter"},
    "v_open_item_named_any_run": set(),
}
FUNCTION_RIGHTS = {  # signature -> roles with EXECUTE (besides the owner, who owns them)
    "record_control(text, text, text, text, numeric, text, numeric)": {"cred_loader", "cred_verifier"},
    "verify_run(text)": {"cred_loader", "cred_owner"},
    "mart_checks(text)": {"cred_loader", "cred_owner"},
    "api_verify_run(text)": {"cred_verifier"},
    "ui_verify_run(text)": {"cred_verifier"},
    "promote_run(text, text)": {"cred_promoter"},
    "demote_to(text, text)": {"cred_promoter"},
    "purge_run(text, text)": {"cred_owner"},
    "set_policy(boolean, boolean, text)": {"cred_owner"},
}
PUBLIC_FUNCTIONS = {"caller_role()", "caller_is(name)", "maintenance_on()"}


def verify(conn) -> list[tuple[str, bool, str]]:
    """Returns (check, ok, detail). Read-only: catalog queries only."""
    out: list[tuple[str, bool, str]] = []

    def add(name: str, ok: bool, detail: str = ""):
        out.append((name, bool(ok), detail))

    one = lambda sql, *p: conn.execute(sql, p).fetchone()[0]  # noqa: E731
    add("schema cred exists", one("SELECT count(*) FROM pg_namespace WHERE nspname = 'cred'") == 1)
    add("schema owner is cred_owner", one("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'cred'") == "cred_owner")
    owners = {r[0] for r in conn.execute("SELECT pg_get_userbyid(relowner) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'cred' AND c.relkind IN ('r','v','S')")}
    add("every table, view and sequence is owned by cred_owner", owners == {"cred_owner"}, str(sorted(owners)))
    fown = {r[0] for r in conn.execute("SELECT pg_get_userbyid(proowner) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'cred'")}
    add("every function is owned by cred_owner", fown == {"cred_owner"}, str(sorted(fown)))

    attrs = {r[0]: r[1:] for r in conn.execute("SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname = ANY(%s)", (ROLES,))}
    add("all six roles exist", sorted(attrs) == sorted(ROLES), str(sorted(attrs)))
    add("no role is superuser / createdb / createrole / replication / bypassrls", all(not any(v[1:]) for v in attrs.values()))
    add("login state of the cred roles (informational: the administrator attaches logins)", True, "; ".join(f"{k}={'LOGIN' if v[0] else 'NOLOGIN'}" for k, v in sorted(attrs.items())))
    members = [r for r in conn.execute("SELECT m.rolname, g.rolname FROM pg_auth_members a JOIN pg_roles m ON m.oid = a.member JOIN pg_roles g ON g.oid = a.roleid WHERE g.rolname = ANY(%s)", (ROLES,))]
    add("no role is a member of another cred role (no privilege inheritance between them)", not any(m[0] in ROLES for m in members), str(members))

    for r in ROLES[1:]:
        add(f"{r}: schema USAGE", one("SELECT has_schema_privilege(%s, 'cred', 'USAGE')", r) is True)
        add(f"{r}: no CREATE in schema cred", one("SELECT has_schema_privilege(%s, 'cred', 'CREATE')", r) is False)
        add(f"{r}: no CREATE in the database", one("SELECT has_database_privilege(%s, current_database(), 'CREATE')", r) is False)
    add("cred_owner: may create in the database (migrations)", one("SELECT has_database_privilege('cred_owner', current_database(), 'CREATE')") is True)

    mism = []
    for t in TABLES:
        for r in ROLES[1:]:
            for priv in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                want = priv in TABLE_RIGHTS.get(t, {}).get(r, set())
                got = one("SELECT has_table_privilege(%s, %s, %s)", r, f"cred.{t}", priv)
                if want != got:
                    mism.append(f"{r} {priv} on {t}: expected {want}, found {got}")
    add("table privilege matrix matches the design", not mism, "; ".join(mism[:6]) or f"{len(TABLES) * 5 * 7} grants checked")
    mism = []
    for v, allowed in VIEW_RIGHTS.items():
        for r in ROLES[1:]:
            got = one("SELECT has_table_privilege(%s, %s, 'SELECT')", r, f"cred.{v}")
            if (r in allowed) != got:
                mism.append(f"{r} SELECT on {v}: expected {r in allowed}, found {got}")
    add("view privilege matrix matches the design (names only for Finance)", not mism, "; ".join(mism[:6]) or f"{len(VIEW_RIGHTS) * 5} grants checked")
    mism = []
    for sig, allowed in FUNCTION_RIGHTS.items():
        for r in ROLES[1:]:
            got = one("SELECT has_function_privilege(%s, %s, 'EXECUTE')", r, f"cred.{sig}")
            if (r in allowed) != got:
                mism.append(f"{r} EXECUTE {sig}: expected {r in allowed}, found {got}")
    add("function privilege matrix matches the design", not mism, "; ".join(mism[:6]) or f"{len(FUNCTION_RIGHTS) * 5} grants checked")
    pub = [r[0] for r in conn.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace, aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a "
                                       "WHERE n.nspname = 'cred' AND c.relkind IN ('r','v') AND a.grantee = 0")]
    add("no PUBLIC privilege on any table or view", not pub, str(pub))
    pubf = [r[0] for r in conn.execute("SELECT p.oid::regprocedure::text FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'cred' AND has_function_privilege('public', p.oid, 'EXECUTE')")]
    pubf = [f.replace("cred.", "") for f in pubf]
    add("PUBLIC can execute only the three harmless helpers", set(pubf) == PUBLIC_FUNCTIONS, str(sorted(pubf)))

    trig = {r[0]: r[1] for r in conn.execute("SELECT c.relname, count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'cred' AND NOT t.tgisinternal GROUP BY 1")}
    add("immutability guard triggers are present and enabled", all(t in trig for t in ("open_item", "vendor_snapshot", "identity_snapshot", "control_result", "run_event", "load_rejection", "promotion", "policy_change", "run")), str(trig))
    add("no trigger is disabled", one("SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'cred' AND NOT t.tgisinternal AND t.tgenabled <> 'O'") == 0)
    add("security-definer functions pin their search_path", one("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'cred' AND p.prosecdef AND position('search_path=' in coalesce(p.proconfig::text, '')) = 0") == 0)

    pol = conn.execute("SELECT require_api_layer, require_ui_layer FROM cred.policy_change ORDER BY change_id DESC LIMIT 1").fetchone()
    add("initial policy: API layer required, UI layer not yet", pol == (True, False), str(pol))
    empty = {t: conn.execute(f"SELECT count(*) FROM cred.{t}").fetchone()[0] for t in TABLES if t != "policy_change"}
    add("no data has been loaded: every table is empty and nothing is live", all(v == 0 for v in empty.values()), str(empty))

    app = one("SELECT count(*) FROM pg_roles WHERE rolname = 'fpa_app'")
    if app:
        add("the existing application role fpa_app has no access to schema cred", one("SELECT has_schema_privilege('fpa_app', 'cred', 'USAGE')") is False)
    return out


def render(db: str, results: list[tuple[str, bool, str]]) -> str:
    bad = [r for r in results if not r[1]]
    lines = ["# Creditors pilot mart: real database install evidence", "",
             f"Database: `{db}`. Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} by `tools/creditors_mart/verify_install.py` (read-only catalog queries).",
             "No credential, host or password appears in this file.", "",
             f"**{len(results) - len(bad)} of {len(results)} checks pass.**", "", "| Check | Result | Detail |", "|---|---|---|"]
    for name, ok, detail in results:
        lines.append(f"| {name} | {'PASS' if ok else 'FAIL'} | {detail[:160].replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    import psycopg
    from migrate import admin_conninfo, redact, with_database

    url = admin_conninfo()
    if not url:
        print(__doc__)
        print("No administrator connection available: run this in an interactive terminal, or set FPA_PG_ADMIN_URL.")
        return 2

    db = argv[1]
    try:
        with psycopg.connect(with_database(url, db), autocommit=True, options="-c default_transaction_read_only=on") as conn:
            results = verify(conn)
    except Exception as e:  # noqa: BLE001
        print(f"FAILED: {type(e).__name__}: {redact(e)}")
        return 1
    bad = [r for r in results if not r[1]]
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail[:120]}]" if not ok else ""))
    out = Path(__file__).resolve().parents[2] / "docs" / "creditors_pilot" / "MART_REAL_INSTALL_EVIDENCE.md"
    out.write_text(render(db, results), encoding="utf-8")
    print(f"\n{len(results) - len(bad)} of {len(results)} checks pass. Evidence: {out.name}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main(sys.argv))
