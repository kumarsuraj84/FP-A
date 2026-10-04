"""
Apply the creditors pilot mart migrations to ONE database, as a database administrator.

    set FPA_PG_ADMIN_URL=postgresql://<admin>:<password>@localhost:5432/<database>     (environment only; never in the repository)
    python tools/creditors_mart/migrate.py            # applies 000_roles.sql then 001_cred_schema.sql to that database

The database named in the URL must already exist (create `fpa_pilot` as the admin, empty). 000 creates the five NOLOGIN roles
(cluster-wide); 001 creates schema `cred` owned by cred_owner. The scripts refuse to run twice. Passwords or LOGIN roles for the
five roles are attached by the admin afterwards and never stored here.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SQL_DIR = Path(__file__).resolve().parent / "sql"
SCRIPTS = ["000_roles.sql", "001_cred_schema.sql"]


def read_scripts() -> list[tuple[str, str]]:
    return [(name, (SQL_DIR / name).read_text(encoding="utf-8")) for name in SCRIPTS]


def apply(conn) -> None:
    """Apply every migration on an open admin connection (autocommit). Raises on the first error."""
    for name, sql in read_scripts():
        conn.execute(sql)


def main() -> int:
    url = os.environ.get("FPA_PG_ADMIN_URL")
    if not url:
        print(__doc__)
        return 2
    import psycopg

    with psycopg.connect(url, autocommit=True) as conn:
        db = conn.execute("SELECT current_database()").fetchone()[0]
        who = conn.execute("SELECT current_user").fetchone()[0]
        print(f"Applying to database '{db}' as '{who}'")
        apply(conn)
        print("Done: roles and schema cred created.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
