"""One short transaction per request, running as exactly one cred role. The database decides what that role may read."""
from __future__ import annotations

from contextlib import contextmanager

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

ROLES = {"candidate": "cred_verifier", "live": "cred_api_reader", "finance": "cred_finance_reader", "cash": "cash_api_reader", "cash_verifier": "cash_verifier", "entry": "entry_api_reader", "entry_finance": "entry_finance_reader", "entry_verifier": "entry_verifier"}


class Db:
    def __init__(self, conninfo: str):
        self.conninfo = conninfo

    @contextmanager
    def session(self, role_key: str, readonly: bool = True):
        """Reads are always read-only. Only the reconciliation step asks for readonly=False, to record controls through the verifier's function."""
        role = ROLES[role_key]                                     # whitelist: never a caller-supplied role name
        opts = "-c statement_timeout=60000" + (" -c default_transaction_read_only=on" if readonly else "")
        conn = psycopg.connect(self.conninfo, autocommit=False, row_factory=dict_row, options=opts)
        try:
            conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
            yield conn
            if not readonly:
                conn.commit()
        finally:
            conn.rollback()
            conn.close()
