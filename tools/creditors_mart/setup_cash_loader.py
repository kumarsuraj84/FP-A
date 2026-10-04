"""
One-time setup of the Cash loader login, run by the administrator in THEIR OWN terminal (after migrations 003 and 004 are applied).

    python tools/creditors_mart/setup_cash_loader.py            # asks for the admin connection (password hidden), database defaults to fpa_pilot

It creates (or re-keys) the login `cash_loader_login`: a member of cash_loader and of NO other mart role, not superuser / createdb / createrole /
replication / bypassrls. A random password is generated here, sent to PostgreSQL ONLY as a SCRAM hash, and written ONLY to the git-ignored file
.secrets/cash_loader.env. It is never printed or logged. The script then proves the restrictions by logging in as the account and being refused
promote, demote, DDL, update, delete and any access to creditors data.
"""
from __future__ import annotations

import secrets
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from setup_loader import read_env, write_secret_file  # noqa: E402

LOGIN = "cash_loader_login"
SECRET_FILE = HERE.parents[1] / ".secrets" / "cash_loader.env"
OTHER_ROLES = ["cash_owner", "cash_promoter", "cash_verifier", "cash_api_reader", "cred_owner", "cred_loader", "cred_promoter", "cred_verifier", "cred_api_reader", "cred_finance_reader"]


def provision(admin, secret_path: Path, host: str, port: str, dbname: str) -> dict:
    from psycopg import sql

    is_admin = admin.execute("SELECT rolsuper OR (rolcreaterole AND rolcreatedb) FROM pg_roles WHERE rolname = current_user").fetchone()[0]
    if not is_admin:
        raise SystemExit("this account is not an administrator; nothing was changed")
    if not admin.execute("SELECT 1 FROM pg_roles WHERE rolname = 'cash_loader'").fetchone():
        raise SystemExit("role cash_loader does not exist: run migrate.py first")
    if admin.execute("SELECT current_database()").fetchone()[0] in ("fpa", "postgres", "template0", "template1"):
        raise SystemExit("refusing to use this database")
    password = secrets.token_urlsafe(32)
    hashed = admin.pgconn.encrypt_password(password.encode(), LOGIN.encode(), b"scram-sha-256").decode()
    exists = admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (LOGIN,)).fetchone() is not None
    attrs = sql.SQL("LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT CONNECTION LIMIT 5 PASSWORD {}").format(sql.Literal(hashed))
    if exists:
        admin.execute(sql.SQL("ALTER ROLE {} ").format(sql.Identifier(LOGIN)) + attrs)
    else:
        admin.execute(sql.SQL("CREATE ROLE {} ").format(sql.Identifier(LOGIN)) + attrs + sql.SQL(" IN ROLE cash_loader"))
    admin.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(dbname), sql.Identifier(LOGIN)))
    write_secret_file(secret_path, {"host": host, "port": port, "dbname": dbname, "user": LOGIN, "password": password})
    return {"role": LOGIN, "created": not exists, "secret_file": str(secret_path)}


def check_role(admin) -> list[tuple[str, bool]]:
    one = lambda q, *p: admin.execute(q, p).fetchone()[0]  # noqa: E731
    a = admin.execute("SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname = %s", (LOGIN,)).fetchone()
    out = [("can log in", a[0] is True), ("not superuser / createdb / createrole / replication / bypassrls", not any(a[1:6])),
           ("member of cash_loader", one("SELECT pg_has_role(%s, 'cash_loader', 'MEMBER')", LOGIN) is True)]
    others = admin.execute("SELECT r FROM unnest(%s::text[]) r WHERE pg_has_role(%s, r, 'MEMBER')", (OTHER_ROLES, LOGIN)).fetchall()
    out.append(("member of no other mart role", not others))
    for fn in ("promote_run(text, text)", "demote_to(text, text)", "api_verify_run(text)"):
        out.append((f"cannot execute cash.{fn.split('(')[0]}", one("SELECT has_function_privilege(%s, %s, 'EXECUTE')", LOGIN, f"cash.{fn}") is False))
    for t in ("run", "store_till", "bank_ledger", "control_result"):
        out.append((f"cannot update or delete cash.{t}", not one("SELECT has_table_privilege(%s, %s, 'UPDATE') OR has_table_privilege(%s, %s, 'DELETE')", LOGIN, f"cash.{t}", LOGIN, f"cash.{t}")))
    out.append(("no CREATE in schema cash or the database", not one("SELECT has_schema_privilege(%s, 'cash', 'CREATE') OR has_database_privilege(%s, current_database(), 'CREATE')", LOGIN, LOGIN)))
    out.append(("no access to creditors data", not one("SELECT has_schema_privilege(%s, 'cred', 'USAGE')", LOGIN)))
    return out


def check_login(conninfo: str) -> list[tuple[str, bool]]:
    import psycopg
    from psycopg import errors as E

    out = []
    with psycopg.connect(conninfo, autocommit=True) as c:
        out.append(("password login works as cash_loader_login", c.execute("SELECT current_user").fetchone()[0] == LOGIN))
        for label, stmt in (("promote", "SELECT cash.promote_run('run_00000000_000','x')"), ("demote", "SELECT cash.demote_to('run_00000000_000','x')"),
                            ("DDL", "CREATE TABLE cash.evil (x int)"), ("update", "UPDATE cash.store_till SET cumulative_balance = cumulative_balance"),
                            ("delete", "DELETE FROM cash.store_till"), ("read creditors items", "SELECT * FROM cred.v_open_item_candidate")):
            try:
                c.execute(stmt)
                out.append((f"refused: {label}", False))
            except E.InsufficientPrivilege:
                out.append((f"refused: {label}", True))
            except Exception:  # noqa: BLE001
                out.append((f"refused: {label}", False))
    return out


def main(argv: list[str]) -> int:
    import psycopg
    from migrate import admin_conninfo, redact, with_database
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
    print(f"\nLogin `{facts['role']}`: {'created' if facts['created'] else 're-keyed'}.")
    print(f"Secrets written to {Path(facts['secret_file']).relative_to(HERE.parents[1])} (git-ignored). Nothing secret was printed.")
    print(f"{len(checks) - len(bad)} of {len(checks)} checks pass.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
