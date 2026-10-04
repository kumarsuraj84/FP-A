"""
Offline UAT for tools/creditors_mart/loader.py.

Runs against a PRIVATE, THROWAWAY PostgreSQL instance (own folder, random localhost port, deleted afterwards) with SYNTHETIC runs only.
It never connects to fpa_pilot, to the application database, to Oracle or to anything real, and it loads no real run.
Evidence: docs/creditors_pilot/LOADER_UAT_EVIDENCE.md
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from psycopg import errors as E

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(ROOT / "extraction_broker"))
sys.path.insert(0, str(ROOT / "extraction_broker" / "tests"))
sys.path.insert(0, str(HERE))
import creditors_stage as cs  # noqa: E402
import loader  # noqa: E402
import manifest as mf  # noqa: E402
import migrate  # noqa: E402
import test_creditors_pilot as tcp  # noqa: E402
from test_cred_mart_db import PG_BIN, Cluster  # noqa: E402

EVIDENCE_FILE = ROOT.parent / "docs" / "creditors_pilot" / "LOADER_UAT_EVIDENCE.md"
SALT = "unit-test-pseudonym-key-0123456789"
pytestmark = pytest.mark.skipif(not (PG_BIN / "initdb.exe").exists() and not shutil.which("initdb"), reason="PostgreSQL server binaries not found")

EVIDENCE: list[dict] = []
VENDOR_NAMES = [f"Vendor {i}" for i in range(7)]
SENTINELS = VENDOR_NAMES + ["DOC0001", "DOC0010", "SL500", "SL501", "Supplier-Apparels"]


def ev(uid: str, title: str, **detail):
    EVIDENCE.append({"id": uid, "title": title, "detail": detail})


# ───────────── infrastructure ─────────────


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    root = tmp_path_factory.mktemp("pg_loader")
    c = Cluster(root)
    c.start()
    with c.connect("postgres") as a:
        a.execute("CREATE DATABASE loader_template")
    with c.connect("loader_template") as a:
        migrate.apply(a)
    yield c
    c.stop()
    shutil.rmtree(root, ignore_errors=True)
    ev("L00", "scratch instance removed", data_directory_removed=not root.exists())
    write_evidence()


_n = [0]


@pytest.fixture
def dbs(cluster):
    """(loader connection acting as cred_loader, admin connection) on a fresh migrated database."""
    _n[0] += 1
    name = f"ld_{_n[0]:03d}"
    with cluster.connect("postgres") as a:
        a.execute(f"CREATE DATABASE {name} TEMPLATE loader_template")
    admin = cluster.connect(name)
    admin.execute(f"GRANT CONNECT, CREATE ON DATABASE {name} TO cred_owner")
    admin.execute(f"GRANT CONNECT ON DATABASE {name} TO cred_loader, cred_verifier, cred_promoter, cred_api_reader, cred_finance_reader")
    conn = cluster.connect(name)
    conn.execute("SET ROLE cred_loader")
    yield conn, admin
    conn.close()
    admin.close()
    with cluster.connect("postgres") as a:
        a.execute(f"DROP DATABASE {name} WITH (FORCE)")


class Spy:
    """Stands in for a database connection: any use at all fails the test."""

    used = 0

    def __getattr__(self, name):
        Spy.used += 1
        raise AssertionError(f"the database was used ({name}) before preflight finished")


def sealed(tmp_path, name="run_20261004_901", rows=None):
    run = tcp.build_run(tmp_path, rows=rows, name=name)
    rep = cs.validate(run)
    assert rep["verdict"] == "PASSED", rep["hard_failures"]
    return run


def flow(conn, run):
    return loader.load_run(conn, loader.preflight(run, SALT))


def tables(admin, run_id=None):
    out = {}
    for t in ("run", "vendor_snapshot", "open_item", "identity_snapshot", "control_result", "run_event", "live_run"):
        out[t] = admin.execute(f"SELECT count(*) FROM cred.{t}").fetchone()[0]
    return out


def reseal(run: Path, mutate):
    """Edit the derived Parquet AND re-record its hash in the staging report, so only the content check can catch the change."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    dp = run / "staging" / "creditor_open_items.parquet"
    t = pq.read_table(dp)
    rows = t.to_pylist()
    mutate(rows)
    pq.write_table(pa.Table.from_pylist(rows, schema=t.schema), dp)
    rp = run / "staging" / "validation_report.json"
    rep = json.loads(rp.read_text(encoding="utf-8"))
    rep["outputs"]["creditor_open_items"] = mf.sha256_file(dp)
    rp.write_text(json.dumps(rep), encoding="utf-8")


