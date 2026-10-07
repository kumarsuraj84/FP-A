"""P&L actuals API and the mart = API gate on a PRIVATE, THROWAWAY PostgreSQL with SYNTHETIC runs only."""
from __future__ import annotations

import json
import shutil
import sys
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
import pnl_loader as pl  # noqa: E402
import test_pl_stage as tps  # noqa: E402
from app.creditors_api.config import ApiSettings  # noqa: E402
from app.creditors_api.db import Db  # noqa: E402
from app.creditors_api.main import create_app  # noqa: E402
from app.pnl_api import reconcile as rec  # noqa: E402
from test_cred_mart_db import PG_BIN, Cluster  # noqa: E402

pytestmark = pytest.mark.skipif(not (PG_BIN / "initdb.exe").exists() and not shutil.which("initdb"), reason="PostgreSQL server binaries not found")
RUN = "run_20261007_900"


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    c = Cluster(tmp_path_factory.mktemp("pg_pnl_api"))
    c.start()
    with c.connect("postgres") as a:
        a.execute("CREATE DATABASE pnl_api_template")
    with c.connect("pnl_api_template") as a:
        migrate.apply(a)
    yield c
    c.stop()
    shutil.rmtree(c.root, ignore_errors=True)


_n = [0]


def make(cluster, tmp_path, verify=True):
    _n[0] += 1
    name = f"pa_{_n[0]:03d}"
    tmp_path.mkdir(parents=True, exist_ok=True)
    with cluster.connect("postgres") as a:
        a.execute(f"CREATE DATABASE {name} TEMPLATE pnl_api_template")
    admin = cluster.connect(name)
    admin.execute(f"GRANT CONNECT, CREATE ON DATABASE {name} TO pnl_owner")
    admin.execute(f"GRANT CONNECT ON DATABASE {name} TO pnl_loader, pnl_verifier, pnl_promoter, pnl_api_reader")
    plr, cgr = tps.build(tmp_path)
    assert ps.validate(plr, cgr)["verdict"] == "PASSED"
    admin.execute("SET ROLE pnl_loader")
    pl.load_run(admin, pl.preflight(plr, cgr))
    if verify:
        assert pl.verify_loaded(admin, RUN)["ok"]
    admin.execute("RESET ROLE")
    db = Db(cluster.dsn(name))
    app = create_app(ApiSettings(conninfo=cluster.dsn(name), finance_token="t" * 32, cors_origins=()), db)
    return {"admin": admin, "db": db, "client": TestClient(app), "name": name}


@pytest.fixture
def env(cluster, tmp_path):
    e = make(cluster, tmp_path)
    yield e
    e["admin"].close()
    with cluster.connect("postgres") as a:
        a.execute(f"DROP DATABASE {e['name']} WITH (FORCE)")


def get(env, path, **params):
    r = env["client"].get(f"/api/v1/pnl/runs/{RUN}{path}", params=params)
    assert r.status_code == 200, (path, r.text)
    return r.json()


def test_summary_defines_every_line_and_reconciles(env):
    s = get(env, "/summary")
    t = {k: Decimal(str(v)) for k, v in s["totals"].items() if v is not None}
    assert t["revenue"] == 1500 and t["cogs"] == 660 and t["opex"] == -300 and t["gross_margin"] == 840 and t["contribution"] == 540
    assert s["excluded_unmapped"]["ledgers"] == 1 and Decimal(str(s["excluded_unmapped"]["net"])) == -40                  # never in a total, always shown
    assert s["reconciliation"]["reconciles"] is True and s["budget"] is None and "not available" in s["budget_note"]
    assert s["data_state"] == "verified_candidate" and s["scope"]["basis"] == "all" and "unposted" in s["scope"]["basis_label"]
    assert "Before other income" in s["flags"]["contribution_definition"]
    assert [x["group_label"] for x in s["lines"] if x["section"] == "STORE_OPEX"] == ["02-Employee Cost"]


def test_the_posted_basis_leaves_the_unposted_month_out(env):
    s = get(env, "/summary", basis="posted")
    assert Decimal(str(s["totals"]["revenue"])) == 1000
    assert "2026-10" in get(env, "/summary")["flags"]["provisional_months"]


def test_the_store_league_lists_stores_sorted_and_reconciles_to_the_parent(env):
    r = get(env, "/stores")
    assert r["stores_total"] == 1 and r["reconciles"] is True               # a store is a site with sales in the books: site 20 has COGS-table sales only
    contrib = [Decimal(str(x["contribution"])) for x in r["stores"]]
    assert contrib == sorted(contrib, reverse=True) and r["stores"][0]["rank"] == 1 and r["stores"][0]["site_code"] == "10"
    assert r["stores"][0]["region"] == "R1" and r["stores"][0]["store_name"] == "STORE TEN"
    low = get(env, "/stores", sort="contribution", order="asc")["stores"]
    assert [x["site_code"] for x in low] == ["10"] and "sales_in_table_not_in_books" not in low[0]
    s = get(env, "/summary")
    assert s["reconciliation"]["reconciles"] is True and Decimal(str(s["reconciliation"]["non_store"]["cogs"])) == 60       # the COGS-only site is in the non-store side, so company = stores + non-store


