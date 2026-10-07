"""The P&L review layer (pivot, MTD/QTD/YTD, PSF, heat map, peers, exceptions, quality) on a PRIVATE, THROWAWAY PostgreSQL with a RICH SYNTHETIC run (pl_synth.py). Every expected number is
recomputed here from the generator, not from the code under test."""
from __future__ import annotations

import shutil
import statistics
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT.parent / "backend"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(ROOT / "extraction_broker"))
sys.path.insert(0, str(ROOT / "extraction_broker" / "tests"))
sys.path.insert(0, str(HERE))
import migrate  # noqa: E402
import pl_stage as ps  # noqa: E402
import pl_synth as syn  # noqa: E402
import pnl_loader as pl  # noqa: E402
from app.creditors_api.config import ApiSettings  # noqa: E402
from app.creditors_api.db import Db  # noqa: E402
from app.creditors_api.main import create_app  # noqa: E402
from test_cred_mart_db import PG_BIN, Cluster  # noqa: E402

pytestmark = pytest.mark.skipif(not (PG_BIN / "initdb.exe").exists() and not shutil.which("initdb"), reason="PostgreSQL server binaries not found")
RUN = "run_20261007_910"
D = Decimal
SEP, OCT = date(2026, 9, 1), date(2026, 10, 1)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("pnl_review")
    c = Cluster(tmp_path_factory.mktemp("pg_pnl_review"))
    c.start()
    with c.connect("postgres") as a:
        a.execute("CREATE DATABASE rv")
    with c.connect("rv") as a:
        migrate.apply(a)
    admin = c.connect("rv")
    admin.execute("GRANT CONNECT, CREATE ON DATABASE rv TO pnl_owner")
    admin.execute("GRANT CONNECT ON DATABASE rv TO pnl_loader, pnl_verifier, pnl_promoter, pnl_api_reader")
    plr, cgr = syn.build_rich(tmp)
    rep = ps.validate(plr, cgr)
    assert rep["verdict"] == "PASSED", rep["hard_failures"]
    admin.execute("SET ROLE pnl_loader")
    res = pl.load_run(admin, pl.preflight(plr, cgr))
    assert pl.verify_loaded(admin, RUN)["ok"]
    admin.execute("RESET ROLE")
    db = Db(c.dsn("rv"))
    app = create_app(ApiSettings(conninfo=c.dsn("rv"), finance_token="t" * 32, cors_origins=()), db)
    yield {"admin": admin, "db": db, "client": TestClient(app), "load": res}
    admin.close()
    c.stop()
    shutil.rmtree(c.root, ignore_errors=True)


def get(env, path, **params):
    r = env["client"].get(f"/api/v1/pnl/runs/{RUN}{path}", params=params)
    assert r.status_code == 200, (path, r.text)
    return r.json()


def months(lo, hi):
    return [m for m in syn.MONTHS if lo <= m <= hi]


def rev_sum(sites, ms):
    return sum((syn.revenue(s, m) for s in sites for m in ms), D(0))


def eff_area(i, s, m):
    """Effective area of store s in month m, from the generator's own facts (area, opening, closing)."""
    area = D(0) if s == "124" else D(8000 + 100 * i)
    cal = D(syn.CAL[m])
    if s == "123" and m == date(2026, 3, 1):
        return area * 27 / cal
    if s == "123" and m < date(2026, 3, 1):
        return D(0)
    if s == "122" and m == date(2026, 6, 1):
        return area * 15 / cal                       # closed on 15 June (its last bill date): 15 active days of 30
    if s == "122" and m > date(2026, 6, 1):
        return D(0)
    return area


STORES = syn.STORES


def test_the_rich_run_loaded_with_every_control_and_check_green(env):
    r = env["load"]
    assert r["controls"]["pass"] == r["controls"]["total"] and all(v == 0 for v in r["mart_checks"].values())
    assert {"M13_effective_area_covers_every_site_month", "M14_effective_area_recomputed"} <= set(r["mart_checks"])