# ───────────── L01 / L15: a correct run ─────────────


def test_l01_correct_run_loads_and_ends_loaded_and_unpublished(dbs, tmp_path):
    conn, admin = dbs
    run = sealed(tmp_path)
    res = flow(conn, run)
    rep = json.loads((run / "staging" / "validation_report.json").read_text(encoding="utf-8"))
    raw = cs.load(run, "e1_open_items")
    assert (res["recon_state"], res["publication_state"], res["live_runs"]) == ("loaded", "unpublished", 0)
    assert res["rows"] == {"open_item": 48, "vendor_snapshot": 7, "distinct_source_keys": 48, "identity_snapshot": 51}
    assert Decimal(res["signed_net"]) == sum(Decimal(r["pending"]) for r in raw)
    assert Decimal(res["credit_outstanding"]) + Decimal(res["creditor_debit_balance"]) == sum(abs(Decimal(r["pending"])) for r in raw)
    c = res["controls"]
    assert c["total"] == c["pass"] == len(rep["controls"]) + c["extract_to_mart"] and c["source_to_extract"] == len(rep["controls"])
    assert Decimal(c["max_abs_variance"]) == 0 and Decimal(res["extract_vs_mart"]["row_variance"]) == 0 and Decimal(res["extract_vs_mart"]["money_variance"]) == 0
    assert all(v == 0 for v in res["mart_checks"].values()) and set(res["mart_checks"]) >= {f"M{i}_" + x for i, x in ((1, "rows_vs_expected"), (2, "duplicate_business_key"), (3, "key_conflicting_identity"))}
    assert res["loaded_by"] == "cred_loader"
    t = tables(admin)
    assert t["run"] == 1 and t["live_run"] == 0 and t["run_event"] == 0              # nothing promoted, no state event: it is simply loaded
    assert admin.execute("SELECT recon_state, publication_state, expected_rows, expected_identity_rows FROM cred.run").fetchone() == ("loaded", "unpublished", 48, 51)
    ev("L01", "correct run loads", rows=res["rows"], controls=c, final_state=[res["recon_state"], res["publication_state"]], live_runs=res["live_runs"])


def test_l15_verification_is_a_separate_gate_and_still_unpublished(dbs, tmp_path):
    conn, admin = dbs
    run = sealed(tmp_path)
    flow(conn, run)
    out = loader.verify_loaded(conn, "run_20261004_901")
    assert out["ok"] is True
    assert admin.execute("SELECT recon_state, publication_state FROM cred.run").fetchone() == ("verified", "unpublished")
    assert tables(admin)["live_run"] == 0
    with pytest.raises(E.InsufficientPrivilege):
        conn.execute("SELECT cred.promote_run('run_20261004_901','x')")
    ev("L15", "verification is separate and never publishes", after_verify=["verified", "unpublished"], loader_promote="permission denied")


# ───────────── L02 / L03 / L04: identity and vendor refusals ─────────────


