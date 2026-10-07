"""
One-time administrator step for the Creditors API, run in YOUR OWN terminal (one hidden password prompt):

    python tools/creditors_mart/install_api.py            # database defaults to fpa_pilot

  1. applies any pending mart migrations (002 verified-candidate views, 003 shared run model, 004 cash schema, 005 entry layer, 006 till-day-only entry layer, 007 entry identity v2, 008 P&L actuals) through the reviewed migration path;
  2. creates (or re-keys) the login `cred_api_login`: a member of cred_verifier, cred_finance_reader, cred_api_reader, cash_verifier, cash_api_reader, entry_verifier, entry_api_reader, entry_finance_reader, pnl_verifier and pnl_api_reader ONLY, set
     NOINHERIT so it holds no privilege of its own: the API must `SET ROLE` into exactly one of them per request, and the database
     decides what each role may read. It is not a member of any loader, owner or promoter role and has no admin attributes;
  3. writes the random password and a random Finance access token ONLY to the git-ignored file .secrets/cred_api.env;
     the password reaches PostgreSQL only as a SCRAM hash. Nothing secret is printed;
  4. proves the restrictions by logging in as that account.
"""
from __future__ import annotations

import secrets
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from setup_loader import read_env, write_secret_file  # noqa: E402

LOGIN = "cred_api_login"
SECRET_FILE = HERE.parents[1] / ".secrets" / "cred_api.env"
MEMBER_OF = ["cred_verifier", "cred_finance_reader", "cred_api_reader", "cash_verifier", "cash_api_reader", "entry_verifier", "entry_api_reader", "entry_finance_reader", "pnl_verifier", "pnl_api_reader"]
FORBIDDEN = ["cred_owner", "cred_loader", "cred_promoter", "cash_owner", "cash_loader", "cash_promoter", "entry_owner", "entry_loader", "entry_promoter", "pnl_owner", "pnl_loader", "pnl_promoter"]


def provision(admin, secret_path: Path, host: str, port: str, dbname: str) -> dict:
    from psycopg import sql

    is_admin = admin.execute("SELECT rolsuper OR (rolcreaterole AND rolcreatedb) FROM pg_roles WHERE rolname = current_user").fetchone()[0]
    if not is_admin:
        raise SystemExit("this account is not an administrator; nothing was changed")
    if admin.execute("SELECT current_database()").fetchone()[0] in ("fpa", "postgres", "template0", "template1"):
        raise SystemExit("refusing to use this database")
    existing = read_env(secret_path)
    token = existing.get("finance_token") or secrets.token_urlsafe(32)
    password = secrets.token_urlsafe(32)
    hashed = admin.pgconn.encrypt_password(password.encode(), LOGIN.encode(), b"scram-sha-256").decode()
    exists = admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (LOGIN,)).fetchone() is not None
    attrs = sql.SQL("LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 20 PASSWORD {}").format(sql.Literal(hashed))
    if exists:
        admin.execute(sql.SQL("ALTER ROLE {} ").format(sql.Identifier(LOGIN)) + attrs)
    else:
        admin.execute(sql.SQL("CREATE ROLE {} ").format(sql.Identifier(LOGIN)) + attrs)
    for role in MEMBER_OF:
        if not admin.execute("SELECT pg_has_role(%s, %s, 'MEMBER')", (LOGIN, role)).fetchone()[0]:
            admin.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(role), sql.Identifier(LOGIN)))
    admin.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(dbname), sql.Identifier(LOGIN)))
    write_secret_file(secret_path, {"host": host, "port": port, "dbname": dbname, "user": LOGIN, "password": password, "finance_token": token})
    return {"role": LOGIN, "created": not exists, "token_kept": bool(existing.get("finance_token")), "secret_file": str(secret_path)}