def test_mtd_qtd_ytd_compare_the_same_days_of_last_year(env):
    c = get(env, "/comparison", mode="stores")
    w = {x["id"]: x for x in c["windows"]}
    assert c["partial_month"] is True and c["aligned_days"] == 7 and all(x["day_aligned"] for x in c["windows"])
    ty_mtd = rev_sum(STORES, [OCT])
    ly_mtd = sum((syn.revenue(s, date(2025, 10, 1)) * D(7) / D(31)).quantize(D("0.01")) for s in STORES)          # days 1..7 of October 2025, not the whole month
    assert D(w["mtd"]["ty"]["revenue"]) == ty_mtd and D(w["mtd"]["ly"]["revenue"]) == ly_mtd
    assert abs(D(w["mtd"]["growth"]["revenue_pct"]) - (ty_mtd - ly_mtd) / ly_mtd * 100) < D("0.001")
    whole_oct = rev_sum(STORES, [date(2025, 10, 1)])
    assert D(w["mtd"]["ly"]["revenue"]) < whole_oct / 3                                                          # never compared with a whole month
    assert w["qtd"]["from_month"] == "2026-10" and D(w["qtd"]["ty"]["revenue"]) == ty_mtd and D(w["qtd"]["ly"]["revenue"]) == ly_mtd     # Q3 so far is just October
    ytd_ty = rev_sum(STORES, months(date(2026, 4, 1), OCT))
    ytd_ly = rev_sum(STORES, months(date(2025, 4, 1), date(2025, 9, 1))) + ly_mtd
    assert D(w["ytd"]["ty"]["revenue"]) == ytd_ty and D(w["ytd"]["ly"]["revenue"]) == ytd_ly                      # complete months plus the aligned window
    assert w["ytd"]["growth"]["gm_bps"] is not None and w["ytd"]["growth"]["contribution_bps"] is not None


def test_the_pivot_adds_up_across_months_quarters_and_rows(env):
    p = get(env, "/pivot", mode="stores")
    cols = {c["id"]: c for c in p["columns"]}
    assert [c["id"] for c in p["columns"]][:7] == ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"] and {"q1", "q2", "qtd", "ytd"} <= set(cols)
    assert cols["2026-10"]["partial"] is True and cols["qtd"]["partial"] is True and cols["q1"]["partial"] is False
    rows = {r["id"]: r for r in p["rows"]}
    rev = rows["revenue"]["cells"]
    assert sum((D(rev[c]) for c in ("2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10")), D(0)) == D(rev["ytd"])
    assert D(rev["q1"]) == sum((D(rev[m]) for m in ("2026-04", "2026-05", "2026-06")), D(0)) and D(rev["q2"]) == sum((D(rev[m]) for m in ("2026-07", "2026-08", "2026-09")), D(0))
    for c in cols:                                                                                                  # gross margin and contribution are exactly the sum of their rows, in every column
        cell = lambda rid: D(rows[rid]["cells"][c] or 0)  # noqa: E731
        assert cell("gross_margin") == cell("revenue") + cell("cogs") + cell("cogs_books")
        assert cell("store_opex") == sum((D(r["cells"][c] or 0) for r in p["rows"] if r["kind"] == "group"), D(0))
        assert cell("contribution") == cell("gross_margin") + cell("store_opex")
    assert p["ly_ytd_available"] and D(rows["revenue"]["ly_ytd"]) == sum((syn.revenue(s, m) for s in STORES for m in months(date(2025, 4, 1), date(2025, 9, 1))), D(0)) + sum((syn.revenue(s, date(2025, 10, 1)) * D(7) / D(31)).quantize(D("0.01")) for s in STORES)
    assert D(rows["revenue"]["variance"]) == D(rev["ytd"]) - D(rows["revenue"]["ly_ytd"])
    assert "Unmapped / Finance classification required" in p["unmapped_note"]


