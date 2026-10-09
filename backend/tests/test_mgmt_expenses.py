"""Store Expense / DC Expense review: head classification and aggregation on synthetic input, then a live smoke against gold_fpa
(skipped when the database or the git-ignored config/mgmt files are not available)."""
from decimal import Decimal as D

import pytest

from app.gold import db as gold
from app.mgmt import config as cfg
from app.mgmt import engine as eng
from app.mgmt import expenses as ex
from app.mgmt import service as svc

CR = 10_000_000


def row(month, kind, gl, grp, cr, site=None, entity="SUBCO"):
    return {"month": month, "site_kind": kind, "site_code": site, "entity": entity, "glname": gl, "fin_group": grp, "is_mapped": True, "pe": D(str(cr)) * CR}


ROWS = [row("2026-08", "STORE", "Sales", "01-Net Sales", 100), row("2026-08", "STORE", "Rent", "01-Rent", -5), row("2026-08", "STORE", "Wages", "02-Employee Cost", -4),
        row("2026-08", "STORE", "Director fee", "05-Director remunaration", -1), row("2026-08", "STORE", "Printing", "20-Printing & Stationery", -0.5),
        row("2026-08", "WAREHOUSE", "WH rent", "01-Rent", -2), row("2026-08", "WAREHOUSE", "Purchase disc", "02-COGS(Others)", 0.8),
        row("2026-08", "HEAD_OFFICE", "HO salary", "02-Employee Cost", -3), row("2026-08", "WAREHOUSE", "Venture WH rent", "01-Rent", -1.5, entity="HOLDCO")]


@pytest.fixture()
def book():
    return eng.build_book(ROWS, [{"month": "2026-08", "ns": D(100) * CR, "cogs": D(60) * CR}], {}, {})


def test_head_of_follows_the_engine_line_targets():
    assert ex.head_of("store", "STORES", "rent") == "rent"
    assert ex.head_of("store", "STORES", "director_remuneration") == "other_expenses"     # the engine puts it in Other expenses at stores
    assert ex.head_of("store", "STORES", "material_cost") is None and ex.head_of("store", "STORES", "revenue") is None
    assert ex.head_of("store", "DC", "rent") is None                                       # wrong location type
    assert ex.head_of("dc", "DC", "freight") == "freight"
    assert ex.head_of("dc", "DC", "material_cost") == ex.COGS_HEAD                         # purchase discounts booked at a DC
    assert ex.head_of("ho", "HO", "director_remuneration") == "other_expenses"
    assert ex.head_of("dc", "DC", "other_operating_income") is None and ex.head_of("ho", "HO", "interest_income") is None


def test_store_scope_cells_are_positive_expenses_and_sum_to_the_engine_line(book):
    cells = ex.engine_cells(book, [], "store", "consolidated", ["2026-08"])
    assert cells[("2026-08", "rent")]["book"] == D("5") and cells[("2026-08", "employee_cost")]["book"] == D("4")
    assert cells[("2026-08", "other_expenses")]["book"] == D("1.5")                        # director fee + printing
    tot = ex.tot_of(cells, ["2026-08"], ex.heads_of("store"))
    lines = {l["key"]: l for l in eng.shape_lines(eng.compute_pnl(book, [], ["2026-08"]), ["2026-08"])}
    assert tot["book"] == -lines["total_store_expenses"]["values"]["2026-08"]["book"] == D("10.5")


def test_dc_and_ho_scope_and_entity_filter(book):
    dc_all = ex.tot_of(ex.engine_cells(book, [], "dc", "consolidated", ["2026-08"]), ["2026-08"], ex.heads_of("dc"))
    assert dc_all["book"] == D("2") + D("1.5") - D("0.8")                                  # both entities' warehouses less the discount credit
    dc_hold = ex.tot_of(ex.engine_cells(book, [], "dc", "holdco", ["2026-08"]), ["2026-08"], ex.heads_of("dc"))
    assert dc_hold["book"] == D("1.5")
    assert ex.tot_of(ex.engine_cells(book, [], "store", "holdco", ["2026-08"]), ["2026-08"], ex.heads_of("store"))["book"] == 0     # HoldCo has no stores
    ho = ex.tot_of(ex.engine_cells(book, [], "ho", "consolidated", ["2026-08"]), ["2026-08"], ex.heads_of("ho"))
    assert ho["book"] == D("3")


def test_adjustments_are_added_with_the_expense_sign(book):
    items = [{"month": "2026-08", "entity": "SUBCO", "location_type": "STORES", "mis_line": "employee_cost", "amount_cr": D("-0.25"), "kind": "provision"},
             {"month": "2026-08", "entity": "SUBCO", "location_type": "STORES", "mis_line": "other_operating_income", "amount_cr": D("2"), "kind": "adjustment"}]
    c = ex.engine_cells(book, items, "store", "consolidated", ["2026-08"])
    assert c[("2026-08", "employee_cost")]["adj"] == D("0.25") and ("2026-08", "other_operating_income") not in c


def test_scopes_add_up_to_the_pnl_expense_lines(book):
    months = ["2026-08"]
    s = sum((ex.tot_of(ex.engine_cells(book, [], sc, "consolidated", months), months, ex.heads_of(sc))["book"] for sc in ("store", "dc", "ho")), D(0))
    lines = {l["key"]: l for l in eng.shape_lines(eng.compute_pnl(book, [], months), months)}
    pnl = -sum((lines[k]["values"]["2026-08"]["book"] for k in ("total_store_expenses", "dc_cost", "ho_cost")), D(0))
    assert s == pnl


