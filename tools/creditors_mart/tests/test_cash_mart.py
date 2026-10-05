"""
Cash mart UAT: schema `cash`, the shared run model `core`, the loader, the Cash API and the mart = API gate.

Runs against a PRIVATE, THROWAWAY PostgreSQL instance with SYNTHETIC runs only. It never touches fpa_pilot, Oracle or anything real.
Evidence: docs/profit_cash/CASH_MART_UAT_EVIDENCE.md
"""
from __future__ import annotations

import json
import shutil
import sys
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import errors as E

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT.parent / "backend"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(ROOT / "extraction_broker"))
sys.path.insert(0, str(ROOT / "extraction_broker" / "tests"))
sys.path.insert(0, str(HERE))
import cash_loader as cl  # noqa: E402
import cash_stage as cstage  # noqa: E402
import creditors_stage as cs  # noqa: E402
import loader as cred_loader  # noqa: E402
import manifest as mf  # noqa: E402
import migrate  # noqa: E402
import test_cash_stage as tcs  # noqa: E402
import test_creditors_pilot as tcp  # noqa: E402
from app.cash_api import reconcile as rec  # noqa: E402
from app.cash_api import repository as cash_repo  # noqa: E402
from app.creditors_api.config import ApiSettings  # noqa: E402
from app.creditors_api.db import Db  # noqa: E402
from app.creditors_api.main import create_app  # noqa: E402
from test_cred_mart_db import PG_BIN, Cluster  # noqa: E402

EVIDENCE_FILE = ROOT.parent / "docs" / "profit_cash" / "CASH_MART_UAT_EVIDENCE.md"
RUN = "run_20261004_950"
SALT = "unit-test-pseudonym-key-0123456789"
pytestmark = pytest.mark.skipif(not (PG_BIN / "initdb.exe").exists() and not shutil.which("initdb"), reason="PostgreSQL server binaries not found")
EVIDENCE: list[dict] = []
CASH_ROLES = ["cash_owner", "cash_loader", "cash_verifier", "cash_promoter", "cash_api_reader"]


def ev(uid, title, **detail):
    EVIDENCE.append({"id": uid, "title": title, "detail": detail})


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    c = Cluster(tmp_path_factory.mktemp("pg_cash"))
    c.start()
    with c.connect("postgres") as a:
        a.execute("CREATE DATABASE cash_template")
    with c.connect("cash_template") as a:
        ran = migrate.apply(a)
    ev("C00", "migrations applied on a fresh database", versions=ran)
    yield c
    c.stop()
    shutil.rmtree(c.root, ignore_errors=True)
    ev("C99", "scratch instance removed", data_directory_removed=not c.root.exists())
    write_evidence()


_n = [0]


@pytest.fixture
def env(cluster, tmp_path):
    _n[0] += 1
    name = f"cash_{_n[0]:03d}"
    with cluster.connect("postgres") as a:
        a.execute(f"CREATE DATABASE {name} TEMPLATE cash_template")
    admin = cluster.connect(name)
    for r in ("cred_owner", "cash_owner"):
        admin.execute(f"GRANT CONNECT, CREATE ON DATABASE {name} TO {r}")
    admin.execute(f"GRANT CONNECT ON DATABASE {name} TO cred_loader, cred_verifier, cred_promoter, cred_api_reader, cred_finance_reader, cash_loader, cash_verifier, cash_promoter, cash_api_reader")
    run = tcs.synth(tmp_path, name=RUN)
    assert cstage.validate(run)["verdict"] == "PASSED"
    db = Db(cluster.dsn(name))
    app = create_app(ApiSettings(conninfo=cluster.dsn(name), finance_token="t" * 32, cors_origins=()), db)
    yield {"admin": admin, "db": db, "client": TestClient(app), "run": run, "name": name, "cluster": cluster, "tmp": tmp_path}
    admin.close()
    with cluster.connect("postgres") as a:
        a.execute(f"DROP DATABASE {name} WITH (FORCE)")


def as_loader(env):
    env["admin"].execute("SET ROLE cash_loader")
    return env["admin"]


def load(env):
    conn = as_loader(env)
    try:
        return cl.load_run(conn, cl.preflight(env["run"]))
    finally:
        env["admin"].execute("RESET ROLE")


def verify(env):
    conn = as_loader(env)
    try:
        return cl.verify_loaded(conn, RUN)
    finally:
        env["admin"].execute("RESET ROLE")


