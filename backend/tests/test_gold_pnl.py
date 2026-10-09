"""Gold P&L relations: coverage of every pnl.* view the API names (offline) and, when gold_fpa is reachable, a live cross-check of totals."""
import re
from pathlib import Path

import pytest

from app.gold import db as gold
from app.gold import pnl

API = Path(__file__).resolve().parents[1] / "app" / "pnl_api"


def test_every_referenced_view_is_defined():
    used = set()
    for f in API.glob("*.py"):
        used |= set(re.findall(r"pnl\.(v_[a-z_]+)", f.read_text(encoding="utf-8")))
    assert used, "no pnl views found"
    assert {f"pnl.{u}" for u in used} <= set(pnl.RELATIONS)


def test_relations_have_no_percent_sign():
    assert not [k for k, v in pnl.RELATIONS.items() if "%" in v]


@pytest.fixture(scope="module")
def conn():
    url = gold.database_url()
    if not url:
        pytest.skip("no DATABASE_URL")
    try:
        with gold.GoldDb(url).session() as c:
            yield c
    except Exception as e:  # unreachable database
        pytest.skip(f"gold_fpa not reachable: {type(e).__name__}")


def test_live_totals_match_source(conn):
    run = conn.execute("SELECT * FROM pnl.v_serving_run").fetchone()
    assert run["publication_state"] == "live" and run["run_id"].startswith("PNL-")
    a = conn.execute("SELECT sum(credit - debit) AS v FROM pnl.v_gl_site_month WHERE section = 'REVENUE'").fetchone()["v"]
    b = conn.execute("SELECT sum(credit - debit) AS v FROM gold_fpa.pnl_store_month WHERE fin_group = '01-Net Sales'").fetchone()["v"]
    assert a == b
    assert conn.execute("SELECT count(*) AS n FROM pnl.v_control WHERE verdict <> 'PASS'").fetchone()["n"] == 0