def check_role(admin) -> list[tuple[str, bool]]:
    one = lambda q, *p: admin.execute(q, p).fetchone()[0]  # noqa: E731
    a = admin.execute("SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, rolinherit FROM pg_roles WHERE rolname = %s", (LOGIN,)).fetchone()
    out = [("can log in", a[0] is True), ("not superuser / createdb / createrole / replication / bypassrls", not any(a[1:6])),
           ("NOINHERIT: holds no privilege until it sets a role", a[6] is False)]
    for r in MEMBER_OF:
        out.append((f"member of {r}", one("SELECT pg_has_role(%s, %s, 'MEMBER')", LOGIN, r) is True))
    for r in FORBIDDEN:
        out.append((f"NOT a member of {r}", one("SELECT pg_has_role(%s, %s, 'MEMBER')", LOGIN, r) is False))
    out.append(("no privilege of its own on any table or view in schemas cred and cash", not one(
        "SELECT bool_or(has_table_privilege(%s, c.oid, 'SELECT') OR has_table_privilege(%s, c.oid, 'INSERT') OR has_table_privilege(%s, c.oid, 'UPDATE') OR has_table_privilege(%s, c.oid, 'DELETE')) "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname IN ('cred', 'cash', 'core', 'entry', 'pnl') AND c.relkind IN ('r','v')", LOGIN, LOGIN, LOGIN, LOGIN)))
    return out


def check_login(conninfo: str) -> list[tuple[str, bool]]:
    """Log in AS the API account and prove what each role it can assume may and may not do."""
    import psycopg
    from psycopg import errors as E

    out = []
    with psycopg.connect(conninfo, autocommit=True) as c:
        out.append(("password login works as cred_api_login", c.execute("SELECT current_user").fetchone()[0] == LOGIN))
        for label, stmt in (("read items with no role set", "SELECT * FROM cred.v_open_item_candidate"), ("promote", "SELECT cred.promote_run('run_00000000_000','x')"),
                            ("purge", "SELECT cred.purge_run('run_00000000_000','x')"), ("DDL", "CREATE TABLE cred.evil (x int)"),
                            ("read cash with no role set", "SELECT * FROM cash.v_store_till"), ("promote cash", "SELECT cash.promote_run('run_00000000_000','x')"),
                            ("read entry text with no role set", "SELECT * FROM entry.v_entry_line_text"), ("promote entry", "SELECT entry.promote_run('run_00000000_000','x')")):
            try:
                c.execute(stmt)
                out.append((f"refused: {label}", False))
            except E.InsufficientPrivilege:
                out.append((f"refused: {label}", True))
        for role, view, ok in (("cred_verifier", "cred.v_open_item_candidate", True), ("cred_verifier", "cred.v_open_item_named_candidate", False),
                               ("cred_finance_reader", "cred.v_open_item_named_candidate", True), ("cred_api_reader", "cred.v_open_item_named", False),
                               ("cash_api_reader", "cash.v_store_till", True), ("cash_api_reader", "cash.store_till", False), ("cash_verifier", "cash.v_bank_ledger", True),
                               ("cash_api_reader", "core.v_domain_run", True),
                               ("entry_api_reader", "entry.v_entry_header", True), ("entry_api_reader", "entry.v_entry_line_text", False), ("entry_api_reader", "entry.v_entry_identity", False),
                               ("entry_api_reader", "entry.entry_line_text", False), ("entry_finance_reader", "entry.v_entry_line_text", True), ("entry_finance_reader", "entry.v_entry_identity", True),
                               ("entry_verifier", "entry.v_entry_line_text", False),
                               ("pnl_api_reader", "pnl.v_gl_site_month", True), ("pnl_api_reader", "pnl.gl_site_month", False), ("pnl_api_reader", "core.v_domain_run", True)):
            try:
                c.execute(f"SET ROLE {role}")
                c.execute(f"SELECT 1 FROM {view} LIMIT 1")
                got = True
            except E.InsufficientPrivilege:
                got = False
            finally:
                c.execute("RESET ROLE")
            out.append((f"as {role}: {'can' if ok else 'cannot'} read {view.split('.')[1]}", got == ok))
        for role in FORBIDDEN:
            try:
                c.execute(f"SET ROLE {role}")
                out.append((f"cannot assume {role}", False))
                c.execute("RESET ROLE")
            except E.InsufficientPrivilege:
                out.append((f"cannot assume {role}", True))
    return out


def main(argv: list[str]) -> int:
    import psycopg
    from migrate import admin_conninfo, apply, redact, with_database
    from psycopg.conninfo import conninfo_to_dict

    dbname = argv[1] if len(argv) > 1 else "fpa_pilot"
    info = admin_conninfo()
    if not info:
        print(__doc__)
        print("No administrator connection: run this in an interactive terminal.")
        return 2
    try:
        d = conninfo_to_dict(info)
        host, port = d.get("host", "localhost"), str(d.get("port", "5432"))
        with psycopg.connect(with_database(info, dbname), autocommit=True) as admin:
            ran = apply(admin)
            print(f"Migrations: {', '.join('applied ' + v for v in ran) if ran else 'already up to date'}")
            facts = provision(admin, SECRET_FILE, host, port, dbname)
            checks = check_role(admin)
        e = read_env(SECRET_FILE)
        checks += check_login(f"host={e['host']} port={e['port']} dbname={e['dbname']} user={e['user']} password={e['password']}")
    except SystemExit as e:
        print(f"STOPPED: {e}")
        return 3
    except Exception as e:  # noqa: BLE001
        print(f"FAILED: {type(e).__name__}: {redact(e)}")
        return 1
    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    bad = [n for n, ok in checks if not ok]
    print(f"\nLogin `{facts['role']}`: {'created' if facts['created'] else 're-keyed'}; Finance access token {'kept' if facts['token_kept'] else 'generated'}.")
    print(f"Secrets written to {Path(facts['secret_file']).relative_to(HERE.parents[1])} (git-ignored). Nothing secret was printed.")
    print(f"{len(checks) - len(bad)} of {len(checks)} checks pass.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