def test_the_pivot_ledgers_and_the_company_view_with_head_office(env):
    g = get(env, "/pivot", group="02-Employee Cost")
    led = {x["ledger_name"]: x for x in g["ledgers"]}
    assert "Salary" in led and D(led["Salary"]["cells"]["ytd"]) == -sum((syn.cost(s, m, "pay") for s in STORES for m in months(date(2026, 4, 1), OCT)), D(0))
    comp = get(env, "/pivot", mode="company")
    store = get(env, "/pivot", mode="stores")
    cs = {r["id"]: r for r in comp["rows"]}
    ss = {r["id"]: r for r in store["rows"]}
    assert comp["mode"] == "company" and store["mode"] == "stores"
    ho = sum((D(1_000_000) * (D(7) / D(31) if m == OCT else D(1)) for m in months(date(2026, 4, 1), OCT)), D(0))
    assert abs((D(cs["g:02-Employee Cost"]["cells"]["ytd"]) - D(ss["g:02-Employee Cost"]["cells"]["ytd"])) + ho) < D("0.001")     # head office is in the company view only


def test_expense_lines_carry_share_of_sales_basis_points_and_psf(env):
    e = get(env, "/expenses")
    assert e["months"] == ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"] and e["stores_with_area"] == e["stores"] - 1       # store 124 has no area
    rent = next(x for x in e["lines"] if x["group"] == "01-Rent")
    ms = months(date(2026, 4, 1), SEP)
    cost = sum((syn.cost(s, m, "rent") for s in STORES for m in ms), D(0))
    assert D(rent["cost"]) == cost
    rev = rev_sum(STORES, ms)
    assert abs(D(rent["pct_of_sales"]) - cost / rev * 100) < D("0.001")
    num = sum((syn.cost(s, m, "rent") for i, s in enumerate(STORES) if s != "124" for m in ms), D(0))
    den = sum((eff_area(i, s, m) for i, s in enumerate(STORES) if s != "124" for m in ms), D(0))
    assert abs(D(rent["psf"]) - num / den) < D("0.001")                                          # sum of rent / sum of effective area, over the stores that have an area
    ly = months(date(2025, 4, 1), date(2025, 9, 1))
    assert rent["ly_pct_of_sales"] is not None and rent["bps"] is not None and rent["ly_psf"] is not None and len(rent["trend"]) == 6
    assert abs(D(rent["bps"]) - (D(rent["pct_of_sales"]) - D(rent["ly_pct_of_sales"])) * 100) < D("0.01")
    assert ly[0] == date(2025, 4, 1)


def test_the_heat_map_lists_every_store_with_last_year_psf_and_sort_modes(env):
    h = get(env, "/heatmap", sort="worst_contribution_pct")
    rows = {r["site_code"]: r for r in h["stores"]}
    assert h["stores_total"] == len(rows) and "124" in rows and rows["124"]["sales_psf"] is None and rows["124"]["rent_psf"] is None       # no area: no PSF, never an average
    s101 = rows["101"]
    ms = months(date(2026, 4, 1), SEP)
    assert abs(D(s101["sales_psf"]) - rev_sum(["101"], ms) / sum((eff_area(0, "101", m) for m in ms), D(0))) < D("0.001")
    pcts = [D(r["contribution_pct"]) for r in h["stores"] if r["contribution_pct"] is not None]
    assert pcts == sorted(pcts)                                                                  # worst first
    opp = get(env, "/heatmap", sort="biggest_opportunity")["stores"]
    vals = [D(r["opportunity"]) for r in opp if r["opportunity"] is not None]
    assert vals == sorted(vals, reverse=True) and all(v >= 0 for v in vals)
    decl = [D(r["contribution_bps"]) for r in get(env, "/heatmap", sort="largest_decline_bps")["stores"] if r["contribution_bps"] is not None]
    assert decl == sorted(decl)
    assert h["scales"]["contribution_pct"]["p10"] is not None and "relative to the stores listed" in h["note"]
    assert env["client"].get(f"/api/v1/pnl/runs/{RUN}/heatmap", params={"sort": "nonsense"}).status_code == 422


