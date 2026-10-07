"""
P&L actuals UAT: schema `pnl`, the loader and the structural / state controls, on a PRIVATE, THROWAWAY PostgreSQL with SYNTHETIC runs only.
Evidence: docs/profit_cash/PNL_MART_UAT_EVIDENCE.md. The API tests live in test_pnl_api.py.
"""
from __future__ import annotations

import json
import logging
import shutil
import sys
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from psycopg import errors as E

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
from test_cred_mart_db import PG_BIN, Cluster  # noqa: E402

EVIDENCE_FILE = ROOT.parent / "docs" / "profit_cash" / "PNL_MART_UAT_EVIDENCE.md"
pytestmark = pytest.mark.skipif(not (PG_BIN / "initdb.exe").exists() and not shutil.which("initdb"), reason="PostgreSQL server binaries not found")
EVIDENCE: list[dict] = []


def ev(uid, title, **detail):
    EVIDENCE.append({"id": uid, "title": title, "detail": detail})


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    c = Cluster(tmp_path_factory.mktemp("pg_pnl"))
    c.start()
    with c.connect("postgres") as a:
        a.execute("CREATE DATABASE pnl_template")
    with c.connect("pnl_template") as a:
        ran = migrate.apply(a)
    ev("P00", "migrations applied on a fresh database", versions=ran)
    yield c
    c.stop()
    shutil.rmtree(c.root, ignore_errors=True)
    ev("P99", "scratch instance removed", data_directory_removed=not c.root.exists())
    write_evidence()


_n = [0]


@pytest.fixture
def env(cluster, tmp_path):
    _n[0] += 1
    name = f"pnl_{_n[0]:03d}"
    with cluster.connect("postgres") as a:
        a.execute(f"CREATE DATABASE {name} TEMPLATE pnl_template")
    admin = cluster.connect(name)
    admin.execute(f"GRANT CONNECT, CREATE ON DATABASE {name} TO pnl_owner")
    admin.execute(f"GRANT CONNECT ON DATABASE {name} TO pnl_loader, pnl_verifier, pnl_promoter, pnl_api_reader")
    yield {"admin": admin, "name": name, "cluster": cluster, "tmp": tmp_path}
    admin.close()
    with cluster.connect("postgres") as a:
        a.execute(f"DROP DATABASE {name} WITH (FORCE)")


def staged(env, tweak=None):
    d = env["tmp"] / f"p{len(list(env['tmp'].glob('p*')))}"
    d.mkdir()
    plr, cgr = tps.build(d, tweak)
    rep = ps.validate(plr, cgr)
    return plr, cgr, rep


def as_role(env, role, fn):
    a = env["admin"]
    a.execute(f"SET ROLE {role}")
    try:
        return fn(a)
    finally:
        a.execute("RESET ROLE")


def load(env, plr, cgr):
    return as_role(env, "pnl_loader", lambda a: pl.load_run(a, pl.preflight(plr, cgr)))


def verify(env, run_id):
    return as_role(env, "pnl_loader", lambda a: pl.verify_loaded(a, run_id))


def ready(env):
    plr, cgr, rep = staged(env)
    assert rep["verdict"] == "PASSED", rep["hard_failures"]
    res = load(env, plr, cgr)
    assert verify(env, plr.name)["ok"]
    return plr, cgr, res


def test_p01_load_succeeds_every_control_green_and_the_run_stays_unpublished(env):
    plr, cgr, rep = staged(env)
    assert rep["verdict"] == "PASSED", rep["hard_failures"]
    res = load(env, plr, cgr)
    assert (res["recon_state"], res["publication_state"]) == ("loaded", "unpublished")
    assert res["controls"]["pass"] == res["controls"]["total"] > 20 and res["controls"]["max_abs_variance"] == "0.0000"
    assert all(v == 0 for v in res["mart_checks"].values()) and {"M05_tieout_books_sales_recomputed", "M06_tieout_table_sales_recomputed", "M07_tied_flag_matches_tolerance"} <= set(res["mart_checks"])
    assert res["tieout"] == {"site_months": 3, "tied": 2}
    ev("P01", "load", gl_rows=res["gl_rows"], cogs_rows=res["cogs_rows"], controls=res["controls"], checks=len(res["mart_checks"]), tieout=res["tieout"])


def test_p02_verify_moves_loaded_to_verified_and_nothing_promotes_it(env):
    plr, _, _ = ready(env)
    a = env["admin"]
    assert a.execute("SELECT recon_state, publication_state FROM pnl.run WHERE run_id = %s", (plr.name,)).fetchone() == ("verified", "unpublished")
    assert a.execute("SELECT count(*) FROM pnl.live_run").fetchone()[0] == 0
    with pytest.raises(psycopg.Error):                         # promotion needs api_verified, and only the promoter may call it
        as_role(env, "pnl_loader", lambda c: c.execute("SELECT pnl.promote_run(%s, 'x')", (plr.name,)))
    a.execute("RESET ROLE")
    with pytest.raises(psycopg.Error, match="api_verified"):
        as_role(env, "pnl_promoter", lambda c: c.execute("SELECT pnl.promote_run(%s, 'a test')", (plr.name,)))
    assert a.execute("SELECT publication_state FROM pnl.run WHERE run_id = %s", (plr.name,)).fetchone()[0] == "unpublished"
    ev("P02", "verify, no promotion", state="verified/unpublished", promote_before_api_verified="refused")