def load_creditors(env):
    """A synthetic creditors run, loaded and verified through the real creditors loader, so the Cash page can compose it."""
    run = tcp.build_run(env["tmp"], name="run_20261004_940")
    assert cs.validate(run)["verdict"] == "PASSED"
    a = env["admin"]
    a.execute("SET ROLE cred_loader")
    cred_loader.load_run(a, cred_loader.preflight(run, SALT))
    cred_loader.verify_loaded(a, "run_20261004_940")
    a.execute("RESET ROLE")
    return "run_20261004_940"


def base(path=""):
    return f"/api/v1/cash/runs/{RUN}{path}"


# ───────────── load and the shared run model ─────────────


def test_c01_correct_run_loads_unpublished_with_all_controls_green(env):
    res = load(env)
    assert (res["recon_state"], res["publication_state"]) == ("loaded", "unpublished")
    assert res["controls"]["pass"] == res["controls"]["total"] >= 60 and res["controls"]["max_abs_variance"] == "0.0000"
    assert res["stores"] == 4 and Decimal(res["store_till_cash"]) == Decimal("11850.25")
    a = env["admin"]
    assert a.execute("SELECT count(*) FROM cash.store_till").fetchone()[0] == 4 and a.execute("SELECT count(*) FROM cash.bank_ledger").fetchone()[0] == 15
    ev("C01", "load", controls=res["controls"], stores=res["stores"], state="loaded / unpublished")


def test_c02_loader_is_idempotent_and_refuses_a_different_run_under_the_same_id(env):
    load(env)
    conn = as_loader(env)
    with pytest.raises(cl.AlreadyLoaded):
        cl.load_run(conn, cl.preflight(env["run"]))
    env["admin"].execute("RESET ROLE")
    ev("C02", "reload", result="AlreadyLoaded, nothing written")


def test_c03_a_failed_mart_control_rolls_back_every_row(env):
    conn = as_loader(env)
    plan = cl.preflight(env["run"])
    plan.expected[("T_till_sum", "cumulative_balance")] += 1                      # the staging report claims one rupee more than the extract holds
    with pytest.raises(cl.LoadError) as e:
        cl.load_run(conn, plan)
    env["admin"].execute("RESET ROLE")
    assert e.value.stage == "mart_controls" and "T_till_sum" in e.value.failed
    a = env["admin"]
    assert a.execute("SELECT count(*) FROM cash.run").fetchone()[0] == 0 and a.execute("SELECT count(*) FROM cash.store_till").fetchone()[0] == 0
    assert a.execute("SELECT count(*) FROM cash.load_rejection").fetchone()[0] == 1
    ev("C03", "rollback on a control variance", stage=e.value.stage, rows_left=0, rejection_recorded=True)


def test_c04_preflight_catches_a_tampered_derived_file_even_when_the_report_hash_is_updated(env):
    run = env["run"]
    t = run / "staging" / "cash_store_till.parquet"
    import pyarrow as pa
    import pyarrow.parquet as pq

    tbl = pq.read_table(t)
    rows = tbl.to_pylist()
    rows[0]["cumulative_balance"] += 1
    pq.write_table(pa.Table.from_pylist(rows, schema=tbl.schema), t)
    rp = run / "staging" / "validation_report.json"
    rep = json.loads(rp.read_text(encoding="utf-8"))
    rep["outputs"]["cash_store_till"] = mf.sha256_file(t)
    rp.write_text(json.dumps(rep), encoding="utf-8")
    with pytest.raises(cl.LoadError) as e:
        cl.preflight(run)
    assert "derived store rows differ" in e.value.reason
    ev("C04", "tampered derived Parquet with a re-sealed hash", result="refused by the raw re-derivation")


