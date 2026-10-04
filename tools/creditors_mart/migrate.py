"""
Apply the creditors pilot mart migrations as a database administrator.

    Simplest: run the command in your own terminal and it asks for host, port, admin user and password (the password is hidden,
    never echoed, never stored). A credential is never typed into chat or a file.
    Alternative (scripted): PowerShell   $env:FPA_PG_ADMIN_URL = "postgresql://<admin>:<password>@localhost:5432/postgres"
    (a password containing @ : / must be percent-encoded in a URL, e.g. @ as %40; the prompt avoids that problem)

    python tools/creditors_mart/migrate.py --create-database fpa_pilot     # creates the empty database if missing, then applies 000 and 001
    python tools/creditors_mart/migrate.py                                 # applies to the database named in the URL (which must already exist)

000_roles.sql creates the six NOLOGIN roles (cluster-wide); 001_cred_schema.sql creates schema `cred` owned by cred_owner.
The scripts refuse to run twice. The credential is read from the environment only; it is never printed, logged or written anywhere.
LOGIN roles or passwords for the six roles are attached by the administrator afterwards and are never stored here.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

SQL_DIR = Path(__file__).resolve().parent / "sql"
SCRIPTS = ["000_roles.sql", "001_cred_schema.sql", "002_candidate_views.sql"]
VERSIONS = {"001_cred_schema.sql": "001", "002_candidate_views.sql": "002"}
#: databases this tool will never create or migrate: the application database and the maintenance database
PROTECTED = {"fpa", "postgres", "template0", "template1"}
_SECRET = re.compile(r"(://[^:/@\s]+:)[^@\s]*@")


def redact(text: object) -> str:
    return _SECRET.sub(r"\1***@", str(text))[:400]


def read_scripts() -> list[tuple[str, str]]:
    return [(name, (SQL_DIR / name).read_text(encoding="utf-8")) for name in SCRIPTS]


def applied_versions(conn) -> set[str]:
    """What is installed: nothing, a 001-only install (before the migration ledger existed), or whatever the ledger records."""
    if not conn.execute("SELECT 1 FROM pg_namespace WHERE nspname = 'cred'").fetchone():
        return set()
    if conn.execute("SELECT to_regclass('cred.schema_migration')").fetchone()[0] is None:
        return {"001"}
    return {r[0] for r in conn.execute("SELECT version FROM cred.schema_migration")}


def apply(conn) -> list[str]:
    """Apply what is pending, in order, on an open admin connection (autocommit). Returns the versions applied (empty when up to date).
    Roles (000) are idempotent and always run; each numbered migration runs once and 001 still refuses to run twice."""
    done = applied_versions(conn)
    ran = []
    for name, sql in read_scripts():
        version = VERSIONS.get(name)
        if version is None or version not in done:
            conn.execute(sql)
            if version:
                ran.append(version)
    return ran


def admin_conninfo() -> str | None:
    """The administrator connection: FPA_PG_ADMIN_URL if set, otherwise an interactive prompt (never echoed, never stored)."""
    url = os.environ.get("FPA_PG_ADMIN_URL")
    if url:
        return url
    if not sys.stdin.isatty():
        return None
    import getpass

    from psycopg.conninfo import make_conninfo

    try:
        host = input("PostgreSQL host [localhost]: ").strip() or "localhost"
        port = input("Port [5432]: ").strip() or "5432"
        user = input("Admin user [postgres]: ").strip() or "postgres"
        password = getpass.getpass("Admin password (hidden, not stored): ")
    except (EOFError, KeyboardInterrupt):                 # no real terminal attached
        return None
    return make_conninfo(host=host, port=port, user=user, password=password, dbname="postgres")


def with_database(url: str, dbname: str) -> str:
    """The same server and credential, another database. Works for URL and key=value connection strings."""
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    return make_conninfo(**{**conninfo_to_dict(url), "dbname": dbname})


def create_database(url: str, name: str) -> bool:
    """Create an empty database if it does not exist. Returns True when it was created."""
    import psycopg
    from psycopg import sql

    if name in PROTECTED:
        raise SystemExit(f"refusing to create or touch '{name}'")
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,40}", name):
        raise SystemExit("database name must be lowercase letters, digits and underscores")
    with psycopg.connect(with_database(url, "postgres"), autocommit=True) as conn:
        if conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
            return False
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        return True


def main(argv: list[str]) -> int:
    url = admin_conninfo()
    if not url:
        print(__doc__)
        print("No administrator connection available: run this in an interactive terminal, or set FPA_PG_ADMIN_URL.")
        return 2
    import psycopg

    target = None
    if "--create-database" in argv:
        target = argv[argv.index("--create-database") + 1]
    try:
        if target:
            created = create_database(url, target)
            print(f"Database '{target}': {'created' if created else 'already exists (left as is)'}")
            conn_url = with_database(url, target)
        else:
            conn_url = url
        with psycopg.connect(conn_url, autocommit=True) as conn:
            db = conn.execute("SELECT current_database()").fetchone()[0]
            who = conn.execute("SELECT current_user").fetchone()[0]
            if db in PROTECTED:
                print(f"refusing to migrate '{db}'")
                return 3
            is_admin = conn.execute("SELECT rolsuper OR (rolcreatedb AND rolcreaterole) FROM pg_roles WHERE rolname = current_user").fetchone()[0]
            if not is_admin:
                print(f"'{who}' is not an administrator (needs superuser, or CREATEDB and CREATEROLE). Nothing was changed.")
                return 3
            print(f"Applying to database '{db}' as '{who}'")
            ran = apply(conn)
            print(f"Done: applied {', '.join(ran)}." if ran else "Done: already up to date, nothing applied.")
    except Exception as e:  # noqa: BLE001
        print(f"FAILED: {type(e).__name__}: {redact(e)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