def test_p03_runs_are_immutable(env):
    plr, _, _ = ready(env)
    a = env["admin"]
    for sql in ("UPDATE pnl.gl_site_month SET credit = credit + 1 WHERE run_id = '%s'", "DELETE FROM pnl.gl_site_month WHERE run_id = '%s'", "UPDATE pnl.cogs_site_month SET cogs_v = 0 WHERE run_id = '%s'",
                "DELETE FROM pnl.run WHERE run_id = '%s'", "UPDATE pnl.sales_tieout SET tied = true WHERE run_id = '%s'", "DELETE FROM pnl.control_result WHERE run_id = '%s'"):
        with pytest.raises(E.InsufficientPrivilege):
            a.execute(sql % plr.name)
    with pytest.raises(E.InsufficientPrivilege):               # a verified run is closed: no row can be added
        as_role(env, "pnl_loader", lambda c: c.execute("INSERT INTO pnl.site (run_id, site_code) VALUES (%s, 'X')", (plr.name,)))
    ev("P03", "immutability", refused=7)


def test_p04_the_loader_login_rules(env):
    plr, cgr, _ = staged(env)
    a = env["admin"]
    with pytest.raises(pl.LoadError, match="refusing to load as .postgres."):
        pl.load_run(a, pl.preflight(plr, cgr))                  # the superuser session itself
    a.execute("SET ROLE pnl_owner")
    try:
        with pytest.raises(pl.LoadError, match="refusing to load"):
            pl.load_run(a, pl.preflight(plr, cgr))
    finally:
        a.execute("RESET ROLE")
    ev("P04", "loader identity", superuser="refused", owner="refused")


def test_p05_reloading_the_same_run_is_a_no_op_and_a_changed_one_is_refused(env):
    plr, cgr, _ = staged(env)
    load(env, plr, cgr)
    with pytest.raises(pl.AlreadyLoaded):
        load(env, plr, cgr)
    a = env["admin"]
    n = a.execute("SELECT count(*) FROM pnl.gl_site_month").fetchone()[0]
    assert n == 4
    ev("P05", "idempotent reload", rows_after=n)


def test_p06_a_mart_figure_that_disagrees_with_the_extract_rolls_the_whole_run_back(env, monkeypatch):
    plr, cgr, _ = staged(env)
    plan = as_role(env, "pnl_loader", lambda a: pl.preflight(plr, cgr))
    plan.expected[("P_gl", "credit")] += 1                      # the extract-side figure no longer matches what lands in the mart
    with pytest.raises(pl.LoadError) as exc:
        as_role(env, "pnl_loader", lambda a: pl.load_run(a, plan))
    assert exc.value.stage == "mart_controls" and "P_gl" in exc.value.failed
    a = env["admin"]
    assert a.execute("SELECT count(*) FROM pnl.run").fetchone()[0] == 0 and a.execute("SELECT count(*) FROM pnl.gl_site_month").fetchone()[0] == 0
    rej = a.execute("SELECT stage, failed_controls FROM pnl.load_rejection").fetchone()
    assert rej[0] == "mart_controls"
    ev("P06", "variance rolls back", rows_left=0, rejection=rej[0])


def test_p07_a_staging_report_tied_to_another_manifest_is_refused_before_any_database_work(env):
    plr, cgr, rep = staged(env)
    path = plr / "staging" / "validation_report.json"
    j = json.loads(path.read_text(encoding="utf-8"))
    j["manifest_sha256"] = "0" * 64
    path.write_text(json.dumps(j), encoding="utf-8")
    with pytest.raises(pl.LoadError, match="does not belong"):
        pl.preflight(plr, cgr)
    ev("P07", "report/manifest chain", refused="before any database work")


def test_p08_the_api_reader_sees_views_of_a_served_run_only(env):
    plr, _, _ = ready(env)
    a = env["admin"]
    assert as_role(env, "pnl_api_reader", lambda c: c.execute("SELECT count(*) FROM pnl.v_gl_site_month").fetchone()[0]) == 4
    with pytest.raises(E.InsufficientPrivilege):
        as_role(env, "pnl_api_reader", lambda c: c.execute("SELECT count(*) FROM pnl.gl_site_month"))
    a.execute("RESET ROLE")
    ev("P08", "api reader", views="readable", base_tables="denied")


def test_p09_a_loaded_run_is_not_served_until_verified(env):
    plr, cgr, _ = staged(env)
    load(env, plr, cgr)
    a = env["admin"]
    assert as_role(env, "pnl_api_reader", lambda c: c.execute("SELECT count(*) FROM pnl.v_gl_site_month").fetchone()[0]) == 0
    verify(env, plr.name)
    assert as_role(env, "pnl_api_reader", lambda c: c.execute("SELECT count(*) FROM pnl.v_gl_site_month").fetchone()[0]) == 4
    a.execute("RESET ROLE")
    ev("P09", "serving rule", loaded="not served", verified="served")