def test_l02_duplicate_item_is_refused_before_and_inside_the_database(dbs, tmp_path):
    conn, admin = dbs
    rows = tcp.synth_rows()
    rows.append({**rows[0]})                                              # the same business key twice in the raw extract
    run = tcp.build_run(tmp_path, rows=rows, name="run_20261004_902")
    rep = cs.validate(run)
    assert rep["verdict"] == "FAILED"
    with pytest.raises(loader.LoadError) as a:
        loader.preflight(run, SALT)
    assert a.value.stage == "staging_report"
    # a duplicate that reaches the database is refused by the constraints and rolls back everything
    good = sealed(tmp_path / "ok", "run_20261004_903") if (tmp_path / "ok").mkdir() is None else None
    plan = loader.preflight(good, SALT)
    plan.items.append(dict(plan.items[0]))
    with pytest.raises(loader.LoadError) as b:
        loader.load_run(conn, plan)
    assert b.value.stage == "load" and "UniqueViolation" in b.value.reason
    assert tables(admin) == {"run": 0, "vendor_snapshot": 0, "open_item": 0, "identity_snapshot": 0, "control_result": 0, "run_event": 0, "live_run": 0}
    rej = admin.execute("SELECT stage, reason FROM cred.load_rejection").fetchall()
    assert len(rej) == 1 and rej[0][0] == "load" and "DOC" not in rej[0][1]
    ev("L02", "duplicate item refused", staging_blocks_duplicates=True, database_constraint=b.value.reason, rows_left_behind=0, rejection_recorded=rej[0][0])


def test_l03_conflicting_source_key_is_refused(dbs, tmp_path):
    conn, admin = dbs
    run = sealed(tmp_path, "run_20261004_904")
    reseal(run, lambda rows: rows[0].update(source_row_key=cs.sha("not this row")))
    with pytest.raises(loader.LoadError) as a:
        loader.preflight(run, SALT)
    assert a.value.stage == "precheck" and "source_row_key" in a.value.reason
    (tmp_path / "b").mkdir()
    plan = loader.preflight(sealed(tmp_path / "b", "run_20261004_905"), SALT)
    plan.items[0]["source_row_key"] = cs.sha("conflicting key")           # same parts, a different key
    with pytest.raises(loader.LoadError) as b:
        loader.load_run(conn, plan)
    assert b.value.stage == "load" and "CheckViolation" in b.value.reason
    assert tables(admin)["open_item"] == 0 and tables(admin)["run"] == 0
    ev("L03", "conflicting source key refused", preflight=a.value.reason, database=b.value.reason, rows_left_behind=0)


def test_l04_missing_vendor_is_refused(dbs, tmp_path):
    conn, admin = dbs
    plan = loader.preflight(sealed(tmp_path, "run_20261004_906"), SALT)
    plan.vendors = plan.vendors[1:]                                        # one vendor missing from the snapshot
    with pytest.raises(loader.LoadError) as e:
        loader.load_run(conn, plan)
    assert e.value.stage == "load" and "ForeignKeyViolation" in e.value.reason
    assert tables(admin)["run"] == 0 and tables(admin)["vendor_snapshot"] == 0 and tables(admin)["open_item"] == 0
    ev("L04", "missing vendor refused", reason=e.value.reason, rows_left_behind=0)


# ───────────── L05 / L06: nothing touches the database when the inputs are wrong ─────────────


def test_l05_wrong_hash_fails_before_any_database_use(tmp_path):
    spy = Spy()
    run = sealed(tmp_path, "run_20261004_907")
    dp = run / "staging" / "creditor_open_items.parquet"
    dp.write_bytes(dp.read_bytes() + b"x")                                 # any change to the derived file breaks the hash chain
    with pytest.raises(loader.LoadError) as e:
        flow(spy, run)
    assert e.value.stage == "staging_report" and "hash" in e.value.reason and Spy.used == 0
    (tmp_path / "raw").mkdir()
    run2 = sealed(tmp_path / "raw", "run_20261004_908")
    f = run2 / "e1_open_items.parquet"
    f.write_bytes(f.read_bytes() + b"x")                                   # the raw extract no longer matches the manifest
    with pytest.raises(loader.LoadError) as e2:
        flow(spy, run2)
    assert e2.value.stage == "precheck" and Spy.used == 0
    ev("L05", "wrong hash fails before the database", derived_parquet=e.value.reason, raw_extract=e2.value.reason, database_calls=Spy.used)