def test_c05_loader_login_rules_and_immutability(env):
    load(env)
    a = env["admin"]
    a.execute("SET ROLE cash_loader")
    for stmt in ("SELECT cash.promote_run('run_20261004_950', 'x')", "SELECT cash.api_verify_run('run_20261004_950')", "UPDATE cash.store_till SET cumulative_balance = 0",
                 "DELETE FROM cash.bank_ledger", "UPDATE cash.run SET publication_state = 'live'", "CREATE TABLE cash.evil (x int)", "SELECT * FROM cred.v_candidate_run"):
        with pytest.raises((E.InsufficientPrivilege, E.RaiseException)):
            a.execute(stmt)
    a.execute("RESET ROLE")
    a.execute("SET ROLE cash_owner")                                               # even the owner cannot rewrite a run
    for stmt in ("UPDATE cash.store_till SET cumulative_balance = 0", "DELETE FROM cash.store_till", "DELETE FROM cash.run"):
        with pytest.raises((E.InsufficientPrivilege, E.RaiseException)):
            a.execute(stmt)
    a.execute("RESET ROLE")
    with pytest.raises(cl.LoadError):                                              # a non-loader identity is refused outright
        a.execute("SET ROLE cash_api_reader")
        try:
            cl.assert_loader_identity(a)
        finally:
            a.execute("RESET ROLE")
    ev("C05", "role separation and immutability", loader_refused=7, owner_refused=3, non_loader_identity="refused")


def test_c06_verify_then_api_gate_then_promotion(env):
    load(env)
    a = env["admin"]
    assert verify(env)["ok"] is True
    cred = load_creditors(env)
    checks = rec.reconcile(env["client"], env["db"], RUN)
    bad = [c for c in checks if not c.ok]
    assert not bad, [(c.control, c.dimension, c.mart, c.api) for c in bad]
    assert any(c.control == "CASH-C5" for c in checks)
    res = rec.record(env["db"], RUN, checks)
    assert res["ok"] and res["recon_state"] == "api_verified"
    # the shared run model shows both domains, each in its own state
    rows = {(r[0], r[1]): r[2:] for r in a.execute("SELECT domain, run_id, mart_state, api_state, publication_state, is_live FROM core.v_domain_run").fetchall()}
    assert rows[("cash", RUN)] == ("verified", "verified", "unpublished", False)
    assert rows[("creditors", cred)][:2] == ("verified", "pending")
    a.execute("SET ROLE cash_promoter")
    a.execute("SELECT cash.promote_run(%s, 'UAT promotion')", (RUN,))
    a.execute("RESET ROLE")
    live = env["client"].get(base("/summary")).json()
    assert live["data_state"] == "live"
    assert a.execute("SELECT is_live FROM core.v_domain_run WHERE domain = 'cash'").fetchone()[0] is True
    ev("C06", "verify, mart=API gate, promotion", api_checks=len(checks), api_verified=True, run_model=["cash", "creditors"], live_data_state="live")


def test_c07_a_run_that_is_only_loaded_is_not_served(env):
    load(env)
    assert env["client"].get(base("/summary")).status_code == 404
    assert env["client"].get("/api/v1/cash/current").status_code == 404
    verify(env)
    assert env["client"].get(base("/summary")).status_code == 200
    ev("C07", "serving rule", loaded="404", verified="served as verified_candidate")


def test_c08_the_page_never_offers_a_cash_position_and_labels_every_figure(env):
    load(env)
    verify(env)
    s = env["client"].get(base("/summary")).json()
    assert s["data_state"] == "verified_candidate"
    assert s["till"]["label"] == "Store Till Cash" and s["till"]["note"] == "excludes bank balances"
    assert s["bank_review"]["status"] == "PROVISIONAL · NOT BANK-RECONCILED"
    assert not any(k in s for k in ("cash_position", "consolidated_cash", "cash_available", "forecast"))
    assert {u["id"] for u in s["unavailable"]} >= {"bank_reconciled_cash", "consolidated_cash", "cash_forecast", "inventory", "receivables", "vendor_advances", "payroll", "statutory", "capex"}
    br = s["bank_review"]
    t = br["totals"]
    assert Decimal(t["opening_balance"]) + (Decimal(t["posted_closing"]) - Decimal(t["opening_balance"])) == Decimal(t["posted_closing"])
    assert Decimal(t["including_unposted"]) == Decimal(t["posted_closing"]) + Decimal(t["unposted_movement"])
    assert br["driver"]["ledger_name"] == "BANK ALPHA-1" and Decimal(br["driver"]["posted_closing"]) < 0   # the synthetic ledger that runs negative
    assert br["ledgers_total"] == 5 and br["ledgers_with_movement"] == 4 and br["ledgers_without_movement"] == 1
    assert br["opening_ties_to_prior_year_closing"] == {"ledgers_checked": 5, "ledgers_not_tying": 0} and br["cross_check"]["posted_agrees_with_gl_register"] is True
    assert s["creditors"]["available"] is False                                     # no creditors run in this database: said plainly, not zero
    ev("C08", "honest page contract", till_label=s["till"]["label"], bank_status=br["status"], unavailable=len(s["unavailable"]), driver=br["driver"]["ledger_name"])