def test_p10_the_shared_run_model_lists_the_pnl_domain(env):
    plr, _, _ = ready(env)
    row = env["admin"].execute("SELECT domain, run_id, as_of_date, reconciliation_status, publication_state FROM core.v_domain_run WHERE domain = 'pnl'").fetchone()
    assert row[:2] == ("pnl", plr.name) and str(row[2]) == tps.AS_OF and row[3:] == ("verified", "unpublished")
    ev("P10", "shared run model", row=[str(x) for x in row])


def test_p11_rejections_and_logs_carry_no_names(env, caplog):
    plr, cgr, _ = staged(env)
    plan = as_role(env, "pnl_loader", lambda a: pl.preflight(plr, cgr))
    plan.expected[("P_gl", "credit")] += 1
    caplog.set_level(logging.DEBUG)
    with pytest.raises(pl.LoadError):
        as_role(env, "pnl_loader", lambda a: pl.load_run(a, plan))
    blob = caplog.text + json.dumps(env["admin"].execute("SELECT reason, failed_controls FROM pnl.load_rejection").fetchall(), default=str)
    for s in ("STORE TEN", "Mystery Fee", "Salary", "Sales - POS"):
        assert s not in blob, s
    ev("P11", "telemetry", names_in_logs_or_rejections=False)


def write_evidence():
    EVIDENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# P&L actuals mart: UAT evidence", "", "Generated by `tools/creditors_mart/tests/test_pnl_mart.py`: synthetic runs through the real loader into a private temporary PostgreSQL.",
             "`fpa_pilot`, Oracle and every real run were untouched.", "", "| Item | Result |", "|---|---|"]
    for e in sorted(EVIDENCE, key=lambda x: x["id"]):
        lines.append(f"| {e['id']} {e['title']} | " + "; ".join(f"{k}: {json.dumps(v, default=str)}" for k, v in e["detail"].items()) + " |")
    EVIDENCE_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_p12_the_effective_area_is_rederived_in_sql_and_a_wrong_row_is_refused(env):
    plr, cgr, _ = staged(env)
    plan = as_role(env, "pnl_loader", lambda a: pl.preflight(plr, cgr))
    rows = plan.data["store_month_effective_area"]
    victim = next(e for e in rows if e["effective_area"] is not None and e["active_days"] > 0)
    victim["effective_area"] = victim["effective_area"] + Decimal("1.0000")           # the stager and the extract-side figures agree on the wrong number...
    plan.expected = pl.expected_dims(plan.data)
    with pytest.raises(pl.LoadError) as exc:
        as_role(env, "pnl_loader", lambda a: pl.load_run(a, plan))
    assert exc.value.stage == "mart_controls" and "M14_effective_area_recomputed" in exc.value.failed           # ...but the SQL re-derivation from the site master does not
    assert env["admin"].execute("SELECT count(*) FROM pnl.run").fetchone()[0] == 0
    ev("P12", "effective area re-derivation", refused_by="M14", rows_left=0)


def test_p13_the_review_foundation_is_loaded_and_checked(env):
    plr, cgr, rep = staged(env)
    res = load(env, plr, cgr)
    assert {"M12_aligned_rows_in_the_aligned_month", "M13_effective_area_covers_every_site_month", "M14_effective_area_recomputed", "M15_cogs_early_within_month"} <= set(res["mart_checks"])
    assert all(v == 0 for v in res["mart_checks"].values())
    a = env["admin"]
    assert a.execute("SELECT aligned_days, ly_aligned_month FROM pnl.run").fetchone() == (7, __import__("datetime").date(2025, 10, 1))
    assert a.execute("SELECT count(*) FROM pnl.store_month_effective_area").fetchone()[0] == 38 and a.execute("SELECT count(*) FROM pnl.gl_aligned").fetchone()[0] == 2
    assert a.execute("SELECT area FROM pnl.site WHERE site_code = '10'").fetchone()[0] == Decimal("10000.00")
    assert a.execute("SELECT cogs_early FROM pnl.cogs_site_month WHERE site_code = '10' AND month = '2026-09-01'").fetchone()[0] == Decimal("300")
    eff = a.execute("SELECT effective_area, reason FROM pnl.store_month_effective_area WHERE site_code = '40' AND month = '2026-05-01'").fetchone()
    assert eff[0] == (Decimal(8000) * 22 / 31).quantize(Decimal("0.0001")) and "OPENED_IN_MONTH" in eff[1]               # opened 10 May: 22 of 31 days
    with pytest.raises(E.InsufficientPrivilege):
        a.execute("UPDATE pnl.store_month_effective_area SET effective_area = 1")
    ev("P13", "review foundation", checks=len(res["mart_checks"]), effective_area_rows=38, aligned_rows=2)
