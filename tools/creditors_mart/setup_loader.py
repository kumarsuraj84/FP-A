"""
One-time setup of the loader login, run by the administrator in THEIR OWN terminal.

    python tools/creditors_mart/setup_loader.py            # asks for the admin connection (password hidden), database defaults to fpa_pilot

It creates (or re-keys) the login `cred_loader_login`:
  * a member of cred_loader and of NO other cred role; not superuser / createdb / createrole / replication / bypassrls;
  * a random 43-character password that is generated here, sent to PostgreSQL ONLY as a SCRAM hash (so it cannot appear in statement
    logs), and written ONLY to the git-ignored file .secrets/cred_loader.env. It is never printed, logged or typed by anyone;
  * a random 64-character vendor pseudonym key, created once and then never changed (re-running keeps the existing key, because a
    changed key would change every pseudonymous vendor reference; the loader refuses a load whose key differs from the previous run).
It then proves the restrictions by logging in as that account and being refused promote, demote, purge, DDL, update and delete.
"""
from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
LOGIN = "cred_loader_login"
SECRET_FILE = HERE.parents[1] / ".secrets" / "cred_loader.env"
OTHER_CRED_ROLES = ["cred_owner", "cred_promoter", "cred_verifier", "cred_api_reader", "cred_finance_reader"]


def read_env(path: Path) -> dict:
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def write_secret_file(path: Path, values: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "# git-ignored. Local secrets for the creditors loader. Never share or commit.\n" + "".join(f"{k}={v}\n" for k, v in values.items())
    path.write_text(body, encoding="utf-8")
    try:  # best effort: only the current Windows user may read it
        user = os.environ.get("USERNAME")
        if os.name == "nt" and user:
            subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"], capture_output=True, timeout=20)
        else:
            os.chmod(path, 0o600)
    except Exception:  # noqa: BLE001
        pass


def provision(admin, secret_path: Path, host: str, port: str, dbname: str) -> dict:
    """Create or re-key the login on an open ADMIN connection to the target database and write the secrets file. Returns facts only (no secrets)."""
    from psycopg import sql

    is_admin = admin.execute("SELECT rolsuper OR (rolcreaterole AND rolcreatedb) FROM pg_roles WHERE rolname = current_user").fetchone()[0]
    if not is_admin:
        raise SystemExit("this account is not an administrator; nothing was changed")
    if not admin.execute("SELECT 1 FROM pg_roles WHERE rolname = 'cred_loader'").fetchone():
        raise SystemExit("role cred_loader does not exist: run migrate.py first")
    if admin.execute("SELECT current_database()").fetchone()[0] in ("fpa", "postgres", "template0", "template1"):
        raise SystemExit("refusing to use this database")
    existing = read_env(secret_path)
    salt = existing.get("vendor_ref_salt") or secrets.token_urlsafe(48)
    if len(salt) < 32:
        raise SystemExit("the existing vendor_ref_salt is shorter than 32 characters; remove it deliberately if you really mean to replace it")
    password = secrets.token_urlsafe(32)
    # PostgreSQL receives only the SCRAM hash, so the password cannot reach a statement log
    hashed = admin.pgconn.encrypt_password(password.encode(), LOGIN.encode(), b"scram-sha-256").decode()
    exists = admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (LOGIN,)).fetchone() is not None
    attrs = sql.SQL("LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT CONNECTION LIMIT 5 PASSWORD {}").format(sql.Literal(hashed))
    if exists:
        admin.execute(sql.SQL("ALTER ROLE {} ").format(sql.Identifier(LOGIN)) + attrs)
    else:
        admin.execute(sql.SQL("CREATE ROLE {} ").format(sql.Identifier(LOGIN)) + attrs + sql.SQL(" IN ROLE cred_loader"))
    admin.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(dbname), sql.Identifier(LOGIN)))
    write_secret_file(secret_path, {"host": host, "port": port, "dbname": dbname, "user": LOGIN, "password": password, "vendor_ref_salt": salt})
    return {"role": LOGIN, "created": not exists, "rekeyed": exists, "salt_kept": bool(existing.get("vendor_ref_salt")), "secret_file": str(secret_path)}


