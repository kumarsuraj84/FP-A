"""Static checks of the gold entry relations (no database needed) plus a live smoke test when FPA_SOURCE=gold and DATABASE_URL are available."""
import os

import pytest

from app.gold import entry
from app.gold.db import database_url

EXPECTED = {"entry.v_serving_run", "entry.v_entry_header", "entry.v_entry_line", "entry.v_entry_line_text", "entry.v_entry_identity",
            "entry.v_till_day", "entry.v_creditor_bill_link", "entry.v_bank_entry", "entry.v_control"}


def test_every_entry_relation_is_defined():
    assert set(entry.RELATIONS) == EXPECTED


def test_no_percent_sign_in_relation_sql():
    for name, sql in entry.RELATIONS.items():
        assert "%" not in sql, name


@pytest.mark.skipif(os.environ.get("FPA_SOURCE", "").lower() != "gold" or not database_url(), reason="gold database not configured")
def test_live_smoke():
    import psycopg
    from psycopg.rows import dict_row
    from app.gold.db import GoldConn, relations
    c = GoldConn(psycopg.connect(database_url(), row_factory=dict_row, options="-c default_transaction_read_only=on"), relations())
    try:
        run = c.execute("SELECT * FROM entry.v_serving_run").fetchone()
        assert run["recon_state"] == "verified" and run["publication_state"] == "live"
        bad = c.execute("SELECT count(*) AS n FROM entry.v_control WHERE verdict <> 'PASS'").fetchone()["n"]
        assert bad == 0
    finally:
        c.close()
