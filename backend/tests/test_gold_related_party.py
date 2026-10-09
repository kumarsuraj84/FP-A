"""Related-party register parsing, the main/related exclusion SQL, and a live smoke (skipped when the gold database is unreachable)."""
import os
from decimal import Decimal

import pytest

from app.gold import creditors as gc, related_register as rr

CSV = """sub_ledger_code,party_name,group_entity,relationship,basis,status,note
13804,CKSPL Haryana Cross Charge,CKSPL,cross charge,name,proposed,
4414,CITYKART RETAIL PVT LTD (Haryana),Retail,group company,name,CONFIRMED,n
4414,duplicate row is ignored,x,x,x,proposed,
abc,not numeric,x,x,x,proposed,
6013,Odd status,Retail,group company,name,maybe,
"""


@pytest.fixture
def register(tmp_path, monkeypatch):
    p = tmp_path / "rp.csv"
    p.write_text(CSV, encoding="utf-8")
    monkeypatch.setenv("FPA_RELATED_PARTIES", str(p))
    monkeypatch.setattr(rr, "_cache", None)
    yield p
    monkeypatch.setattr(rr, "_cache", None)


def test_parse_register(register):
    rows = rr.load()
    assert [r["sub_ledger_code"] for r in rows] == [13804, 4414, 6013]
    assert rows[1]["status"] == "confirmed" and rows[2]["status"] == "proposed"      # case-insensitive; unknown status -> proposed
    assert rows[1]["party_name"] == "CITYKART RETAIL PVT LTD (Haryana)"             # first duplicate wins
    assert rr.in_list() == "13804, 4414, 6013"


def test_exclusion_sql(register):
    main, rel, allp = gc.items(True), gc.items(True, "related"), gc.items(True, "all")
    assert "coalesce(sub_ledger_code, -1) NOT IN (13804, 4414, 6013)" in main
    assert "WHERE sub_ledger_code IN (13804, 4414, 6013)" in rel
    assert "NOT IN" not in allp and "WHERE" not in allp.split("FROM gold_fpa.creditors_open_items")[1]
    with pytest.raises(ValueError):
        gc.items(True, "bogus")


def test_missing_register_excludes_nothing(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("FPA_RELATED_PARTIES", str(tmp_path / "nope.csv"))
    monkeypatch.setattr(rr, "_cache", None)
    with caplog.at_level("WARNING"):
        assert rr.codes() == []
    assert "not found" in caplog.text
    assert "NOT IN" not in gc.items(False) and "WHERE" not in gc.items(False).split("FROM gold_fpa.creditors_open_items")[1]
    assert "WHERE false" in gc.items(False, "related")
    monkeypatch.setattr(rr, "_cache", None)


def test_example_file_is_parseable():
    ex = rr.ROOT / "config" / "mgmt" / "related_parties.example.csv"
    assert ex.exists() and rr.parse(ex.read_text(encoding="utf-8"))


def _client():
    if os.environ.get("FPA_SOURCE", "").lower() != "gold":
        pytest.skip("FPA_SOURCE=gold not set")
    from app.gold.db import database_url
    if not database_url():
        pytest.skip("gold database not configured")
    from fastapi.testclient import TestClient
    from app.creditors_api.main import create_app
    app = create_app()
    if not app.state.settings.finance_token:
        pytest.skip("finance token not configured")
    try:
        import psycopg
        psycopg.connect(database_url(), connect_timeout=5).close()
    except Exception:
        pytest.skip("gold database unreachable")
    return TestClient(app), {"Authorization": f"Bearer {app.state.settings.finance_token}"}


def test_live_smoke():
    rr.reload()
    if not {4414, 6013, 13804} <= set(rr.codes()):
        pytest.skip("register does not hold the seeded sub-ledgers")
    c, h = _client()
    d = c.get("/api/v1/related-party/summary", headers=h).json()
    ctl = d["controls"]
    assert ctl["main_plus_related_equals_all"] is True
    assert abs(Decimal(ctl["main_payable"]) + Decimal(ctl["related_payable"]) - Decimal(ctl["all_payable"])) <= Decimal("50000")      # 0.005 Cr
    assert Decimal(d["creditors"]["payable"]) > 0 and d["loans"]["available"] in (True, False)
    rid = c.get("/api/v1/creditors/current").json()["extraction_run_id"]
    vendors = c.get(f"/api/v1/creditors/runs/{rid}/finance/vendors?limit=500", headers=h).json()["vendors"]
    assert not {4414, 6013, 13804} & {int(v["sub_ledger_code"]) for v in vendors}
    s = c.get(f"/api/v1/creditors/runs/{rid}/summary").json()
    assert Decimal(s["related_party_excluded"]["payable_inr"]) == Decimal(ctl["related_payable"])
    assert Decimal(s["credit_outstanding"]) == Decimal(ctl["main_payable"])
    assert c.get("/api/v1/related-party/items?sub_ledger_code=1", headers=h).status_code == 404
