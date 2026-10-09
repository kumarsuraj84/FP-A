"""Gold source mode: the APIs read `gold_fpa` in the common Postgres (role fpa_ro, read-only) instead of the run-versioned cred/cash/pnl marts.
Enabled with FPA_SOURCE=gold. DATABASE_URL (postgresql+asyncpg://... is accepted) comes from the environment or the git-ignored backend/.env.
The per-API roles of the old mart do not exist here: every session is one read-only transaction as fpa_ro."""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

BACKEND = Path(__file__).resolve().parents[2]


def enabled() -> bool:
    return os.environ.get("FPA_SOURCE", "").lower() == "gold"


def database_url() -> str | None:
    url = os.environ.get("DATABASE_URL")
    env = BACKEND / ".env"
    if not url and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                url = line.split("=", 1)[1].strip()
    return url.replace("postgresql+asyncpg://", "postgresql://") if url else None


def vendor_salt() -> str:
    """Stable secret for the pseudonymous vendor_ref. Generated once into the git-ignored .secrets folder."""
    s = os.environ.get("FPA_VENDOR_SALT")
    if s:
        return s
    p = BACKEND.parent / ".secrets" / "vendor_salt"
    if not p.exists():
        import secrets
        p.parent.mkdir(exist_ok=True)
        p.write_text(secrets.token_hex(32))
    return p.read_text().strip()


def relations() -> dict[str, str]:
    """Old-mart view name -> SELECT over gold_fpa. Each domain module (cash, pnl, entry) exports RELATIONS = {"cash.v_store_till": "SELECT ..."}."""
    from importlib import import_module
    out: dict[str, str] = {}
    for mod in ("cash", "pnl", "entry"):
        try:
            m = import_module(f"{__package__}.{mod}")
            out.update(m.RELATIONS)
            out.update(getattr(m, "EXTRA_RELATIONS", {}))
        except ModuleNotFoundError as e:
            if e.name != f"{__package__}.{mod}":
                raise
    return out


class GoldConn:
    """Wraps a read-only psycopg connection. A statement that names an old mart view (e.g. cash.v_store_till) gets a WITH clause that
    defines it over gold_fpa, so the API repositories keep their SQL unchanged."""
    def __init__(self, conn, rel: dict[str, str]):
        self._c, self._rel = conn, rel

    def execute(self, sql, params=None):
        import re
        word = lambda n: chr(92) + "b" + re.escape(n) + chr(92) + "b"   #  word boundaries
        used = [n for n in self._rel if re.search(word(n), sql)]
        if used:
            ctes = ", ".join(f'{n.replace(".", "__")} AS ({self._rel[n]})' for n in used)
            for n in used:
                sql = re.sub(word(n), n.replace(".", "__"), sql)
            sql = f"WITH {ctes} {sql}"
        return self._c.execute(sql, params)

    def rollback(self):
        self._c.rollback()

    def close(self):
        self._c.close()


class GoldDb:
    def __init__(self, conninfo: str):
        self.conninfo = conninfo
        self.rel = relations()

    @contextmanager
    def session(self, role_key: str = "live", readonly: bool = True):
        conn = psycopg.connect(self.conninfo, autocommit=False, row_factory=dict_row,
                               options="-c statement_timeout=90000 -c default_transaction_read_only=on")
        try:
            yield GoldConn(conn, self.rel)
        finally:
            conn.rollback()
            conn.close()