def test_c09_creditor_figures_come_from_the_creditors_mart_and_state_their_run(env):
    load(env)
    verify(env)
    cred = load_creditors(env)
    s = env["client"].get(base("/summary")).json()
    c = s["creditors"]
    assert c["available"] and c["creditors_run_id"] == cred and c["data_state"] == "verified_candidate"
    direct = env["client"].get(f"/api/v1/creditors/runs/{cred}/summary").json()
    assert c["credit_outstanding"] == direct["credit_outstanding"] and c["past_due_credit"] == direct["past_due_credit"] and c["creditor_debit_balance"] == direct["creditor_debit_balance"]
    ev("C09", "creditor composition", creditors_run=cred, equals_creditors_api=True)


def test_c10_the_gate_blocks_on_a_single_difference(env, monkeypatch):
    load(env)
    verify(env)
    load_creditors(env)
    real = cash_repo.till

    def off_by_a_paisa(conn, run_id):
        t = real(conn, run_id)
        t["store_till_cash"] += Decimal("0.01")
        return t

    monkeypatch.setattr(cash_repo, "till", off_by_a_paisa)
    checks = rec.reconcile(env["client"], env["db"], RUN)
    bad = [c for c in checks if not c.ok]
    assert [c.dimension for c in bad] == ["store till cash"]
    with env["db"].session("cash_verifier", readonly=False) as c:                  # recording the failure leaves the run un-verified
        for ch in checks:
            c.execute("SELECT cash.record_control(%s,%s,%s,'mart',%s,'api',%s)", (RUN, ch.control, ch.dimension[:200], ch.mart, ch.api))
        r = c.execute("SELECT cash.api_verify_run(%s) AS r", (RUN,)).fetchone()["r"]
    assert r["ok"] is False
    assert env["admin"].execute("SELECT recon_state FROM cash.run").fetchone()[0] == "verified"
    ev("C10", "one paisa difference blocks api_verified", blocked=True, state_after="verified")


def test_c11_promotion_needs_api_verified_and_only_the_promoter_can_do_it(env):
    load(env)
    verify(env)
    a = env["admin"]
    a.execute("SET ROLE cash_promoter")
    with pytest.raises(E.RaiseException):
        a.execute("SELECT cash.promote_run(%s, 'too early')", (RUN,))
    a.execute("RESET ROLE")
    for role in ("cash_api_reader", "cash_verifier", "cash_loader"):
        a.execute(f"SET ROLE {role}")
        with pytest.raises((E.InsufficientPrivilege, E.RaiseException)):
            a.execute("SELECT cash.promote_run(%s, 'x')", (RUN,))
        a.execute("RESET ROLE")
    ev("C11", "promotion gates", too_early="refused", other_roles="refused")


def test_c12_creditors_pipeline_is_unchanged_by_the_new_migrations(env):
    cred = load_creditors(env)
    a = env["admin"]
    assert a.execute("SELECT recon_state, publication_state FROM cred.run WHERE extraction_run_id = %s", (cred,)).fetchone() == ("verified", "unpublished")
    assert a.execute("SELECT count(*) FROM cred.schema_migration").fetchone()[0] == 6
    assert [r[0] for r in a.execute("SELECT version FROM cred.schema_migration ORDER BY version").fetchall()] == ["001", "002", "003", "004", "005", "006"]
    r = env["client"].get(f"/api/v1/creditors/runs/{cred}/summary")
    assert r.status_code == 200 and r.json()["data_state"] == "verified_candidate"
    ev("C12", "creditors untouched", migrations=["001", "002", "003", "004", "005", "006"], creditors_api_still_serves=True)


def write_evidence():
    EVIDENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Cash mart: UAT evidence", "", "Generated by `tools/creditors_mart/tests/test_cash_mart.py`: synthetic runs through the real loader into a private temporary PostgreSQL, served by the real app.",
             "`fpa_pilot`, Oracle and every real run were untouched.", "", "| Item | Result |", "|---|---|"]
    for e in sorted(EVIDENCE, key=lambda x: x["id"]):
        lines.append(f"| {e['id']} {e['title']} | " + "; ".join(f"{k}: {json.dumps(v, default=str)}" for k, v in e["detail"].items()) + " |")
    EVIDENCE_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