def test_peers_are_the_same_region_and_vintage_with_median_and_quartiles(env):
    p = get(env, "/stores/101/peers")
    g = {x["dimension"]: x for x in p["groups"]}
    assert g["default"]["basis"] == "region + vintage" and g["default"]["peers"] >= 5
    h = {r["site_code"]: r for r in get(env, "/heatmap")["stores"]}
    peers = [h[s] for s in STORES if s != "101" and h[s]["region"] == "R1" and h[s]["vintage"] == "SAME STORE" and D(h[s]["revenue"]) >= D(10_000_000)]
    gm = next(m for m in g["default"]["metrics"] if m["metric"] == "gross_margin_pct")
    vals = [float(x["gross_margin_pct"]) for x in peers]
    assert g["default"]["peers"] == len(peers) and abs(float(gm["peer_median"]) - statistics.median(vals)) < 0.001
    assert gm["top_quartile"] is not None and gm["position"] in ("top quartile", "middle", "bottom quartile")
    op = next(m for m in g["default"]["metrics"] if m["metric"] == "opex_pct")
    assert float(op["top_quartile"]) <= float(op["peer_median"]) <= float(op["bottom_quartile"])        # for a cost, the top quartile is the LOW end
    assert g["network"]["basis"] == "whole network" and "state" in g and "size_band" in g
    assert env["client"].get(f"/api/v1/pnl/runs/{RUN}/stores/NOPE/peers").status_code == 404


def test_expense_exceptions_flag_the_planted_anomalies_and_nothing_ordinary(env):
    x = get(env, "/exceptions/expenses")
    assert x["month"] == "2026-09" and "sudden_increase" in x["rules"] and x["rules"]["severity"]
    by = {(e["site_code"], e["group"]): e for e in x["exceptions"]}
    power = by[("107", "03-Power and Fuel Expenses")]
    assert "SUDDEN_INCREASE" in power["flags"] and power["severity"] in ("High", "Critical") and "against a 3-month average" in power["why"]
    assert D(power["current"]) > D(power["expected"]) * D("1.3")
    rent = by[("109", "01-Rent")]
    assert "SUDDEN_DECREASE" in rent["flags"] and "missing posting" in rent["why"]                        # a fall is an exception too
    assert not any(e["site_code"] == "101" for e in x["exceptions"])                                    # an ordinary store raises nothing
    sev = [{"Critical": 0, "High": 1, "Medium": 2}[e["severity"]] for e in x["exceptions"]]
    assert sev == sorted(sev) and x["total"] == len(x["exceptions"])


def test_revenue_exceptions_flag_the_sales_collapse_and_the_growth_that_costs_margin(env):
    x = get(env, "/exceptions/revenue")
    by = {e["site_code"]: e for e in x["exceptions"]}
    assert "SALES_DROP" in by["111"]["flags"] and "against a 3-month average" in by["111"]["why"]
    assert "GROWTH_MARGIN_FALL" in by["113"]["flags"] and "bps" in by["113"]["why"]
    assert "101" not in by


def test_data_quality_names_the_gaps_in_the_inputs(env):
    q = get(env, "/quality")
    assert q["stores_without_area"]["count"] == 1 and q["stores_without_area"]["sites"][0]["site_code"] == "124"
    assert q["closed_stores_without_a_closing_date"]["count"] == 0
    reasons = {r["reason"] for r in q["effective_area_reasons"]}
    assert "FULL_MONTH" in reasons and any("OPENED_IN_MONTH" in r for r in reasons) and any("CLOSED_IN_MONTH" in r for r in reasons) and any("AFTER_CLOSE" in r for r in reasons)
    assert q["cogs_typical_pct"] is not None and len(q["cogs_pct_by_month"]) == 18
    assert "square feet" in q["area_units_note"]


def test_the_gate_passes_on_the_review_layer_and_catches_a_wrong_psf(env, monkeypatch):
    from app.pnl_api import reconcile as rec
    from app.pnl_api import review_engine as eng

    checks = rec.reconcile(env["client"], env["db"], RUN)
    bad = [c for c in checks if not c.ok]
    assert not bad, [(c.control, c.dimension, str(c.mart), str(c.api)) for c in bad[:6]]
    controls = {c.control for c in checks}
    assert {"PNL-R0", "PNL-R1", "PNL-R2", "PNL-R3", "PNL-R4", "PNL-R5", "PNL-R6"} <= controls
    real = eng.psf_over_sites
    monkeypatch.setattr(eng, "psf_over_sites", lambda *a, **k: ((real(*a, **k)[0] or D(0)) + D(1), real(*a, **k)[1]))       # an API whose PSF is one rupee out
    assert any(not c.ok and c.control == "PNL-R3" for c in rec.reconcile(env["client"], env["db"], RUN))
