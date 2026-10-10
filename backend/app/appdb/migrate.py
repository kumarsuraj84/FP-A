"""Apply backend/migrations/fpa_app/*.sql to the app database `fpa_app` in order, once each.

  python -m app.appdb.migrate            apply pending files
  python -m app.appdb.migrate --status   list applied / pending

Connects as fpa_app_migrator and runs SET ROLE fpa_app_owner so every object is owned by the owner role (the app login cannot alter or drop them). Each file
runs in one transaction with its checksum recorded; an applied file that has since changed is refused, never re-run. Passwords come from backend/.env
(FPA_MIGRATOR_PASSWORD); host and port from DATABASE_URL.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg

from .conn import env

DIR = Path(__file__).resolve().parents[2] / "migrations" / "fpa_app"


def files() -> list[Path]:
    return sorted(DIR.glob("[0-9][0-9][0-9]_*.sql"))


def connect():
    e = env()
    u = urlparse(e["DATABASE_URL"])
    return psycopg.connect(host=u.hostname, port=u.port or 5432, dbname="fpa_app", user="fpa_app_migrator", password=e["FPA_MIGRATOR_PASSWORD"], autocommit=False)


def main(argv: list[str]) -> int:
    with connect() as c:
        c.execute("SET ROLE fpa_app_owner")
        have = {}
        if c.execute("SELECT to_regclass('fpa_app.schema_migration') IS NOT NULL").fetchone()[0]:
            have = dict(c.execute("SELECT version, checksum FROM fpa_app.schema_migration").fetchall())
        c.rollback()
        todo = []
        for f in files():
            sha = hashlib.sha256(f.read_bytes()).hexdigest()
            if f.stem in have:
                if have[f.stem] != sha:
                    print(f"REFUSED {f.name}: applied earlier but the file has changed; add a new migration instead")
                    return 2
                print(f"applied  {f.name}")
            else:
                print(f"pending  {f.name}")
                todo.append((f, sha))
        if "--status" in argv:
            return 0
        for f, sha in todo:
            c.execute("SET ROLE fpa_app_owner")
            c.execute(f.read_text(encoding="utf-8"))
            c.execute("INSERT INTO fpa_app.schema_migration (version, checksum) VALUES (%s, %s)", (f.stem, sha))
            c.commit()
            print(f"APPLIED  {f.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