def check_role(admin) -> list[tuple[str, bool]]:
    """Catalog checks on the login, as the administrator."""
    one = lambda q, *p: admin.execute(q, p).fetchone()[0]  # noqa: E731
    out = []
    attrs = admin.execute("SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, rolinherit FROM pg_roles WHERE rolname = %s", (LOGIN,)).fetchone()
    out.append(("can log in", attrs[0] is True))
    out.append(("not superuser / createdb / createrole / replication / bypassrls", not any(attrs[1:6])))
    out.append(("member of cred_loader", one("SELECT pg_has_role(%s, 'cred_loader', 'MEMBER')", LOGIN) is True))
    others = admin.execute("SELECT r FROM unnest(%s::text[]) r WHERE pg_has_role(%s, r, 'MEMBER')", (OTHER_CRED_ROLES, LOGIN)).fetchall()
    out.append(("member of no other cred role", not others))
    for fn in ("promote_run(text, text)", "demote_to(text, text)", "purge_run(text, text)", "set_policy(boolean, boolean, text)", "api_verify_run(text)", "ui_verify_run(text)"):
        out.append((f"cannot execute {fn.split('(')[0]}", one("SELECT has_function_privilege(%s, %s, 'EXECUTE')", LOGIN, f"cred.{fn}") is False))
    for t in ("run", "open_item", "vendor_snapshot", "identity_snapshot", "control_result"):
        out.append((f"cannot update or delete cred.{t}", not one("SELECT has_table_privilege(%s, %s, 'UPDATE') OR has_table_privilege(%s, %s, 'DELETE')", LOGIN, f"cred.{t}", LOGIN, f"cred.{t}")))
    out.append(("no CREATE in schema cred or the database", not one("SELECT has_schema_privilege(%s, 'cred', 'CREATE') OR has_database_privilege(%s, current_database(), 'CREATE')", LOGIN, LOGIN)))
    out.append(("no access to the named (vendor name) view", one("SELECT has_table_privilege(%s, 'cred.v_open_item_named', 'SELECT')", LOGIN) is False))
    return out


def check_login(conninfo: str) -> list[tuple[str, bool]]:
    """Log in AS the loader account and prove it is refused everything outside loading."""
    import psycopg
    from psycopg import errors as E

    out = []
    with psycopg.connect(conninfo, autocommit=True) as c:
        who = c.execute("SELECT current_user").fetchone()[0]
        out.append(("password login works as cred_loader_login", who == LOGIN))
        for label, stmt in (("promote", "SELECT cred.promote_run('run_00000000_000','x')"), ("demote", "SELECT cred.demote_to('run_00000000_000','x')"),
                            ("purge", "SELECT cred.purge_run('run_00000000_000','x')"), ("DDL", "CREATE TABLE cred.evil (x int)"),
                            ("update", "UPDATE cred.open_item SET pending = pending"), ("delete", "DELETE FROM cred.open_item"),
                            ("read vendor names via the named view", "SELECT * FROM cred.v_open_item_named")):
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
        checks += check_login((lambda e: f"host={e['host']} port={e['port']} dbname={e['dbname']} user={e['user']} password={e['password']}")(read_env(SECRET_FILE)))
    except SystemExit as e:
        print(f"STOPPED: {e}")
        return 3
    except Exception as e:  # noqa: BLE001
        print(f"FAILED: {type(e).__name__}: {redact(e)}")
        return 1
    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    bad = [n for n, ok in checks if not ok]
    print(f"\nLogin `{facts['role']}`: {'created' if facts['created'] else 're-keyed'}; vendor pseudonym key {'kept' if facts['salt_kept'] else 'generated (keep it for ever)'}.")
    print(f"Secrets written to {Path(facts['secret_file']).relative_to(HERE.parents[1])} (git-ignored). Nothing secret was printed.")
    print(f"{len(checks) - len(bad)} of {len(checks)} checks pass.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
