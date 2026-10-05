"""
Entry layer UAT: schema `entry`, the loader, the entry API and the mart = API gate, on a PRIVATE, THROWAWAY PostgreSQL with SYNTHETIC runs only.
Covers the twelve drill controls (E1 to E12) and the telemetry rule: sensitive text is stored in the restricted table and never appears in logs, reports,
control evidence, rejection records, exception messages or masked responses. Evidence: docs/profit_cash/ENTRY_MART_UAT_EVIDENCE.md
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
import entry_loader as el  # noqa: E402
import entry_stage as es  # noqa: E402
import entry_synth as syn  # noqa: E402
import loader as cred_loader  # noqa: E402
import migrate  # noqa: E402
import test_cash_stage as tcs  # noqa: E402
import test_creditors_pilot as tcp  # noqa: E402
from app.entry_api import reconcile as rec  # noqa: E402
from app.entry_api import repository as entry_repo  # noqa: E402
from app.creditors_api.config import ApiSettings  # noqa: E402
from app.creditors_api.db import Db  # noqa: E402
from app.creditors_api.main import create_app  # noqa: E402
from test_cred_mart_db import PG_BIN, Cluster  # noqa: E402

EVIDENCE_FILE = ROOT.parent / "docs" / "profit_cash" / "ENTRY_MART_UAT_EVIDENCE.md"
SALT = "unit-test-pseudonym-key-0123456789"
TOKEN = "t" * 32
CRED_RUN, CASH_RUN, ENTRY_RUN = "run_20261004_940", "run_20261004_950", "run_20261005_960"
pytestmark = pytest.mark.skipif(not (PG_BIN / "initdb.exe").exists() and not shutil.which("initdb"), reason="PostgreSQL server binaries not found")
EVIDENCE: list[dict] = []


def ev(uid, title, **detail):
    EVIDENCE.append({"id": uid, "title": title, "detail": detail})


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    c = Cluster(tmp_path_factory.mktemp("pg_entry"))
    c.start()
    with c.connect("postgres") as a:
        a.execute("CREATE DATABASE entry_template")
    with c.connect("entry_template") as a:
        ran = migrate.apply(a)
    ev("N00", "migrations applied on a fresh database", versions=ran)
    yield c
    c.stop()
    shutil.rmtree(c.root, ignore_errors=True)
    ev("N99", "scratch instance removed", data_directory_removed=not c.root.exists())
    write_evidence()


_n = [0]


def make_env(cluster, tmp_path, cred_rows=None):
    """A fresh database holding a verified creditors run and a verified cash run, and the app wired to it. The entry run is staged by each test."""
    _n[0] += 1
    name = f"ent_{_n[0]:03d}"
    with cluster.connect("postgres") as a:
        a.execute(f"CREATE DATABASE {name} TEMPLATE entry_template")
    admin = cluster.connect(name)
    for r in ("cred_owner", "cash_owner", "entry_owner"):
        admin.execute(f"GRANT CONNECT, CREATE ON DATABASE {name} TO {r}")
    admin.execute(f"GRANT CONNECT ON DATABASE {name} TO cred_loader, cred_verifier, cred_promoter, cred_api_reader, cred_finance_reader, cash_loader, cash_verifier, cash_promoter, cash_api_reader, "
                  "entry_loader, entry_verifier, entry_promoter, entry_api_reader, entry_finance_reader")
    crun = tcp.build_run(tmp_path, rows=cred_rows, name=CRED_RUN)
    assert cs.validate(crun)["verdict"] == "PASSED"
    admin.execute("SET ROLE cred_loader")
    cred_loader.load_run(admin, cred_loader.preflight(crun, SALT))
    assert cred_loader.verify_loaded(admin, CRED_RUN)["ok"]
    admin.execute("RESET ROLE")
    cash = tcs.synth(tmp_path, name=CASH_RUN)
    assert cstage.validate(cash)["verdict"] == "PASSED"
    admin.execute("SET ROLE cash_loader")
    cl.load_run(admin, cl.preflight(cash))
    assert cl.verify_loaded(admin, CASH_RUN)["ok"]
    admin.execute("RESET ROLE")
    db = Db(cluster.dsn(name))
    app = create_app(ApiSettings(conninfo=cluster.dsn(name), finance_token=TOKEN, cors_origins=()), db)
    return {"admin": admin, "db": db, "client": TestClient(app), "name": name, "cluster": cluster, "tmp": tmp_path}


@pytest.fixture
def env(cluster, tmp_path):
    e = make_env(cluster, tmp_path)
    yield e
    e["admin"].close()
    with cluster.connect("postgres") as a:
        a.execute(f"DROP DATABASE {e['name']} WITH (FORCE)")


def stage(env, **kw):
    run, expected = syn.build(env["tmp"] / "entry", **kw) if (env["tmp"] / "entry").exists() else (None, None)
    return run, expected


def staged(env, **kw):
    d = env["tmp"] / f"e{len(list(env['tmp'].glob('e*')))}"
    d.mkdir()
    run, expected = syn.build(d, **kw)
    rep = es.validate(run)
    return run, expected, rep


def load_entry(env, run, salt=SALT):
    a = env["admin"]
    a.execute("SET ROLE entry_loader")
    try:
        plan = el.preflight(run, CRED_RUN, CASH_RUN, salt)
        return el.load_run(a, plan, salt)
    finally:
        a.execute("RESET ROLE")


def verify_entry(env):
    a = env["admin"]
    a.execute("SET ROLE entry_loader")
    try:
        return el.verify_loaded(a, ENTRY_RUN)
    finally:
        a.execute("RESET ROLE")


def ready(env, **kw):
    run, expected, rep = staged(env, **kw)
    assert rep["verdict"] == "PASSED", rep["hard_failures"]
    res = load_entry(env, run)
    assert verify_entry(env)["ok"]
    return run, expected, res


def base(p=""):
    return f"/api/v1/entries/runs/{ENTRY_RUN}{p}"


# ───────────── load, verify, the gate, promotion ─────────────


def test_n01_load_succeeds_with_every_control_and_cross_domain_check_green(env):
    run, expected, rep = staged(env)
    assert rep["verdict"] == "PASSED", rep["hard_failures"]
    res = load_entry(env, run)
    assert (res["recon_state"], res["publication_state"]) == ("loaded", "unpublished")
    assert res["controls"]["pass"] == res["controls"]["total"] > 40 and res["controls"]["max_abs_variance"] == "0.0000"
    assert all(v == 0 for v in res["checks"].values()) and {"M07_E3_entry_balances", "M13_E8_till_cumulative_and_day_totals", "X04_E7_bank_lines_equal_the_review_card", "X05_E8_till_equals_the_cash_card"} <= set(res["checks"])
    ev("N01", "load", entries=res["entries"], lines=res["lines"], links=res["links_by_status"], controls=res["controls"], checks=len(res["checks"]))


def test_n02_verify_then_the_api_gate_then_promotion(env):
    run, expected, res = ready(env)
    checks = rec.reconcile(env["client"], env["db"], ENTRY_RUN, CASH_RUN, CRED_RUN, TOKEN)
    bad = [c for c in checks if not c.ok]
    assert not bad, [(c.control, c.dimension, c.mart, c.api) for c in bad]
    out = rec.record(env["db"], ENTRY_RUN, checks)
    assert out["ok"] and out["recon_state"] == "api_verified"
    a = env["admin"]
    assert a.execute("SELECT mart_state, api_state, publication_state, is_live FROM core.v_domain_run WHERE domain = 'entries'").fetchone() == ("verified", "verified", "unpublished", False)
    a.execute("SET ROLE entry_promoter")
    a.execute("SELECT entry.promote_run(%s, 'UAT promotion')", (ENTRY_RUN,))
    a.execute("RESET ROLE")
    assert env["client"].get(base()).json()["data_state"] == "live"
    ev("N02", "verify, mart=API gate, promotion", api_checks=len(checks), controls={c.control for c in checks}.__len__(), live="live")


def test_n03_a_run_that_is_only_loaded_is_not_served_and_promotion_needs_api_verified(env):
    run, expected, rep = staged(env)
    load_entry(env, run)
    assert env["client"].get(base()).status_code == 404 and env["client"].get("/api/v1/entries/current").status_code == 404
    assert verify_entry(env)["ok"]
    a = env["admin"]
    a.execute("SET ROLE entry_promoter")
    with pytest.raises(E.RaiseException):
        a.execute("SELECT entry.promote_run(%s, 'too early')", (ENTRY_RUN,))
    a.execute("RESET ROLE")
    assert env["client"].get(base()).status_code == 200
    ev("N03", "serving and promotion gates", loaded="404", verified="served", promote_too_early="refused")


# ───────────── E1 to E9: the mart refuses a run that breaks a control ─────────────


def refused(env, run, stage_name="mart_controls"):
    a = env["admin"]
    a.execute("SET ROLE entry_loader")
    try:
        with pytest.raises(el.LoadError) as e:
            el.load_run(a, el.preflight(run, CRED_RUN, CASH_RUN, SALT), SALT)
    finally:
        a.execute("RESET ROLE")
    assert e.value.stage == stage_name
    for t in ("run", "entry_header", "entry_line", "entry_line_text", "creditor_bill_link", "till_day", "control_result"):
        assert a.execute(f"SELECT count(*) FROM entry.{t}").fetchone()[0] == 0, t           # every row rolled back
    assert a.execute("SELECT count(*) FROM entry.load_rejection").fetchone()[0] == 1
    return e.value


def test_n04_e7_bank_lines_that_do_not_sum_to_the_review_card_are_refused(env):
    run, _, rep = staged(env, bank_delta=True)
    assert rep["verdict"] == "PASSED"                                            # internally consistent: only the cross-domain check can see it
    e = refused(env, run)
    assert "X04_E7_bank_lines_equal_the_review_card" in e.failed
    ev("N04", "E7 bank drill must equal the review card", refused_by="X04", rows_left=0)


def test_n05_e8_a_cash_drawer_line_the_till_view_does_not_carry_is_refused(env):
    run, _, rep = staged(env, till_delta=True)
    assert rep["verdict"] == "PASSED"
    e = refused(env, run)
    assert "M13_E8_till_cumulative_and_day_totals" in e.failed or "M14_drawer_lines_without_a_till_day" in e.failed
    ev("N05", "E8 till day totals must equal the day's lines", refused_by=sorted(k for k in e.failed if k.startswith("M1")))


def test_n06_e8_cumulative_day_reconciliation_catches_a_wrong_running_balance(env):
    def tweak(files, b):
        rows, cols = files["l2_till_day"]
        rows[1]["cumulative_balance"] = str(Decimal(rows[1]["cumulative_balance"]) + 1)
        files["l2_till_day"] = (rows, cols)

    run, _, rep = staged(env, tweak=tweak)
    assert rep["verdict"] == "PASSED"
    e = refused(env, run)
    assert "M13_E8_till_cumulative_and_day_totals" in e.failed
    ev("N06", "E8 cumulative-day reconciliation", refused_by="M13 (running balance of all Cash Drawer lines up to the day)")


def test_n07_e11_a_different_snapshot_is_refused(env):
    def tweak(files, b):
        for k in ("c3_bills_pre", "c3_bills_post"):
            d, cols = files[k]
            files[k] = ([{**d[0], "cube_report_date": "2026-10-05", "register_report_date": "2026-10-05"}], cols)

    run, _, rep = staged(env, tweak=tweak)
    assert rep["verdict"] == "PASSED"
    e = refused(env, run)
    assert "X01_E11_as_of_lineage" in e.failed
    ev("N07", "E11 as-of lineage", refused_by="X01")


def test_n08_e6_every_bill_of_the_creditors_run_needs_exactly_one_link(cluster, tmp_path):
    rows = tcp.synth_rows()[:-1]                                                   # the creditors run holds one bill fewer than the entry run links
    e = make_env(cluster, tmp_path, cred_rows=rows)
    try:
        run, _, rep = staged(e)
        assert rep["verdict"] == "PASSED"
        err = refused(e, run)
        assert "X02_E6_every_bill_has_a_link" in err.failed
        ev("N08", "E6 bills = links", refused_by="X02")
    finally:
        e["admin"].close()
        with cluster.connect("postgres") as a:
            a.execute(f"DROP DATABASE {e['name']} WITH (FORCE)")


def test_n09_a_failed_source_control_or_tampered_derived_file_never_reaches_the_database(env):
    run, _, rep = staged(env)
    import pyarrow as pa
    import pyarrow.parquet as pq

    p = run / "staging" / "entry_line.parquet"
    t = pq.read_table(p)
    rows = t.to_pylist()
    rows[0]["debit"] += 1
    pq.write_table(pa.Table.from_pylist(rows, schema=t.schema), p)
    rp = run / "staging" / "validation_report.json"
    r = json.loads(rp.read_text(encoding="utf-8"))
    r["outputs"]["entry_line"] = es.mf.sha256_file(p)                              # a re-sealed hash: only the raw re-derivation can catch the edit
    rp.write_text(json.dumps(r), encoding="utf-8")
    with pytest.raises(el.LoadError) as e:
        el.preflight(run, CRED_RUN, CASH_RUN, SALT)
    assert "derived entry_line rows differ" in e.value.reason
    ev("N09", "tampered derived Parquet with a re-sealed hash", result="refused by the raw re-derivation")


def test_n10_e4_e5_constraints_live_in_the_database_not_only_in_the_loader(env):
    run, _, rep = staged(env)
    a = env["admin"]
    a.execute("SET ROLE entry_loader")
    plan = el.preflight(run, CRED_RUN, CASH_RUN, SALT)
    a.execute("SELECT 1")
    with a.transaction() as tx:
        headers, lines, identity, texts, links, till = plan.data
        el_ = el
        a.execute("INSERT INTO entry.run (entry_run_id, register_report_date, creditors_run_id, cash_run_id, till_balance_date, coverage_from, package, contract_version, rules, manifest_sha256, staging_report_sha256,"
                  " extract_started_at, extract_finished_at, expected_headers, expected_lines, expected_links, expected_till_days) VALUES (%s,'2026-10-04',%s,%s,'2026-10-03','2023-04-01','entry_pilot_01','drill-1.0','{}',"
                  "%s,%s,now(),now(),1,1,1,1)", (ENTRY_RUN, CRED_RUN, CASH_RUN, "a" * 64, "b" * 64))
        h = headers[0]
        a.execute("INSERT INTO entry.entry_header (entry_run_id, entry_ref, site_code, entry_type_short, entry_date, release_status, line_count, total_dr, total_cr, selections) VALUES (%s,%s,'1','X','2026-10-01','Posted',1,0,0,%s)", (ENTRY_RUN, h["entry_ref"], ["bank"]))
        for bad in (("AMBIGUOUS", 2, h["entry_ref"], None), ("EXACT", 1, None, True), ("EXACT", 1, h["entry_ref"], False), ("NOT_LINKED", 0, h["entry_ref"], None), ("STRONG", 1, None, False)):
            sp = a.transaction()
            sp.__enter__()
            with pytest.raises(E.CheckViolation):
                a.execute("INSERT INTO entry.creditor_bill_link (entry_run_id, creditors_run_id, source_row_key, ledger_code, bill_amount, link_status, not_linked_reason, key_used, matched_entries, entry_ref, amount_agrees, coverage) "
                          "VALUES (%s,%s,%s,'1',1,%s,%s,'k',%s,%s,%s,'CURRENT_FY')", (ENTRY_RUN, CRED_RUN, "c" * 64, bad[0], "NO_MATCH" if bad[0] == "NOT_LINKED" else None, bad[1], bad[2], bad[3]))
            sp.__exit__(E.CheckViolation, None, None)
        tx.__class__  # the outer transaction is rolled back below
        raise psycopg.Rollback()
    a.execute("RESET ROLE")
    ev("N10", "E4 / E5 as database constraints", refused=["ambiguous with an entry", "exact without one", "exact without amount agreement", "not linked with an entry", "strong without one"])


# ───────────── privileges, masking and telemetry ─────────────


def test_n11_e12_the_database_refuses_restricted_text_to_every_role_but_finance(env):
    ready(env)
    a = env["admin"]
    denied = 0
    for role in ("entry_api_reader", "entry_verifier", "entry_promoter", "entry_loader", "cash_api_reader", "cred_api_reader"):
        for rel in ("entry.entry_line_text", "entry.v_entry_line_text", "entry.entry_identity", "entry.v_entry_identity"):
            a.execute(f"SET ROLE {role}")
            with pytest.raises((E.InsufficientPrivilege, E.UndefinedTable)):
                a.execute(f"SELECT narration FROM {rel} LIMIT 1" if "text" in rel else f"SELECT entry_no FROM {rel} LIMIT 1")
            a.execute("RESET ROLE")
            denied += 1
    a.execute("SET ROLE entry_finance_reader")
    assert a.execute("SELECT count(*) FROM entry.v_entry_line_text").fetchone()[0] > 0
    with pytest.raises(E.InsufficientPrivilege):
        a.execute("SELECT count(*) FROM entry.entry_line_text")                    # not even the finance role touches the base table
    a.execute("RESET ROLE")
    a.execute("SET ROLE entry_api_reader")
    assert a.execute("SELECT count(*) FROM entry.v_entry_line").fetchone()[0] > 0
    cols = {r[0] for r in a.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'entry' AND table_name IN ('v_entry_line', 'v_entry_header', 'v_creditor_bill_link', 'v_till_day', 'v_bank_entry', 'v_cash_drawer_entry')").fetchall()}
    a.execute("RESET ROLE")
    assert not cols & {"narration", "reference_no", "cheque_no", "prepared_by", "released_by", "entry_no", "sub_ledger_code", "counter_ledgers"}
    ev("N11", "E12 at the database privilege layer", denied_combinations=denied, finance_reads_text_only_through_the_view=True, masked_views_have_no_restricted_column=True)


def test_n12_e12_masked_api_responses_carry_no_restricted_field_or_value_and_finance_needs_the_token(env):
    ready(env)
    c = env["client"]
    refs = [r["entry_ref"] for r in env["admin"].execute("SELECT entry_ref FROM entry.entry_header ORDER BY entry_ref LIMIT 40").fetchall()] if False else None
    with env["db"].session("entry_verifier") as cx:
        refs = [r["entry_ref"] for r in cx.execute("SELECT entry_ref FROM entry.v_entry_header ORDER BY entry_ref").fetchall()]
    dump = ""
    for ref in refs:
        r = c.get(base(f"/entry/{ref}"))
        assert r.status_code == 200
        assert not (set(rec.keys_of(r.json())) & rec.RESTRICTED_KEYS), ref
        dump += r.text
    for s in syn.SENTINELS:
        assert s not in dump, s
    assert "No verified attachment source available" in dump
    assert c.get(base(f"/finance/entry/{refs[0]}")).status_code == 401
    assert c.get(base(f"/finance/entry/{refs[0]}"), headers={"Authorization": "Bearer wrong"}).status_code == 401
    fin = c.get(base(f"/finance/entry/{refs[0]}"), headers={"Authorization": f"Bearer {TOKEN}"}).json()["entry"]
    assert fin["identity"]["entry_no"] and any(syn.SENT_NARR in (ln["text"]["narration"] or "") for ln in fin["lines"])
    ev("N12", "E12 at the API layer", entries_checked=len(refs), restricted_keys_in_masked=0, sentinels_in_masked=0, finance_without_token="401", finance_with_token="identity and text")


def test_n13_telemetry_is_metadata_only_on_success_and_on_every_failure_path(env, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    run, _, rep = staged(env)
    res = load_entry(env, run)
    verify_entry(env)
    reports = el.render_report(res) + json.dumps(res, default=str)
    e2 = None
    # a second run, refused on a control variance, also must not leak
    with env["db"].session("entry_verifier") as cx:
        pass
    d = env["tmp"] / "e_refused"
    d.mkdir()
    run2, _ = syn.build(d, name="run_20261005_961", bank_delta=True)
    es.validate(run2)
    a = env["admin"]
    a.execute("SET ROLE entry_loader")
    try:
        el.load_run(a, el.preflight(run2, CRED_RUN, CASH_RUN, SALT), SALT)
    except el.LoadError as ex:
        e2 = ex
    a.execute("RESET ROLE")
    assert e2 is not None
    # a database error whose DETAIL carries a row value: safe_reason keeps the class and the constraint name only
    class FakeDiag:
        constraint_name = "some_check"
        message_detail = f"Failing row contains ({syn.SENT_NARR})"

    fake = psycopg.errors.CheckViolation(f"violates check constraint: {syn.SENT_NARR}")
    fake._info = None
    try:
        object.__setattr__(fake, "diag", FakeDiag())
    except Exception:  # noqa: BLE001
        pass
    reason = el.safe_reason(fake)
    assert syn.SENT_NARR not in reason
    out = capsys.readouterr()
    sinks = {
        "logs": caplog.text, "console": out.out + out.err, "load report": reports, "refusal message": str(e2) + json.dumps(e2.failed),
        "staging report": (run / "staging" / "validation_report.json").read_text(encoding="utf-8") + (run / "staging" / "VALIDATION_REPORT.md").read_text(encoding="utf-8"),
        "control evidence": json.dumps([list(map(str, r)) for r in a.execute("SELECT control_id, dimension, left_layer, right_layer FROM entry.control_result").fetchall()]),
        "run events": json.dumps([str(r) for r in a.execute("SELECT detail FROM entry.run_event").fetchall()]),
        "rejection records": json.dumps([str(r) for r in a.execute("SELECT reason, failed_controls FROM entry.load_rejection").fetchall()]),
    }
    for where, blob in sinks.items():
        for s in syn.SENTINELS:
            assert s not in blob, f"{s} leaked into {where}"
    stored = a.execute("SELECT count(*) FROM entry.entry_line_text WHERE narration LIKE %s", (syn.SENT_NARR + "%",)).fetchone()[0]
    assert stored > 0                                                              # it IS stored, in the restricted table
    ev("N13", "telemetry stays metadata-only", sinks_checked=sorted(sinks), sentinels=len(syn.SENTINELS), leaks=0, text_rows_stored_in_the_restricted_table=stored)


def test_n14_immutability_and_role_separation(env):
    ready(env)
    a = env["admin"]
    for role in ("entry_loader", "entry_owner", "entry_api_reader", "entry_finance_reader", "entry_verifier"):
        a.execute(f"SET ROLE {role}")
        for stmt in ("UPDATE entry.entry_line SET debit = 0", "DELETE FROM entry.entry_header", "UPDATE entry.run SET publication_state = 'live'", "UPDATE entry.entry_line_text SET narration = 'x'",
                     "SELECT entry.promote_run('run_20261005_960', 'x')"):
            with pytest.raises((E.InsufficientPrivilege, E.RaiseException)):
                a.execute(stmt)
        a.execute("RESET ROLE")
    a.execute("SET ROLE entry_loader")
    with pytest.raises((E.RaiseException, E.InsufficientPrivilege)):                # a closed run takes no more rows
        a.execute("INSERT INTO entry.till_day (entry_run_id, cash_run_id, site_code, day, debit, credit, cumulative_balance) VALUES (%s,%s,'S9','2026-10-01',0,0,0)", (ENTRY_RUN, CASH_RUN))
    a.execute("RESET ROLE")
    a.execute("SET ROLE cash_api_reader")
    with pytest.raises(E.InsufficientPrivilege):
        a.execute("SELECT count(*) FROM entry.v_entry_line")
    a.execute("RESET ROLE")
    ev("N14", "immutability and separation", roles_tested=5, statements_refused=25, other_domain_reader="refused")


# ───────────── the drills (E7, E8, E10, E11) and the bridge semantics (E4, E5, E9) ─────────────


def test_n15_bank_drill_reconciles_at_every_level(env):
    ready(env)
    c = env["client"]
    led = c.get(base("/bank/ledgers"), params={"cash_run": CASH_RUN}).json()
    assert led["reconciles"] and all(r["reconciles"] for r in led["ledgers"]) and len(led["ledgers"]) == 4 and led["status"] == "PROVISIONAL · NOT BANK-RECONCILED"
    checked = 0
    for r in led["ledgers"]:
        for status in ("posted", "unposted", "opening"):
            page = c.get(base(f"/bank/ledgers/{r['ledger_code']}/entries"), params={"cash_run": CASH_RUN, "status": status}).json()
            assert page["reconciles"], (r["ledger_code"], status)
            checked += 1
            if page["entries"]:
                e = c.get(base(f"/entry/{page['entries'][0]['entry_ref']}")).json()["entry"]
                assert e["balanced"] and len(e["lines"]) == e["line_count"]
    assert c.get(base("/bank/ledgers"), params={"cash_run": "run_19990101_001"}).status_code == 409                       # E11
    ev("N15", "bank drill", ledgers=len(led["ledgers"]), entry_lists_reconciled=checked, wrong_run="409")


def test_n16_till_drill_reconciles_store_day_entry(env):
    ready(env)
    c = env["client"]
    ts = c.get(base("/till/stores"), params={"cash_run": CASH_RUN}).json()
    assert ts["reconciles"] and ts["label"] == "Store Till Cash" and Decimal(ts["children_sum"]["store_till_cash"]) == Decimal("11850.25")
    n_days = n_entries = 0
    for s in ts["stores"]:
        days = c.get(base(f"/till/stores/{s['site_code']}/days"), params={"cash_run": CASH_RUN}).json()
        assert days["reconciles"], s["site_code"]
        for d in days["days"]:
            res = c.get(base(f"/till/stores/{s['site_code']}/days/{d['day']}/entries"), params={"cash_run": CASH_RUN}).json()
            assert res["reconciles"] and res["entries"]
            n_days += 1
            n_entries += len(res["entries"])
    assert n_days >= 7 and c.get(base("/till/stores/S001/days/2026-10-02/entries"), params={"cash_run": "run_19990101_001"}).status_code == 409
    ev("N16", "till drill", stores=len(ts["stores"]), store_days_reconciled=n_days, entries=n_entries)


def test_n17_creditor_bridge_semantics_are_exposed_exactly(env):
    ready(env)
    c = env["client"]
    summ = c.get(base("/creditors/links"), params={"creditors_run": CRED_RUN}).json()
    counts = {}
    for r in summ["by_status_and_coverage"]:
        counts[r["link_status"]] = counts.get(r["link_status"], 0) + r["bills"]
    assert set(counts) == {"EXACT", "STRONG", "AMBIGUOUS", "NOT_LINKED"} and summ["total"] == 48
    with env["db"].session("entry_verifier") as cx:
        links = cx.execute("SELECT source_row_key, link_status, entry_ref, not_linked_reason, coverage, matched_entries, amount_agrees, entry_net_amount, bill_amount FROM entry.v_creditor_bill_link").fetchall()
    seen = set()
    for k in links:
        r = c.get(base(f"/creditors/items/{k['source_row_key']}/link"), params={"creditors_run": CRED_RUN}).json()
        link = r["link"]
        seen.add(link["link_status"])
        assert r["attachment"] == {"available": False, "message": "No verified attachment source available"}
        if link["link_status"] == "EXACT":
            assert link["entry_ref"] and link["amount_agrees"] is True and abs(Decimal(link["entry_net_amount"])) == abs(Decimal(link["bill_amount"]))     # E9
            assert c.get(base(f"/entry/{link['entry_ref']}")).status_code == 200
        if link["link_status"] in ("AMBIGUOUS", "NOT_LINKED"):
            assert link["entry_ref"] is None                                       # E5: never auto-selected
        if link["not_linked_reason"] == "REGISTER_COVERAGE_UNAVAILABLE":
            assert link["message"] == "Entry drill unavailable — source register coverage before Apr 2023 not available." and link["coverage"] == "BEFORE_COVERAGE"
        if link["link_status"] == "AMBIGUOUS":
            assert "none is selected" in link["message"]
    assert seen == {"EXACT", "STRONG", "AMBIGUOUS", "NOT_LINKED"}
    assert c.get(base("/creditors/links"), params={"creditors_run": "run_19990101_001"}).status_code == 409
    ev("N17", "creditor bridge exposure", statuses=counts, coverage_gap_message="exact text", ambiguous_selects_nothing=True, exact_amount_corroborated=True)


def test_n18_a_masked_entry_line_carries_the_same_pseudonym_as_the_creditors_mart(env):
    ready(env)
    with env["db"].session("entry_verifier") as cx:
        ex = cx.execute("SELECT entry_ref, source_row_key FROM entry.v_creditor_bill_link WHERE link_status = 'EXACT' LIMIT 1").fetchone()
        line = cx.execute("SELECT sub_ledger_ref FROM entry.v_entry_line WHERE entry_ref = %s AND sub_ledger_ref IS NOT NULL", (ex["entry_ref"],)).fetchone()
    with env["db"].session("candidate") as cx:
        vref = cx.execute("SELECT vendor_ref FROM cred.v_open_item_candidate WHERE item_ref = %s", (ex["source_row_key"],)).fetchone()
    assert line["sub_ledger_ref"] == vref["vendor_ref"] and line["sub_ledger_ref"].startswith("V")
    ev("N18", "masked sub-ledger reference", equals_creditors_vendor_ref=True)


def test_n19_the_gate_blocks_on_a_single_paisa(env, monkeypatch):
    ready(env)
    real = entry_repo.till_stores

    def off(conn, run):
        rows = real(conn, run)
        rows[0] = {**rows[0], "balance": rows[0]["balance"] + Decimal("0.01")}
        return rows

    monkeypatch.setattr(entry_repo, "till_stores", off)
    checks = rec.reconcile(env["client"], env["db"], ENTRY_RUN, CASH_RUN, CRED_RUN, TOKEN)
    bad = [c for c in checks if not c.ok]
    assert [c.dimension for c in bad] == ["the store list reconciles to Store Till Cash"]
    with env["db"].session("entry_verifier", readonly=False) as cx:
        for ch in checks:
            cx.execute("SELECT entry.record_control(%s,%s,%s,'mart',%s,'api',%s)", (ENTRY_RUN, ch.control, ch.dimension[:200], ch.mart, ch.api))
        r = cx.execute("SELECT entry.api_verify_run(%s) AS r", (ENTRY_RUN,)).fetchone()["r"]
    assert r["ok"] is False and env["admin"].execute("SELECT recon_state FROM entry.run").fetchone()[0] == "verified"
    ev("N19", "one paisa blocks api_verified", blocked=True)


def test_n20_the_shared_run_model_shows_all_three_domains_and_creditors_is_unchanged(env):
    ready(env)
    a = env["admin"]
    rows = {r[0]: r[1:] for r in a.execute("SELECT domain, run_id, mart_state FROM core.v_domain_run ORDER BY domain").fetchall()}
    assert set(rows) == {"cash", "creditors", "entries"}
    assert a.execute("SELECT recon_state, publication_state FROM cred.run").fetchone() == ("verified", "unpublished")
    assert [r[0] for r in a.execute("SELECT version FROM cred.schema_migration ORDER BY version").fetchall()] == ["001", "002", "003", "004", "005"]
    assert env["client"].get(f"/api/v1/creditors/runs/{CRED_RUN}/summary").status_code == 200 and env["client"].get(f"/api/v1/cash/runs/{CASH_RUN}/summary").status_code == 200
    ev("N20", "shared run model and untouched domains", domains=sorted(rows), creditors_state="verified / unpublished")


def write_evidence():
    EVIDENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Entry layer: UAT evidence", "", "Generated by `tools/creditors_mart/tests/test_entry_mart.py`: synthetic runs through the real loader into a private temporary PostgreSQL, served by the real app.",
             "`fpa_pilot`, Oracle and every real run were untouched.", "", "| Item | Result |", "|---|---|"]
    for e in sorted(EVIDENCE, key=lambda x: x["id"]):
        lines.append(f"| {e['id']} {e['title']} | " + "; ".join(f"{k}: {json.dumps(v, default=str)}" for k, v in e["detail"].items()) + " |")
    EVIDENCE_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