def test_l06_manifest_mismatch_fails_before_any_database_write(tmp_path):
    spy = Spy()
    run = sealed(tmp_path, "run_20261004_909")
    m = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    m["contract"]["rules_version"] = "9"                                   # a valid manifest, but not the one staging validated
    (run / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(loader.LoadError) as a:
        flow(spy, run)
    assert a.value.stage == "staging_report" and "manifest changed" in a.value.reason
    (tmp_path / "x").mkdir()
    run2 = sealed(tmp_path / "x", "run_20261004_910")
    m2 = json.loads((run2 / "manifest.json").read_text(encoding="utf-8"))
    m2["datasets"][3]["sha256"] = "0" * 64                                 # a dataset hash that does not match its file
    (run2 / "manifest.json").write_text(json.dumps(m2), encoding="utf-8")
    with pytest.raises(loader.LoadError) as b:
        flow(spy, run2)
    assert b.value.stage == "precheck"
    for bad_name in ("run_test_001", "latest", "../run_20261004_001"):
        with pytest.raises(loader.LoadError):
            loader.preflight(tmp_path / bad_name, SALT)
    (tmp_path / "y").mkdir()
    run3 = tcp.build_run(tmp_path / "y", name="run_20261004_911")            # never staged
    with pytest.raises(loader.LoadError) as c:
        flow(spy, run3)
    assert c.value.stage == "staging_report" and Spy.used == 0
    ev("L06", "manifest mismatch fails before the database", contract_edit=a.value.reason, dataset_hash_edit=b.value.reason, unstaged_run=c.value.reason, database_calls=Spy.used)


# ───────────── L07 / L08: exact values ─────────────


def test_l07_numeric_precision_is_exact(dbs, tmp_path):
    conn, admin = dbs
    rows = tcp.synth_rows()
    forced = {0: "-.5", 1: "-80104438.00", 2: "-0.01", 3: "123456789.12", 4: "-1.2345", 7: "999999999999.9999"}
    for i, p in forced.items():
        rows[i]["amount"] = rows[i]["pending"] = p
    rows[7]["drcr"] = "Dr"
    run = sealed(tmp_path, "run_20261004_912", rows)
    res = flow(conn, run)
    got = {r[0]: r[1] for r in admin.execute("SELECT document_code, pending FROM cred.open_item WHERE document_code = ANY(%s)", ([rows[i]["document_code"] for i in forced],))}
    for i, p in forced.items():
        assert got[rows[i]["document_code"]] == Decimal(p), (p, got[rows[i]["document_code"]])
    total = sum(Decimal(r["pending"]) for r in rows)
    assert Decimal(res["signed_net"]) == total
    assert admin.execute("SELECT sum(pending) FROM cred.open_item").fetchone()[0] == total
    assert admin.execute("SELECT count(*) FROM cred.open_item WHERE pending::text ~ 'e'").fetchone()[0] == 0
    ev("L07", "numeric precision exact", forced_values={k: v for k, v in list(forced.items())[:5]}, tm9_leading_dot_accepted=True, signed_net_equals_decimal_sum=True)


def test_l08_bad_and_ancient_dates_survive_as_text_and_are_classified(dbs, tmp_path):
    conn, admin = dbs
    rows = tcp.synth_rows()
    rows[8]["document_date"] = "2026-12-31"                                 # after the as-of date
    run = sealed(tmp_path, "run_20261004_913", rows)
    flow(conn, run)
    q = lambda i: admin.execute("SELECT document_date_raw, document_date, document_age_bucket, document_age_days, date_quality_status FROM cred.open_item WHERE document_code = %s", (rows[i]["document_code"],)).fetchone()  # noqa: E731
    assert q(5) == ("0202-01-01", date(202, 1, 1), "UNCLASSIFIED_BEFORE_MIN", None, "BEFORE_MIN")
    assert q(6) == (None, None, "UNCLASSIFIED_MISSING", None, "MISSING")
    assert q(8) == ("2026-12-31", date(2026, 12, 31), "UNCLASSIFIED_AFTER_AS_OF", None, "AFTER_AS_OF")
    due = admin.execute("SELECT due_status, count(*) FROM cred.open_item GROUP BY 1").fetchall()
    assert {d[0] for d in due} >= {"DUE_UNAVAILABLE", "NOT_YET_DUE", "DUE_INVALID"}
    ev("L08", "bad and ancient dates survive", year_0202="raw text kept, classified BEFORE_MIN", missing="stays NULL, classified MISSING", future="AFTER_AS_OF", due_states=sorted(d[0] for d in due))


# ───────────── L09 / L10: all-or-nothing and no double load ─────────────


def test_l09_failed_control_rolls_back_every_fact_row(dbs, tmp_path):
    conn, admin = dbs
    plan = loader.preflight(sealed(tmp_path, "run_20261004_914"), SALT)
    plan.expected[("M-C2", "credit outstanding")] += Decimal("0.01")      # one paisa of disagreement between extract and mart
    with pytest.raises(loader.LoadError) as e:
        loader.load_run(conn, plan)
    assert e.value.stage == "mart_controls" and e.value.failed == {"M-C2": 1}
    assert tables(admin) == {"run": 0, "vendor_snapshot": 0, "open_item": 0, "identity_snapshot": 0, "control_result": 0, "run_event": 0, "live_run": 0}
    rej = admin.execute("SELECT stage, failed_controls FROM cred.load_rejection").fetchall()
    assert rej == [("mart_controls", {"M-C2": 1})]
    # structural failure also rolls back: an expected-rows value that the data cannot meet
    plan2 = loader.preflight(sealed(tmp_path / "s", "run_20261004_915") if (tmp_path / "s").mkdir() is None else None, SALT)
    plan2.expected_rows += 1
    with pytest.raises(loader.LoadError) as e2:
        loader.load_run(conn, plan2)
    assert e2.value.stage == "mart_controls" and "M1_rows_vs_expected" in e2.value.failed
    assert tables(admin)["open_item"] == 0 and tables(admin)["run"] == 0
    ev("L09", "failed control rolls back all rows", control_failure=e.value.failed, structural_failure=e2.value.failed, rows_left_behind=0, rejections=2)


def test_l10_second_attempt_cannot_create_a_duplicate_load(dbs, tmp_path):
    conn, admin = dbs
    run = sealed(tmp_path, "run_20261004_916")
    plan = loader.preflight(run, SALT)
    loader.load_run(conn, plan)
    before = tables(admin)
    with pytest.raises(loader.AlreadyLoaded):
        loader.load_run(conn, plan)
    assert tables(admin) == before and before["run"] == 1
    plan.manifest_sha256 = cs.sha("different content, same id")
    with pytest.raises(loader.LoadError) as a:
        loader.load_run(conn, plan)
    assert "different content" in a.value.reason
    plan.manifest_sha256 = loader.preflight(run, SALT).manifest_sha256
    plan.run_id = "run_20261004_917"                                       # the same extraction under another id
    with pytest.raises(loader.LoadError) as b:
        loader.load_run(conn, plan)
    assert tables(admin) == before
    assert admin.execute("SELECT count(*) FROM cred.load_rejection").fetchone()[0] == 2
    ev("L10", "second attempt cannot duplicate", identical_repeat="AlreadyLoaded, nothing written", same_id_different_content="refused", same_extraction_other_id="refused", rows_unchanged=True)


# ───────────── L11 / L13 / L14: privileges, identity, secrets ─────────────


def test_l11_loader_cannot_promote_or_purge(dbs, tmp_path):
    conn, admin = dbs
    flow(conn, sealed(tmp_path))
    for sql in ("SELECT cred.promote_run('run_20261004_901','x')", "SELECT cred.demote_to('run_20261004_901','x')", "SELECT cred.purge_run('run_20261004_901','x')",
                "SELECT cred.set_policy(false,false,'x')", "UPDATE cred.run SET recon_state='ui_verified'", "DELETE FROM cred.open_item", "UPDATE cred.open_item SET pending=pending"):
        with pytest.raises(E.InsufficientPrivilege):
            conn.execute(sql)
    src = (HERE.parent / "loader.py").read_text(encoding="utf-8")
    assert not re.search(r"\b(promote_run|demote_to|purge_run|set_policy|api_verify_run|ui_verify_run)\b", src)
    assert tables(admin)["live_run"] == 0
    ev("L11", "loader cannot promote or purge", database="permission denied for promote, demote, purge, policy, update, delete", source_code="no reference to any owner/promoter/verifier function")


def test_l13_loader_identity_is_enforced_and_a_login_member_works(dbs, tmp_path):
    conn, admin = dbs
    admin.execute("CREATE ROLE loader_login LOGIN IN ROLE cred_loader")
    admin.execute("CREATE ROLE greedy_login LOGIN IN ROLE cred_loader, cred_api_reader")
    results = {}
    for who, ok in (("cred_loader", True), ("loader_login", True), ("cred_owner", False), ("cred_promoter", False), ("cred_verifier", False), ("cred_api_reader", False),
                    ("cred_finance_reader", False), ("greedy_login", False)):
        admin.execute("RESET ROLE")
        admin.execute(f"SET ROLE {who}")
        if ok:
            results[who] = loader.assert_loader_identity(admin)
        else:
            with pytest.raises(loader.LoadError):
                loader.assert_loader_identity(admin)
            results[who] = "refused"
    admin.execute("RESET ROLE")
    with pytest.raises(loader.LoadError):
        loader.assert_loader_identity(admin)                                # the superuser session itself
    results["superuser_postgres"] = "refused"
    # a real login that is only a member of cred_loader can run the whole load
    admin.execute("SET ROLE loader_login")
    res = flow(admin, sealed(tmp_path, "run_20261004_918"))
    admin.execute("RESET ROLE")
    assert res["loaded_by"] == "loader_login" and res["recon_state"] == "loaded"
    ev("L13", "loader identity enforced", results=results, login_member_of_cred_loader_loads="yes")


def test_l14_secrets_come_from_the_environment_or_a_git_ignored_file(tmp_path, monkeypatch):
    env = tmp_path / "cred_loader.env"
    env.write_text("host=db.example\nport=5433\ndbname=fpa_pilot\nuser=loader_login\npassword=pw:with@odd/chars\nvendor_ref_salt=" + SALT + "\n", encoding="utf-8")
    monkeypatch.setenv("FPA_CRED_LOADER_ENV", str(env))
    monkeypatch.delenv("FPA_CRED_LOADER_URL", raising=False)
    monkeypatch.delenv("FPA_VENDOR_REF_SALT", raising=False)
    from psycopg.conninfo import conninfo_to_dict

    d = conninfo_to_dict(loader.loader_conninfo())
    assert d["user"] == "loader_login" and d["password"] == "pw:with@odd/chars" and d["dbname"] == "fpa_pilot" and d["port"] == "5433"
    assert loader.vendor_ref_salt() == SALT
    monkeypatch.setenv("FPA_VENDOR_REF_SALT", "too short")
    with pytest.raises(loader.LoadError):
        loader.vendor_ref_salt()
    ref = loader.vendor_ref(SALT, "S1")
    assert re.fullmatch(r"V[0-9a-f]{12}", ref) and ref == loader.vendor_ref(SALT, "S1") and ref != loader.vendor_ref(SALT + "x", "S1") and ref != loader.vendor_ref(SALT, "S2")
    assert ".secrets/" in (ROOT.parent / ".gitignore").read_text(encoding="utf-8")
    src = (HERE.parent / "loader.py").read_text(encoding="utf-8")
    assert "print(info" not in src and "log.info(info" not in src and not re.search(r"(password|passwd)\s*=\s*['\"][^'\"]+['\"]", src)
    ev("L14", "secrets handling", sources="FPA_CRED_LOADER_URL, git-ignored .secrets/cred_loader.env, or a hidden prompt", awkward_password_ok=True, salt_min_length=16, pseudonym_stable_and_key_dependent=True,
       gitignore_has_secrets_dir=True)


def test_l14b_vendor_pseudonym_key_must_not_change_between_runs(dbs, tmp_path):
    conn, admin = dbs
    flow(conn, sealed(tmp_path, "run_20261004_919"))
    (tmp_path / "n").mkdir()
    run2 = sealed(tmp_path / "n", "run_20261004_920")
    ok = loader.load_run(conn, loader.preflight(run2, SALT))
    assert ok["recon_state"] == "loaded"                                    # same key, a second immutable run
    (tmp_path / "m").mkdir()
    run3 = sealed(tmp_path / "m", "run_20261004_921")
    with pytest.raises(loader.LoadError) as e:
        loader.load_run(conn, loader.preflight(run3, SALT + "-changed"))
    assert e.value.failed == {"vendor_ref_drift": 7}
    assert tables(admin)["run"] == 2
    ev("L14b", "pseudonym key drift refused", second_run_same_key="loaded", changed_key=e.value.failed, run_left_behind=False)


# ───────────── L12: no vendor data in logs, reports or rejections ─────────────


def test_l12_no_vendor_names_or_codes_in_logs_reports_or_rejections(dbs, tmp_path, caplog):
    conn, admin = dbs
    caplog.set_level(logging.DEBUG)
    res = flow(conn, sealed(tmp_path, "run_20261004_922"))
    (tmp_path / "f").mkdir()
    plan = loader.preflight(sealed(tmp_path / "f", "run_20261004_923"), SALT)
    plan.items.append(dict(plan.items[3]))                                   # a failing load, whose PostgreSQL error carries row values in its DETAIL
    with pytest.raises(loader.LoadError) as e:
        loader.load_run(conn, plan)
    report = loader.render_report(res)
    rejections = json.dumps(admin.execute("SELECT * FROM cred.load_rejection").fetchall(), default=str)
    corpus = {"log": caplog.text, "report": report, "summary": json.dumps(res, default=str), "rejection_table": rejections, "error": str(e.value)}
    leaks = {k: [s for s in SENTINELS if s in v] for k, v in corpus.items()}
    assert not any(leaks.values()), leaks
    assert "run_20261004_922" in caplog.text and "loaded" in caplog.text                 # logs still say what happened: run ids, counts, states
    ev("L12", "no vendor data in logs, reports or rejections", surfaces_checked=sorted(corpus), sentinels_checked=len(SENTINELS), leaks="none", log_lines_kept=len(caplog.records))


# ───────────── L16: one-command provisioning of the loader login ─────────────


def test_l16_setup_loader_creates_a_restricted_login_and_replaces_a_weak_password(dbs, tmp_path, cluster, monkeypatch, capsys, caplog):
    import setup_loader

    conn, admin = dbs
    caplog.set_level(logging.DEBUG)
    # the situation we are really in: the role already exists with a guessable password typed into a command line
    admin.execute("CREATE ROLE cred_loader_login LOGIN PASSWORD 'choose-your-own' IN ROLE cred_loader")
    weak_hash = admin.execute("SELECT rolpassword FROM pg_authid WHERE rolname = 'cred_loader_login'").fetchone()[0]
    secret = tmp_path / ".secrets" / "cred_loader.env"
    dbname = admin.execute("SELECT current_database()").fetchone()[0]
    facts = setup_loader.provision(admin, secret, "127.0.0.1", str(cluster.port), dbname)
    cfg = setup_loader.read_env(secret)
    new_hash = admin.execute("SELECT rolpassword FROM pg_authid WHERE rolname = 'cred_loader_login'").fetchone()[0]
    assert facts["rekeyed"] and not facts["created"] and new_hash.startswith("SCRAM-SHA-256$") and new_hash != weak_hash
    assert set(cfg) == {"host", "port", "dbname", "user", "password", "vendor_ref_salt"} and cfg["user"] == "cred_loader_login"
    assert len(cfg["password"]) >= 40 and len(cfg["vendor_ref_salt"]) >= 64 and cfg["password"] != "choose-your-own"
    checks = setup_loader.check_role(admin)
    assert all(ok for _, ok in checks), [n for n, ok in checks if not ok]
    # logging in as the account (same path the loader uses): everything outside loading is refused
    monkeypatch.setenv("FPA_CRED_LOADER_ENV", str(secret))
    monkeypatch.delenv("FPA_CRED_LOADER_URL", raising=False)
    monkeypatch.delenv("FPA_VENDOR_REF_SALT", raising=False)
    info = loader.loader_conninfo()
    login_checks = setup_loader.check_login(info)
    assert all(ok for _, ok in login_checks), [n for n, ok in login_checks if not ok]
    # and the real path works end to end: a load through that login, with the key from the file
    with psycopg.connect(info, autocommit=True) as c:
        res = loader.load_run(c, loader.preflight(sealed(tmp_path, "run_20261004_930"), loader.vendor_ref_salt()))
    assert res["loaded_by"] == "cred_loader_login" and (res["recon_state"], res["publication_state"]) == ("loaded", "unpublished")
    # re-running keeps the pseudonym key (a new key would change every vendor_ref) and replaces only the password
    first_salt, first_pw = cfg["vendor_ref_salt"], cfg["password"]
    facts2 = setup_loader.provision(admin, secret, "127.0.0.1", str(cluster.port), dbname)
    cfg2 = setup_loader.read_env(secret)
    assert facts2["salt_kept"] and cfg2["vendor_ref_salt"] == first_salt and cfg2["password"] != first_pw
    # an account that is not an administrator is refused and nothing changes
    admin.execute("RESET ROLE")
    admin.execute("SET ROLE cred_loader")
    with pytest.raises(SystemExit):
        setup_loader.provision(admin, tmp_path / "other.env", "127.0.0.1", "5432", dbname)
    admin.execute("RESET ROLE")
    assert not (tmp_path / "other.env").exists()
    # no secret ever reaches the output or the logs
    seen = capsys.readouterr().out + caplog.text
    for value in (first_pw, cfg2["password"], first_salt):
        assert value not in seen
    ev("L16", "setup_loader provisioning", replaced_weak_password=True, hash_scheme="SCRAM-SHA-256", role_checks=len(checks), login_refusals=len(login_checks), end_to_end_load_through_the_login="loaded / unpublished",
       rerun="keeps the pseudonym key, replaces only the password", non_admin="refused, nothing written", secrets_in_output="none")


# ───────────── evidence ─────────────


def write_evidence():
    EVIDENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    order = sorted(EVIDENCE, key=lambda e: e["id"])
    lines = ["# Creditors loader: offline UAT evidence", "",
             "Generated by `tools/creditors_mart/tests/test_cred_loader.py` against a private, temporary PostgreSQL instance (removed afterwards), with synthetic runs only.",
             "`fpa_pilot`, the application database, Oracle and every real run were untouched; `run_20261004_006` was not loaded anywhere.", "",
             "| Item | Result |", "|---|---|"]
    lines += [f"| {e['id']} | {e['title']}: PASS |" for e in order]
    lines.append("")
    for e in order:
        lines += [f"## {e['id']}: {e['title']}", "```json", json.dumps(e["detail"], indent=2, default=str, ensure_ascii=False), "```", ""]
    EVIDENCE_FILE.write_text("\n".join(lines), encoding="utf-8")