def test_helpers():
    assert ex.add_months("2026-01", -1) == "2025-12" and ex.add_months("2026-04", -12) == "2025-04" and ex.add_months("2025-12", 1) == "2026-01"
    assert ex.pctile([1, 2, 3, 4, 5], 50) == 3 and ex.pctile([10], 90) == 10 and ex.pctile([], 90) is None
    assert ex.pctile([0, 10], 90) == D("9")
    assert ex.median([1, 3, 2]) == 2 and ex.median([]) is None
    assert ex.classify_entity("VENTURES") == "HOLDCO" and ex.classify_entity("RETAIL") == "SUBCO" and ex.classify_entity(None) == "SUBCO"
    assert str(ex.fy_start("2026-02")) == "2025-04-01" and str(ex.fy_start("2026-08")) == "2026-04-01"


# ------------------------------------------------------------------ live


@pytest.fixture(scope="module")
def conn():
    url = gold.database_url()
    if not url:
        pytest.skip("no DATABASE_URL")
    if not (cfg.CONFIG_DIR / "adjustments.csv").exists():
        pytest.skip("config/mgmt files not generated (tools/mgmt/seed_from_workbook.py)")
    try:
        with gold.GoldDb(url).session() as c:
            yield c
    except Exception as e:
        pytest.skip(f"gold_fpa not reachable: {type(e).__name__}")


def test_live_store_dc_ho_scope_equal_the_mgmt_pnl_apr_aug(conn):
    x = ex.load(conn, "store", "2026-04", "2026-08", "consolidated")
    c = ex.controls_engine(x)
    assert c["ok"], c["rows"]
    assert all(abs(r["variance"]) <= D("0.005") for r in c["rows"])
    for ent in ("subco", "holdco"):
        assert ex.controls_engine(ex.load(conn, "dc", "2026-04", "2026-08", ent))["ok"]


def test_live_aug26_store_heads_equal_the_mis_store_lines(conn):
    x = ex.load(conn, "store", "2026-08", "2026-08", "consolidated")
    got = {h: ex.tot_of(x.cells, x.months, (h,)) for h in ex.HEADS}
    want = {"rent": "6.90", "employee_cost": "9.42", "power_fuel": "5.24", "advertisement": "1.29", "freight": "1.99", "other_expenses": "1.06"}
    for h, v in want.items():
        assert abs(got[h]["book"] + got[h]["adj"] - D(v)) <= D("0.01"), (h, got[h])


def test_live_site_and_ledger_rows_tie_to_the_engine_book(conn):
    for scope, ent in (("store", "consolidated"), ("dc", "consolidated"), ("dc", "holdco"), ("ho", "consolidated")):
        x = ex.load(conn, scope, "2026-04", "2026-08", ent)
        r = ex.controls_rows(conn, x)
        assert r["ok"], (scope, ent, r["rows"])
        st = ex.site_table(conn, x)
        assert abs(sum((s["book_total"] for s in st["rows"]), D(0)) - ex.tot_of(x.cells, x.months, x.heads)["book"]) <= D("0.005"), (scope, ent)


def test_live_dc_scope_includes_holdco_warehouses_and_keys_on_entity_and_site(conn):
    x = ex.load(conn, "dc", "2026-08", "2026-08", "consolidated")
    st = ex.site_table(conn, x)
    keys = {r["key"] for r in st["rows"]}
    assert any(k.startswith("HOLDCO:") for k in keys) and any(k.startswith("SUBCO:") for k in keys)
    hold = ex.tot_of(ex.load(conn, "dc", "2026-08", "2026-08", "holdco").cells, ["2026-08"], ex.heads_of("dc"))
    assert hold["book"] > 0


def test_live_holdco_voucher_list_and_single_voucher_lookup_by_entity(conn):
    """The voucher drill of a HoldCo (VENTURES) site: the list joins on entity AND site, the single lookup finds it only with entity=VENTURES; the default stays RETAIL."""
    import os

    os.environ["FPA_SOURCE"] = "gold"
    from fastapi.testclient import TestClient

    from app.creditors_api.main import create_app

    c = TestClient(create_app())
    run = c.get("/api/v1/entries/current").json()["entry_run_id"]
    base = f"/api/v1/entries/runs/{run}"
    x = ex.load(conn, "dc", "2026-08", "2026-08", "holdco")
    hold = {k: v for k, v in ex.fetch_aggregates(conn, x.prev, x.hi, "dc")["led"].items() if k[0] == "HOLDCO" and "2026-08" in v}
    assert hold, "expected HoldCo warehouse postings in Aug-26"
    led = max(hold.items(), key=lambda kv: kv[1]["2026-08"][0])[0]
    site, gl = led[1], led[2]
    lst = c.get(base + "/ledger-entries", params={"site": site, "glcode": gl, "from_month": "2026-08", "to_month": "2026-08", "entity": "VENTURES"})
    assert lst.status_code == 200 and lst.json()["scope"]["entity"] == "VENTURES"
    body = lst.json()
    assert body["total"]["entries"] > 0
    if True:
        assert body["reconciles"] in (True, None)
        ref = body["entries"][0]["entry_ref"]
        assert c.get(base + f"/entry/{ref}", params={"entity": "VENTURES"}).status_code == 200
        assert c.get(base + f"/entry/{ref}").status_code == 404                   # default RETAIL: a Ventures voucher is not found there
    assert c.get(base + "/ledger-entries", params={"site": site, "entity": "NOPE"}).status_code == 422