def test_the_trend_runs_month_by_month_and_reconciles(env):
    t = get(env, "/trend")
    assert [m["month"] for m in t["months"]][-2:] == ["2026-09", "2026-10"] and t["reconciles"] is True
    assert t["months"][-1]["partial"] is True and t["months"][-1]["provisional"] is True
    assert all(m["last_year"] is None or m["last_year"]["month"] < m["month"] for m in t["months"])


def test_filters_narrow_the_view_and_the_hierarchy_comes_from_the_site_master(env):
    h = get(env, "/hierarchy")["options"]
    assert {o["value"] for o in h["region"]} == {"R1"}
    r = get(env, "/stores", region="R1")
    assert r["stores_total"] == 1 and r["stores"][0]["site_code"] == "10" and r["reconciles"] is True
    s = get(env, "/summary", region="R1")
    assert Decimal(str(s["totals"]["revenue"])) == 1500 and "reconciliation" not in s


def test_a_store_and_the_ledgers_behind_a_group_add_up(env):
    d = get(env, "/stores/10")
    assert d["reconciles"] is True and d["site"]["is_store"] is True and Decimal(str(d["totals"]["contribution"])) == 1500 - 600 - 300
    g = get(env, "/stores/10/groups/02-Employee Cost/ledgers")
    assert g["reconciles"] is True and g["ledgers"][0]["ledger_name"] == "Salary" and Decimal(str(g["ledgers"][0]["amount"])) == -300


def test_reconciliation_view_lists_the_gaps(env):
    r = get(env, "/reconciliation")
    assert r["sales_tieout"]["site_months"] == 3 and r["sales_tieout"]["tied"] == 2 and r["sales_tieout"]["largest_gaps"][0]["site_code"] == "20"
    assert r["excluded_unmapped"]["ledgers"][0]["ledger_name"] == "Mystery Fee" and r["sites_without_books_sales"]["count"] == 1


def test_bad_requests_and_unserved_runs(env, cluster, tmp_path):
    c = env["client"]
    assert c.get(f"/api/v1/pnl/runs/{RUN}/summary", params={"basis": "nonsense"}).status_code == 422
    assert c.get(f"/api/v1/pnl/runs/{RUN}/stores", params={"sort": "nonsense"}).status_code == 422
    assert c.get(f"/api/v1/pnl/runs/{RUN}/summary", params={"from_month": "2026-10", "to_month": "2026-09"}).status_code == 422
    assert c.get("/api/v1/pnl/runs/run_19990101_001/summary").status_code == 404
    assert c.get(f"/api/v1/pnl/runs/{RUN}/stores/NOPE").status_code == 404
    e2 = make(cluster, tmp_path / "b", verify=False)
    try:
        assert e2["client"].get(f"/api/v1/pnl/runs/{RUN}/summary").status_code == 404                   # a merely loaded run is not served
        assert e2["client"].get("/api/v1/pnl/current").status_code == 404
    finally:
        e2["admin"].close()
        with cluster.connect("postgres") as a:
            a.execute(f"DROP DATABASE {e2['name']} WITH (FORCE)")


def test_the_gate_passes_records_and_marks_the_run_api_verified_but_unpublished(env):
    checks = rec.reconcile(env["client"], env["db"], RUN)
    bad = [c for c in checks if not c.ok]
    assert not bad, [(c.control, c.dimension, str(c.mart), str(c.api)) for c in bad[:5]]
    assert {c.control for c in checks} >= {"PNL-C1", "PNL-C2", "PNL-C3", "PNL-C4", "PNL-C5", "PNL-C6", "PNL-C7", "PNL-STATE"}
    answer = rec.record(env["db"], RUN, checks)
    assert answer["ok"] is True and answer["recon_state"] == "api_verified"
    st = env["admin"].execute("SELECT recon_state, publication_state FROM pnl.run WHERE run_id = %s", (RUN,)).fetchone()
    assert st == ("api_verified", "unpublished")


def test_the_gate_catches_a_difference(env, monkeypatch):
    from app.pnl_api import repository as repo

    real = repo.period_totals

    def off(data, site_filter, lo, hi):
        t = real(data, site_filter, lo, hi)
        t["revenue"] = t["revenue"] + 1                              # an API that is one rupee out
        return t

    monkeypatch.setattr(repo, "period_totals", off)
    checks = rec.reconcile(env["client"], env["db"], RUN)
    assert any(not c.ok for c in checks)


def test_no_narration_is_in_any_response(env):
    blob = json.dumps(get(env, "/stores")) + json.dumps(get(env, "/summary"))
    assert "narration" not in blob.lower()


def test_last_year_is_compared_over_complete_months_only_and_provisional_means_unposted_revenue(env):
    s = get(env, "/summary")
    assert s["comparison"]["period"]["to_month"] == "2026-09" and "complete months" in s["comparison"]["note"]
    assert s["flags"]["provisional_months"] == ["2026-10"]                      # only October has unposted REVENUE; a stray unposted journal elsewhere does not make a month provisional
    t = get(env, "/trend")
    assert t["months"][-1]["growth_revenue_pct"] is None and t["months"][-1]["partial"] is True
    assert get(env, "/stores")["growth_basis"]["to_month"] == "2026-09"
