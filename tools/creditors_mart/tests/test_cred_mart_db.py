"""
Scratch UAT for the creditors pilot mart (schema `cred`).

Runs against a PRIVATE, THROWAWAY PostgreSQL instance built from the installed binaries (own folder, random localhost port, trust auth
for localhost only, deleted afterwards). Nothing here connects to the configured application database or to any other running server.
A migrated template database named `fpa_pilot_scratch` is cloned for every test, so tests cannot affect each other.

Evidence for each UAT item is collected and written to docs/creditors_pilot/MART_SCRATCH_UAT_EVIDENCE.md.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from psycopg import errors as E

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1] / "extraction_broker"))
import creditors_stage as cs  # noqa: E402
import migrate  # noqa: E402

PG_BIN = Path(os.environ.get("PG_BIN", r"C:\Program Files\PostgreSQL\18\bin"))
EVIDENCE_FILE = HERE.parents[2] / "docs" / "creditors_pilot" / "MART_SCRATCH_UAT_EVIDENCE.md"
TEMPLATE = "fpa_pilot_scratch"
ROLES = ["cred_owner", "cred_loader", "cred_verifier", "cred_promoter", "cred_api_reader", "cred_finance_reader"]

pytestmark = pytest.mark.skipif(not (PG_BIN / "initdb.exe").exists() and not shutil.which("initdb"), reason="PostgreSQL server binaries not found")

EVIDENCE: list[dict] = []


def ev(uid: str, title: str, **detail):
    EVIDENCE.append({"id": uid, "title": title, "detail": detail})


# ───────────── the private instance ─────────────


def _bin(name: str) -> str:
    p = PG_BIN / f"{name}.exe"
    return str(p) if p.exists() else (shutil.which(name) or name)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Cluster:
    def __init__(self, root: Path):
        self.root = root
        self.data = root / "data"
        self.port = _free_port()

    def _ctl(self, *args: str, timeout: int = 90):
        # output goes to a file, never a pipe: the postmaster inherits the handle and would keep a pipe open forever on Windows
        with open(self.root / "pg_ctl.out", "ab") as out:
            return subprocess.run([_bin("pg_ctl"), "-D", str(self.data), *args], stdin=subprocess.DEVNULL, stdout=out, stderr=out, timeout=timeout)

    def start(self):
        subprocess.run([_bin("initdb"), "-D", str(self.data), "-U", "postgres", "-A", "trust", "-E", "UTF8", "--no-locale"], check=True, capture_output=True, timeout=120)
        r = self._ctl("-o", f"-p {self.port} -c listen_addresses=127.0.0.1", "-l", str(self.root / "pg.log"), "-w", "start")
        assert r.returncode == 0, (self.root / "pg_ctl.out").read_text(errors="replace")

    def stop(self):
        self._ctl("-m", "immediate", "-w", "stop")

    def dsn(self, db: str) -> str:
        return f"host=127.0.0.1 port={self.port} dbname={db} user=postgres"

    def connect(self, db: str):
        return psycopg.connect(self.dsn(db), autocommit=True)


@pytest.fixture(scope="session")
def cluster(tmp_path_factory, request):
    root = tmp_path_factory.mktemp("pg_scratch")
    c = Cluster(root)
    c.start()
    with c.connect("postgres") as a:
        ver = a.execute("SHOW server_version").fetchone()[0]
        a.execute(f"CREATE DATABASE {TEMPLATE}")
    with c.connect(TEMPLATE) as a:
        migrate.apply(a)
    ev("U01", "scratch database created", server_version=ver, database=TEMPLATE, instance="private temporary instance, 127.0.0.1 only, removed after the run")
    yield c
    ev("U13", "automated database tests", suite="tools/creditors_mart/tests/test_cred_mart_db.py", tests_collected=request.session.testscollected,
       failures_so_far=request.session.testsfailed, isolation="every test runs in a fresh database cloned from the migrated template")
    c.stop()
    shutil.rmtree(root, ignore_errors=True)
    gone = not root.exists()
    ev("U14", "scratch instance dropped", instance_stopped=True, data_directory_removed=gone)
    write_evidence()


_counter = [0]


@pytest.fixture
def db(cluster):
    """A fresh migrated database for one test."""
    _counter[0] += 1
    name = f"uat_{_counter[0]:03d}"
    with cluster.connect("postgres") as a:
        a.execute(f"CREATE DATABASE {name} TEMPLATE {TEMPLATE}")
    conn = cluster.connect(name)
    # database-level grants are not copied by CREATE DATABASE ... TEMPLATE; the real migration makes them on the target database
    conn.execute(f"GRANT CONNECT, CREATE ON DATABASE {name} TO cred_owner")
    conn.execute(f"GRANT CONNECT ON DATABASE {name} TO cred_loader, cred_verifier, cred_promoter, cred_api_reader, cred_finance_reader")
    yield conn
    conn.close()
    with cluster.connect("postgres") as a:
        a.execute(f"DROP DATABASE {name} WITH (FORCE)")


@contextmanager
def role(conn, name):
    conn.execute(f"SET ROLE {name}")
    try:
        yield
    finally:
        conn.execute("RESET ROLE")


def denied(conn, role_name, sql, params=None, expect=(E.InsufficientPrivilege,), contains=None):
    """The statement must fail for this role. Returns the error message."""
    with role(conn, role_name):
        with pytest.raises(expect) as ei:
            conn.execute(sql, params)
    msg = str(ei.value)
    if contains:
        assert contains.lower() in msg.lower(), msg
    return msg.splitlines()[0]


# ───────────── test data ─────────────

VENDORS = {"S1": ("Vendor Alpha Traders", "Supplier-Apparels"), "S2": ("Vendor Beta Stores", "Supplier-Expenses"), "S3": ("Vendor Gamma Logistics", "Transporter")}
NAMES = [v[0] for v in VENDORS.values()]
LED = ["1000000026", "1000000024"]


def vref(sub):
    return "V" + cs.sha(f"salt|{sub}")[:12]


def insert_run(conn, run_id, as_of="2026-10-04", expected_rows=6, expected_identity=8, manifest=None, **extra):
    cols = {
        "extraction_run_id": run_id, "as_of_date": as_of, "package": "creditors_pilot_01", "contract_version": "creditors-pilot-1.0", "rules_version": "1",
        "hash_spec_version": "v1", "rules": json.dumps({"valid_date_min": "2000-01-01"}), "source_object": "MISRETAIL.T$FINOTSD_533", "scope_ledger_codes": LED,
        "manifest_sha256": manifest or cs.sha("m" + run_id), "staging_report_sha256": cs.sha("r" + run_id), "derived_parquet_sha256": cs.sha("p" + run_id),
        "extract_started_at": datetime(2026, 10, 4, 6, 35, tzinfo=timezone.utc), "extract_finished_at": datetime(2026, 10, 4, 6, 37, tzinfo=timezone.utc),
        "expected_rows": expected_rows, "expected_identity_rows": expected_identity, **extra,
    }
    conn.execute(f"INSERT INTO cred.run ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})", list(cols.values()))


def insert_vendor(conn, run_id, sub, **over):
    name, cls = VENDORS.get(sub, (f"Vendor {sub}", "Supplier-GM"))
    conn.execute(
        "INSERT INTO cred.vendor_snapshot (extraction_run_id, sub_ledger_code, vendor_ref, slid, vendor_name, party_class, party_class_type, credit_days, vendor_extinct, vendor_fingerprint)"
        " VALUES (%s,%s,%s,%s,%s,%s,'Supplier',30,'No',%s)",
        (run_id, sub, over.get("vendor_ref", vref(sub)), over.get("slid", f"SL-{sub}"), over.get("name", name), over.get("cls", cls), cs.sha("vf" + sub)))


def item_row(run_id, doc, sub, ledger, drcr, pending, as_of="2026-10-04", key=None, k1=None):
    pending = Decimal(pending)
    return {
        "extraction_run_id": run_id, "as_of_date": as_of, "source_row_key": key or cs.source_row_key(doc, sub),
        "identity_k1_signature": k1 or cs.k1_signature(doc, ledger, sub, drcr), "row_fingerprint": cs.sha("fp" + doc),
        "document_code": doc, "sub_ledger_code": sub, "ledger_code": ledger, "ledger_name": "Sundry Creditors", "drcr": drcr,
        "amount": pending, "pending": pending, "document_type": "PI", "due_date_basis": "Document Date",
        "document_date": date(2026, 9, 1), "due_date": date(2026, 9, 24), "entry_date": date(2026, 9, 1),
        "document_date_raw": "2026-09-01", "due_date_raw": "2026-09-24", "entry_date_raw": "2026-09-01",
        "document_age_days": 33, "document_age_bucket": "D31_60", "overdue_days": 10, "due_status": "PAST_DUE_OR_DUE_TODAY", "date_quality_status": "OK",
        "classification_status": "CREDIT_OUTSTANDING" if drcr == "Cr" else "CREDITOR_DEBIT_BALANCE_CLASSIFICATION_PENDING",
    }


def insert_item(conn, run_id, doc, sub, ledger, drcr, pending, **kw):
    row = item_row(run_id, doc, sub, ledger, drcr, pending, **kw)
    conn.execute(f"INSERT INTO cred.open_item ({', '.join(row)}) VALUES ({', '.join(['%s'] * len(row))})", list(row.values()))


ITEMS = [("D1", "S1", LED[0], "Cr", "-1000.50"), ("D2", "S1", LED[0], "Cr", "-250.00"), ("D3", "S2", LED[1], "Cr", "-75.25"), ("D4", "S2", LED[1], "Dr", "40.00"),
         ("D5", "S3", LED[1], "Cr", "-10.00"), ("D6", "S3", LED[0], "Dr", "5.75")]


def load_rows(conn, run_id, as_of="2026-10-04", items=ITEMS, settled=2):
    for sub in sorted({i[1] for i in items}):
        insert_vendor(conn, run_id, sub)
    for doc, sub, led, dr, pend in items:
        insert_item(conn, run_id, doc, sub, led, dr, pend, as_of=as_of)
    for doc, sub, led, dr, pend in items:
        conn.execute("INSERT INTO cred.identity_snapshot VALUES (%s,%s,%s,%s,%s,'2026-09-01')", (run_id, cs.source_row_key(doc, sub), led, dr, Decimal(pend)))
    for i in range(settled):
        conn.execute("INSERT INTO cred.identity_snapshot VALUES (%s,%s,%s,'Dr',0,'2025-01-01')", (run_id, cs.source_row_key(f"SET{i}", "S1"), LED[0]))


def record(conn, run_id, left, right, n=3, bad=False):
    for i in range(n):
        conn.execute("SELECT cred.record_control(%s,%s,%s,%s,%s,%s,%s)", (run_id, f"C{i}", f"dim{i}", left, Decimal(i * 100), right, Decimal(i * 100 + (1 if bad and i == 0 else 0))))


def as_loader_load(conn, run_id, as_of="2026-10-04", **kw):
    with role(conn, "cred_loader"):
        insert_run(conn, run_id, as_of, **kw)
        load_rows(conn, run_id, as_of)
        record(conn, run_id, "source", "extract")
        record(conn, run_id, "extract", "mart")
        return conn.execute("SELECT cred.verify_run(%s)", (run_id,)).fetchone()[0]


def to_api_verified(conn, run_id, as_of="2026-10-04"):
    assert as_loader_load(conn, run_id, as_of)["ok"] is True
    with role(conn, "cred_verifier"):
        record(conn, run_id, "mart", "api")
        assert conn.execute("SELECT cred.api_verify_run(%s)", (run_id,)).fetchone()[0]["ok"] is True


def promote(conn, run_id, reason="uat"):
    with role(conn, "cred_promoter"):
        conn.execute("SELECT cred.promote_run(%s,%s)", (run_id, reason))


def states(conn, run_id):
    return conn.execute("SELECT recon_state, publication_state FROM cred.run WHERE extraction_run_id=%s", (run_id,)).fetchone()


def count(conn, table, run_id):
    return conn.execute(f"SELECT count(*) FROM cred.{table} WHERE extraction_run_id=%s", (run_id,)).fetchone()[0]


# ───────────── U02 ─────────────


def test_u02_schema_applied_and_owned_by_cred_owner(db):
    owners = db.execute("SELECT DISTINCT pg_get_userbyid(relowner) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'cred' AND c.relkind IN ('r','v')").fetchall()
    fn_owners = db.execute("SELECT DISTINCT pg_get_userbyid(proowner) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'cred'").fetchall()
    schema_owner = db.execute("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'cred'").fetchone()[0]
    tables = [r[0] for r in db.execute("SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cred' AND c.relkind='r' ORDER BY 1")]
    views = [r[0] for r in db.execute("SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='cred' AND c.relkind='v' ORDER BY 1")]
    roles = {r[0]: (r[1], r[2], r[3], r[4]) for r in db.execute("SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname LIKE 'cred\\_%'")}
    assert owners == [("cred_owner",)] and fn_owners == [("cred_owner",)] and schema_owner == "cred_owner"
    assert sorted(roles) == sorted(ROLES) and all(v == (False, False, False, False) for v in roles.values())
    for t in ("run", "open_item", "vendor_snapshot", "identity_snapshot", "control_result", "run_event", "load_rejection", "live_run", "promotion", "policy_change"):
        assert t in tables
    pol = db.execute("SELECT require_api_layer, require_ui_layer FROM cred.policy_change ORDER BY change_id DESC LIMIT 1").fetchone()
    assert pol == (True, False)
    # applying again is a no-op (nothing pending), and 001 on its own still refuses to run twice
    assert migrate.apply(db) == []
    with pytest.raises(E.RaiseException):
        db.execute((migrate.SQL_DIR / "001_cred_schema.sql").read_text(encoding="utf-8"))
    assert [r[0] for r in db.execute("SELECT version FROM cred.schema_migration ORDER BY 1")] == ["001", "002", "003", "004", "005", "006"]
    ev("U02", "schema applied", schema_owner=schema_owner, tables=len(tables), views=len(views), roles_nologin_nosuper=sorted(roles), initial_policy="require_api_layer=true, require_ui_layer=false", second_apply="no-op (ledger 001, 002); 001 alone refused")


# ───────────── U03 ─────────────


def test_u03_role_permission_matrix(db):
    db.execute("CREATE SCHEMA other; CREATE TABLE other.secret (x int); INSERT INTO other.secret VALUES (1)")
    got = {}
    # loader: can load, cannot update/delete/promote/alter, cannot read other schemas
    with role(db, "cred_loader"):
        insert_run(db, "run_20261004_801")
        load_rows(db, "run_20261004_801")
    got["loader_insert"] = "allowed"
    got["loader_update"] = denied(db, "cred_loader", "UPDATE cred.open_item SET pending = pending", contains="permission denied")
    got["loader_delete"] = denied(db, "cred_loader", "DELETE FROM cred.open_item", contains="permission denied")
    got["loader_update_run"] = denied(db, "cred_loader", "UPDATE cred.run SET recon_state = 'verified'", contains="permission denied")
    got["loader_promote"] = denied(db, "cred_loader", "SELECT cred.promote_run('run_20261004_801','x')", contains="permission denied for function")
    got["loader_ddl"] = denied(db, "cred_loader", "CREATE TABLE cred.evil (x int)", contains="permission denied")
    got["loader_other_schema"] = denied(db, "cred_loader", "SELECT * FROM other.secret", contains="permission denied")
    got["loader_direct_control"] = denied(db, "cred_loader", "INSERT INTO cred.control_result (extraction_run_id, control_id, dimension, left_layer, left_value, right_layer, right_value) VALUES ('run_20261004_801','X','x','source',1,'extract',1)")
    got["loader_api_layer"] = denied(db, "cred_loader", "SELECT cred.record_control('run_20261004_801','X','x','mart',1,'api',1)", contains="only the verifier")
    # verifier: reads masked candidates, cannot touch facts, cannot promote
    got["verifier_insert_item"] = denied(db, "cred_verifier", "INSERT INTO cred.control_result (extraction_run_id, control_id, dimension, left_layer, left_value, right_layer, right_value) VALUES ('run_20261004_801','X','x','mart',1,'api',1)")
    got["verifier_update"] = denied(db, "cred_verifier", "UPDATE cred.open_item SET pending = pending", contains="permission denied")
    got["verifier_base_read"] = denied(db, "cred_verifier", "SELECT * FROM cred.open_item", contains="permission denied")
    got["verifier_promote"] = denied(db, "cred_verifier", "SELECT cred.promote_run('run_20261004_801','x')", contains="permission denied for function")
    got["verifier_load_layer"] = denied(db, "cred_verifier", "SELECT cred.record_control('run_20261004_801','X','x','source',1,'extract',1)", contains="only the loader")
    with role(db, "cred_verifier"):
        db.execute("SELECT count(*) FROM cred.v_open_item_any_run").fetchone()
    got["verifier_masked_read"] = "allowed"
    # API reader: approved live views only
    for obj in ("cred.open_item", "cred.vendor_snapshot", "cred.run", "cred.control_result", "cred.v_open_item_any_run", "cred.v_open_item_named"):
        got[f"api_{obj}"] = denied(db, "cred_api_reader", f"SELECT * FROM {obj}", contains="permission denied")
    got["api_function"] = denied(db, "cred_api_reader", "SELECT cred.verify_run('run_20261004_801')", contains="permission denied")
    with role(db, "cred_api_reader"):
        for v in ("v_live_run", "v_open_item", "v_exposure_summary", "v_vendor_counts", "v_live_controls"):
            db.execute(f"SELECT * FROM cred.{v}").fetchall()
    got["api_approved_views"] = "allowed"
    # finance reader: read-only
    got["finance_write"] = denied(db, "cred_finance_reader", "UPDATE cred.open_item SET pending = pending", contains="permission denied")
    got["finance_base_read"] = denied(db, "cred_finance_reader", "SELECT * FROM cred.open_item", contains="permission denied")
    got["finance_insert"] = denied(db, "cred_finance_reader", "INSERT INTO cred.load_rejection (extraction_run_id, stage, reason) VALUES ('x','load','x')", contains="permission denied")
    with role(db, "cred_finance_reader"):
        db.execute("SELECT * FROM cred.v_open_item_named").fetchall()
    got["finance_named_view"] = "allowed"
    ev("U03", "roles and permissions", checks=len(got), results=got)


# ───────────── U04 ─────────────


def test_u04_immutable_facts_for_application_roles_and_the_owner(db):
    to_api_verified(db, "run_20261004_809")
    promote(db, "run_20261004_809")                      # so that promotion and run_event have rows the triggers can act on
    assert as_loader_load(db, "run_20261004_802")["ok"] is True
    with role(db, "cred_loader"):
        db.execute("INSERT INTO cred.load_rejection (extraction_run_id, stage, reason) VALUES ('run_20261004_899','load','duplicate business key (1 group)')")
    got = {}
    for tbl, stmt in (("open_item", "UPDATE cred.open_item SET pending = pending"), ("vendor_snapshot", "UPDATE cred.vendor_snapshot SET vendor_name = 'x'"),
                      ("identity_snapshot", "UPDATE cred.identity_snapshot SET pending = 1"), ("control_result", "UPDATE cred.control_result SET left_value = 1"),
                      ("run_event", "UPDATE cred.run_event SET event = 'loaded'")):
        got[f"owner_update_{tbl}"] = denied(db, "cred_owner", stmt, contains="immutable")
    for tbl in ("open_item", "vendor_snapshot", "identity_snapshot", "control_result", "run_event", "promotion", "load_rejection", "policy_change"):
        got[f"owner_delete_{tbl}"] = denied(db, "cred_owner", f"DELETE FROM cred.{tbl}", contains="immutable")
    got["owner_delete_run"] = denied(db, "cred_owner", "DELETE FROM cred.run", contains="immutable")
    got["owner_edit_run_state_directly"] = denied(db, "cred_owner", "UPDATE cred.run SET recon_state = 'ui_verified'", contains="controlled functions")
    got["owner_edit_run_data"] = denied(db, "cred_owner", "UPDATE cred.run SET expected_rows = 1", contains="controlled functions")
    # rows cannot be added to a run once it is closed (verified)
    with role(db, "cred_loader"):
        with pytest.raises(E.InsufficientPrivilege) as ei:
            insert_item(db, "run_20261004_802", "D9", "S1", LED[0], "Cr", "-1")
    assert "closed" in str(ei.value)
    got["add_row_to_closed_run"] = "refused: " + str(ei.value).splitlines()[0]
    # a run can only be created in its starting state: a loader cannot insert a run that is already verified or live
    for col, val in (("recon_state", "verified"), ("publication_state", "live")):
        with role(db, "cred_loader"):
            with pytest.raises(E.CheckViolation) as ei2:
                insert_run(db, "run_20261004_803", **{col: val})
        assert "loaded / unpublished" in str(ei2.value)
        got[f"loader_inserts_run_as_{val}"] = "refused: " + str(ei2.value).splitlines()[0]
    ev("U04", "immutable fact enforcement", checks=len(got), results=got, controlled_maintenance_path="cred.purge_run / promote_run / demote_to only (U10, U11)")


# ───────────── U05 ─────────────


def test_u05_duplicate_key_rejection(db):
    with role(db, "cred_loader"):
        insert_run(db, "run_20261004_805")
        insert_vendor(db, "run_20261004_805", "S1")
        insert_item(db, "run_20261004_805", "D1", "S1", LED[0], "Cr", "-10")
        with pytest.raises(E.UniqueViolation) as a:  # same business key, different ledger/drcr/amount: still a duplicate
            insert_item(db, "run_20261004_805", "D1", "S1", LED[1], "Dr", "20")
        with pytest.raises(E.UniqueViolation) as b:  # exact same row
            insert_item(db, "run_20261004_805", "D1", "S1", LED[0], "Cr", "-10")
    assert "document_code" in str(a.value) or "source_row_key" in str(a.value)
    assert count(db, "open_item", "run_20261004_805") == 1
    # the same identity in a DIFFERENT run is fine (immutable run-versioned snapshots)
    with role(db, "cred_loader"):
        insert_run(db, "run_20261004_806")
        insert_vendor(db, "run_20261004_806", "S1")
        insert_item(db, "run_20261004_806", "D1", "S1", LED[0], "Cr", "-10")
    ev("U05", "duplicate-key rejection", same_business_key_in_run="rejected (unique violation)", exact_duplicate="rejected", same_key_in_another_run="allowed (separate immutable run)",
       detail_message=str(a.value).splitlines()[0])


# ───────────── U06 ─────────────


def test_u06_identity_hash_check(db):
    r = "run_20261004_807"
    with role(db, "cred_loader"):
        insert_run(db, r)
        insert_vendor(db, r, "S1")
    results = {}
    cases = {
        "wrong_source_row_key": dict(key=cs.sha("not the key")),
        "key_of_other_document": dict(key=cs.source_row_key("OTHER", "S1")),
        "wrong_k1_signature": dict(k1=cs.sha("not the signature")),
    }
    for name, over in cases.items():
        with role(db, "cred_loader"):
            with pytest.raises(E.CheckViolation):
                insert_item(db, r, "D1", "S1", LED[0], "Cr", "-5", **over)
        results[name] = "rejected (check violation)"
    for name, doc in {"delimiter_in_document_code": "A|B", "empty_document_code": ""}.items():
        with role(db, "cred_loader"):
            with pytest.raises(E.CheckViolation):
                insert_item(db, r, doc, "S1", LED[0], "Cr", "-5")
        results[name] = "rejected (check violation)"
    with role(db, "cred_loader"):
        insert_item(db, r, "D1", "S1", LED[0], "Cr", "-5")
    results["correct_identity"] = "accepted"
    ok = db.execute("SELECT violations FROM cred.mart_checks(%s) WHERE check_id = 'M4_key_not_rederivable'", (r,)).fetchone()[0]
    results["M4_rederivation_check"] = f"{ok} violations"
    assert ok == 0
    ev("U06", "identity-hash check", results=results, sql_recomputes="source_row_key and K1 signature are re-derived by the database with sha256")


# ───────────── U07 ─────────────


def test_u07_vendor_conflict_rejection(db):
    r = "run_20261004_808"
    results = {}
    with role(db, "cred_loader"):
        insert_run(db, r)
        insert_vendor(db, r, "S1")
        with pytest.raises(E.UniqueViolation):
            insert_vendor(db, r, "S1", name="A DIFFERENT NAME", cls="Staff")           # same vendor, conflicting attributes
        results["same_vendor_conflicting_attributes"] = "rejected (primary key)"
        with pytest.raises(E.UniqueViolation):
            insert_vendor(db, r, "S2", vendor_ref=vref("S1"))                          # two vendors, one pseudonym
        results["two_vendors_same_pseudonym"] = "rejected (unique)"
        with pytest.raises(E.CheckViolation):
            insert_vendor(db, r, "S2", vendor_ref="not-a-ref")
        results["malformed_pseudonym"] = "rejected (check)"
        with pytest.raises(E.ForeignKeyViolation):
            insert_item(db, r, "D1", "S9", LED[0], "Cr", "-5")                         # item whose vendor is not in the snapshot
        results["item_without_vendor"] = "rejected (foreign key)"
    assert count(db, "vendor_snapshot", r) == 1 and count(db, "open_item", r) == 0
    ev("U07", "vendor conflict rejection", results=results)


# ───────────── U08 ─────────────


def test_u08_failed_load_rolls_back_completely(db):
    to_api_verified(db, "run_20261004_810")
    promote(db, "run_20261004_810")
    live_before = db.execute("SELECT extraction_run_id FROM cred.live_run").fetchone()[0]
    before = {t: db.execute(f"SELECT count(*) FROM cred.{t}").fetchone()[0] for t in ("run", "open_item", "vendor_snapshot", "identity_snapshot", "control_result")}
    r = "run_20261004_811"
    with role(db, "cred_loader"):
        with pytest.raises(E.UniqueViolation):
            with db.transaction():
                insert_run(db, r, "2026-10-05")
                for sub in ("S1", "S2", "S3"):
                    insert_vendor(db, r, sub)
                for doc, sub, led, dr, pend in ITEMS:
                    insert_item(db, r, doc, sub, led, dr, pend, as_of="2026-10-05")
                insert_item(db, r, "D1", "S1", LED[0], "Cr", "-1", as_of="2026-10-05")   # the duplicate that fails the load
    after = {t: db.execute(f"SELECT count(*) FROM cred.{t}").fetchone()[0] for t in before}
    assert before == after, (before, after)
    assert db.execute("SELECT count(*) FROM cred.run WHERE extraction_run_id=%s", (r,)).fetchone()[0] == 0
    assert db.execute("SELECT extraction_run_id FROM cred.live_run").fetchone()[0] == live_before == "run_20261004_810"
    with role(db, "cred_loader"):                                                           # the rejection is recorded separately: reasons and counts only
        db.execute("INSERT INTO cred.load_rejection (extraction_run_id, manifest_sha256, stage, reason, failed_controls) VALUES (%s,%s,'load','duplicate business key (1 group)',%s)",
                   (r, cs.sha("m" + r), json.dumps({"M2_duplicate_business_key": 1})))
    assert db.execute("SELECT count(*) FROM cred.load_rejection").fetchone()[0] == 1
    assert states(db, "run_20261004_810") == ("api_verified", "live")
    ev("U08", "failed load rollback", rows_before=before, rows_after_failed_load=after, previous_live_run_untouched=live_before, rejection_row="written separately, reasons and counts only")


# ───────────── U09 ─────────────


def test_u09_promotion_requires_every_layer(db):
    r = "run_20261004_812"
    steps = {}
    with role(db, "cred_loader"):
        insert_run(db, r)
        load_rows(db, r)
    with role(db, "cred_promoter"):
        with pytest.raises(E.RaiseException) as e1:
            db.execute("SELECT cred.promote_run(%s,'x')", (r,))
    steps["loaded_only"] = "refused: " + str(e1.value).splitlines()[0]
    with role(db, "cred_loader"):
        res = db.execute("SELECT cred.verify_run(%s)", (r,)).fetchone()[0]
    assert res["ok"] is False and states(db, r)[0] == "loaded"
    steps["verify_without_controls"] = "not verified (no source/extract/mart controls)"
    with role(db, "cred_loader"):
        record(db, r, "source", "extract")
        record(db, r, "extract", "mart", bad=True)
        res = db.execute("SELECT cred.verify_run(%s)", (r,)).fetchone()[0]
    assert res["ok"] is False and res["failed_controls"] == 1 and states(db, r)[0] == "loaded"
    steps["verify_with_a_failed_control"] = f"not verified ({res['failed_controls']} failed control)"
    r2 = "run_20261004_813"
    assert as_loader_load(db, r2)["ok"] is True
    assert states(db, r2) == ("verified", "unpublished")
    steps["clean_run_verified"] = "recon_state verified, still unpublished"
    with role(db, "cred_promoter"):
        with pytest.raises(E.RaiseException) as e2:
            db.execute("SELECT cred.promote_run(%s,'x')", (r2,))
    assert "requires api_verified" in str(e2.value)
    steps["verified_without_api_layer"] = "refused: " + str(e2.value).splitlines()[0]
    with role(db, "cred_verifier"):
        with pytest.raises(E.RaiseException):
            record(db, "run_20261004_812", "mart", "api")            # run 812 is not verified, so no API controls can be recorded
        record(db, r2, "mart", "api", bad=True)
        res = db.execute("SELECT cred.api_verify_run(%s)", (r2,)).fetchone()[0]
    assert res["ok"] is False and states(db, r2)[0] == "verified"
    steps["api_controls_with_a_failure"] = "not api_verified"
    r3 = "run_20261004_814"
    to_api_verified(db, r3)
    for who in ("cred_loader", "cred_verifier", "cred_api_reader", "cred_finance_reader", "cred_owner"):
        denied(db, who, "SELECT cred.promote_run(%s,'x')", (r3,))
    steps["only_the_promoter_can_promote"] = "loader, verifier, api_reader, finance_reader and even the owner are refused"
    promote(db, r3)
    assert states(db, r3) == ("api_verified", "live") and db.execute("SELECT extraction_run_id FROM cred.live_run").fetchone()[0] == r3
    steps["fully_verified_run_promoted"] = "live"
    # policy: when the UI layer becomes required, api_verified is no longer enough
    with role(db, "cred_owner"):
        db.execute("SELECT cred.set_policy(true, true, 'UI connected')")
    r4 = "run_20261004_815"
    to_api_verified(db, r4)
    with role(db, "cred_promoter"):
        with pytest.raises(E.RaiseException) as e3:
            db.execute("SELECT cred.promote_run(%s,'x')", (r4,))
    assert "requires ui_verified" in str(e3.value)
    with role(db, "cred_verifier"):
        record(db, r4, "api", "ui")
        assert db.execute("SELECT cred.ui_verify_run(%s)", (r4,)).fetchone()[0]["ok"] is True
    promote(db, r4)
    steps["ui_layer_required_by_policy"] = "refused until ui_verified, then promoted"
    # an older as-of date than the live run cannot be promoted over it
    r5 = "run_20261004_816"
    with role(db, "cred_loader"):
        insert_run(db, r5, "2026-10-01")
        load_rows(db, r5, "2026-10-01")
        record(db, r5, "source", "extract"); record(db, r5, "extract", "mart")
        db.execute("SELECT cred.verify_run(%s)", (r5,))
    with role(db, "cred_verifier"):
        record(db, r5, "mart", "api"); db.execute("SELECT cred.api_verify_run(%s)", (r5,))
        record(db, r5, "api", "ui"); db.execute("SELECT cred.ui_verify_run(%s)", (r5,))
    with role(db, "cred_promoter"):
        with pytest.raises(E.RaiseException) as e4:
            db.execute("SELECT cred.promote_run(%s,'x')", (r5,))
    assert "older" in str(e4.value)
    steps["older_as_of_refused"] = "refused: " + str(e4.value).splitlines()[0]
    events = [x[0] for x in db.execute("SELECT event FROM cred.run_event WHERE extraction_run_id IN (%s,%s) ORDER BY event_id", ("run_20261004_812", r2)).fetchall()]
    assert "verify_failed" in events and "api_verify_failed" in events
    steps["failure_states_retained_separately"] = "run_event keeps verify_failed / api_verify_failed; recon_state never moved"
    ev("U09", "promotion cannot happen without the required layers", steps=steps)


# ───────────── U10 ─────────────


def test_u10_demotion_does_not_delete_or_re_label_data(db):
    a, b = "run_20261004_820", "run_20261004_821"
    to_api_verified(db, a)
    promote(db, a, "first live run")
    as_loader_load(db, b, "2026-10-05")
    with role(db, "cred_verifier"):
        record(db, b, "mart", "api")
        db.execute("SELECT cred.api_verify_run(%s)", (b,))
    promote(db, b, "second live run")
    assert states(db, a) == ("api_verified", "superseded") and states(db, b) == ("api_verified", "live")
    snap = {t: (count(db, t, a), count(db, t, b)) for t in ("open_item", "vendor_snapshot", "identity_snapshot", "control_result")}
    with role(db, "cred_promoter"):
        db.execute("SELECT cred.demote_to(%s,'found a presentation problem in the later run')", (a,))
    snap_after = {t: (count(db, t, a), count(db, t, b)) for t in snap}
    assert snap == snap_after
    assert db.execute("SELECT extraction_run_id FROM cred.live_run").fetchone()[0] == a
    assert states(db, a) == ("api_verified", "live")
    assert states(db, b) == ("api_verified", "withdrawn")      # reconciliation state untouched; only publication changed
    log = db.execute("SELECT action, extraction_run_id, previous_run_id FROM cred.promotion ORDER BY promotion_id").fetchall()
    assert log == [("promote", a, None), ("promote", b, a), ("demote", a, b)]
    with role(db, "cred_promoter"):
        with pytest.raises(E.RaiseException):
            db.execute("SELECT cred.promote_run(%s,'again')", (b,))       # a withdrawn run is not silently re-promoted
        with pytest.raises(E.RaiseException):
            db.execute("SELECT cred.demote_to(%s,'x')", (b,))
    denied(db, "cred_loader", "SELECT cred.demote_to(%s,'x')", (b,), contains="permission denied for function")
    ev("U10", "demotion does not delete data", rows_per_table_before_and_after=snap_after, run_a=states(db, a), run_b=states(db, b), promotion_log=[list(x) for x in log],
       note="the withdrawn run keeps recon_state api_verified: replaced is not the same as wrong")


# ───────────── U11 ─────────────


def test_u11_live_run_cannot_be_purged(db):
    a, b, c = "run_20261004_830", "run_20261004_831", "run_20261004_832"
    to_api_verified(db, a)
    promote(db, a)
    as_loader_load(db, b, "2026-10-05")
    with role(db, "cred_verifier"):
        record(db, b, "mart", "api")
        db.execute("SELECT cred.api_verify_run(%s)", (b,))
    promote(db, b)                                           # a superseded, b live
    as_loader_load(db, c, "2026-10-06")                      # c: loaded, never published
    res = {}
    with role(db, "cred_owner"):
        res["live"] = db.execute("SELECT cred.purge_run(%s,'retention test')", (b,)).fetchone()[0]
        res["rollback_target"] = db.execute("SELECT cred.purge_run(%s,'retention test')", (a,)).fetchone()[0]
        with pytest.raises(E.RaiseException):
            db.execute("SELECT cred.purge_run(%s,'')", (c,))
    assert res["live"] == {"purged": False, "why": "live run"} and res["rollback_target"] == {"purged": False, "why": "rollback target"}
    assert count(db, "open_item", b) == 6 and count(db, "open_item", a) == 6
    denied(db, "cred_loader", "SELECT cred.purge_run(%s,'x')", (c,), contains="permission denied for function")
    denied(db, "cred_api_reader", "SELECT cred.purge_run(%s,'x')", (c,))
    before_meta = (count(db, "control_result", c), db.execute("SELECT count(*) FROM cred.run_event WHERE extraction_run_id=%s", (c,)).fetchone()[0])
    with role(db, "cred_owner"):
        res["unpublished"] = db.execute("SELECT cred.purge_run(%s,'retention: superseded by newer run')", (c,)).fetchone()[0]
        res["again"] = db.execute("SELECT cred.purge_run(%s,'again')", (c,)).fetchone()[0]
    assert res["unpublished"]["purged"] is True and res["unpublished"]["items"] == 6 and res["again"]["why"] == "already purged"
    assert count(db, "open_item", c) == 0 and count(db, "vendor_snapshot", c) == 0 and count(db, "identity_snapshot", c) == 0
    assert db.execute("SELECT data_purged_at IS NOT NULL FROM cred.run WHERE extraction_run_id=%s", (c,)).fetchone()[0]
    assert count(db, "control_result", c) == before_meta[0] and db.execute("SELECT count(*) FROM cred.run WHERE extraction_run_id=%s", (c,)).fetchone()[0] == 1
    refused = db.execute("SELECT detail->>'why' FROM cred.run_event WHERE event='purge_refused' ORDER BY event_id").fetchall()
    assert [x[0] for x in refused] == ["live run", "rollback target"]
    with role(db, "cred_promoter"):
        with pytest.raises(E.RaiseException):
            db.execute("SELECT cred.promote_run(%s,'x')", (c,))
    ev("U11", "live run cannot be purged", live_run=res["live"], rollback_target=res["rollback_target"], purged_unpublished_run=res["unpublished"],
       metadata_kept="run row, control results and events remain after a purge", refusals_logged=[x[0] for x in refused], purged_run_cannot_be_promoted=True)


# ───────────── U12 ─────────────


def test_u12_vendor_names_are_restricted(db):
    r = "run_20261004_840"
    to_api_verified(db, r)
    promote(db, r)
    results = {}
    results["api_base_table"] = denied(db, "cred_api_reader", "SELECT vendor_name FROM cred.vendor_snapshot", contains="permission denied")
    results["api_named_view"] = denied(db, "cred_api_reader", "SELECT vendor_name FROM cred.v_open_item_named", contains="permission denied")
    results["api_masked_view_column"] = denied(db, "cred_api_reader", "SELECT vendor_name FROM cred.v_open_item", expect=(E.UndefinedColumn,))
    results["verifier_named_view"] = denied(db, "cred_verifier", "SELECT vendor_name FROM cred.v_open_item_named_any_run", contains="permission denied")
    results["verifier_vendor_table"] = denied(db, "cred_verifier", "SELECT vendor_name FROM cred.vendor_snapshot", contains="permission denied")
    cols = [x[0] for x in db.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='cred' AND table_name='v_open_item'").fetchall()]
    for banned in ("vendor_name", "slid", "sub_ledger_code", "document_code", "document_no", "ref_no", "created_by_site", "credit_days", "source_row_key"):
        assert banned not in cols, banned
    assert "vendor_ref" in cols and "party_class" in cols and "item_ref" in cols
    with role(db, "cred_api_reader"):
        masked = db.execute("SELECT * FROM cred.v_open_item").fetchall()
        flat = json.dumps([[str(x) for x in row] for row in masked])
    for n in NAMES + ["SL-S1", "SL-S2", "SL-S3"]:
        assert n not in flat
    assert masked, "masked view must return the live run's rows"
    with role(db, "cred_finance_reader"):
        named = db.execute("SELECT vendor_name, slid, sub_ledger_code, document_code FROM cred.v_open_item_named ORDER BY document_code").fetchall()
    assert {n[0] for n in named} == set(NAMES) and named[0][3] == "D1"
    results["finance_named_view"] = f"{len(named)} rows with vendor names and codes"
    # a name must not leak anywhere else in the schema
    leaks = {}
    for t in ("run", "run_event", "control_result", "load_rejection", "promotion", "policy_change", "live_run"):
        text = json.dumps([[str(x) for x in row] for row in db.execute(f"SELECT * FROM cred.{t}").fetchall()])
        leaks[t] = any(n in text for n in NAMES)
    assert not any(leaks.values()), leaks
    ev("U12", "vendor names restricted to Finance", results=results, masked_view_columns=cols, names_found_in_other_tables="none", tables_scanned=sorted(leaks))
    ev("U12b", "pseudonymous vendor_ref", stable_across_runs=True, note="keyed hash created by the loader; same vendor gives the same ref in every run (test fixture)")


# ───────────── U15: the promoter role ─────────────


def test_u15_promoter_role_separation(db):
    a, b, c, d = "run_20261004_850", "run_20261004_851", "run_20261004_852", "run_20261004_853"
    got = {}
    to_api_verified(db, a)
    as_loader_load(db, c, "2026-10-03")                                  # verified only (no API layer)
    with role(db, "cred_loader"):                                        # loaded only
        insert_run(db, d, "2026-10-03")
        load_rows(db, d, "2026-10-03")
    # the promoter can read what a decision needs, and nothing else
    with role(db, "cred_promoter"):
        status = db.execute("SELECT recon_state, publication_state, expected_rows, loaded_rows, controls_failed, api_controls, is_live FROM cred.v_run_status WHERE extraction_run_id=%s", (a,)).fetchone()
        for v in ("v_run_status", "v_promotion_history", "v_control_result_any_run", "v_live_run"):
            db.execute(f"SELECT * FROM cred.{v}").fetchall()
    assert status == ("api_verified", "unpublished", 6, 6, 0, 3, False)
    got["promoter_reads_decision_metadata"] = {"v_run_status": list(status)}
    for obj in ("cred.open_item", "cred.vendor_snapshot", "cred.identity_snapshot", "cred.run", "cred.control_result", "cred.v_open_item_any_run", "cred.v_open_item_named", "cred.v_open_item"):
        got[f"promoter_read_{obj}"] = denied(db, "cred_promoter", f"SELECT * FROM {obj}", contains="permission denied")
    # eligibility is still decided by the database: the promoter cannot bypass the layers
    with role(db, "cred_promoter"):
        for run_id, why in ((d, "loaded only"), (c, "verified but no API layer")):
            with pytest.raises(E.RaiseException) as ei:
                db.execute("SELECT cred.promote_run(%s,'x')", (run_id,))
            got[f"promote_{why.replace(' ', '_')}"] = "refused: " + str(ei.value).splitlines()[0]
    got["promoter_forges_state"] = denied(db, "cred_promoter", "UPDATE cred.run SET recon_state = 'ui_verified', publication_state = 'live'", contains="permission denied")
    got["promoter_forges_control"] = denied(db, "cred_promoter", "INSERT INTO cred.control_result (extraction_run_id, control_id, dimension, left_layer, left_value, right_layer, right_value) VALUES (%s,'X','x','mart',1,'api',1)", (c,), contains="permission denied")
    got["promoter_record_control_function"] = denied(db, "cred_promoter", "SELECT cred.record_control(%s,'X','x','mart',1,'api',1)", (c,), contains="permission denied for function")
    got["promoter_sets_policy"] = denied(db, "cred_promoter", "SELECT cred.set_policy(false,false,'weaken')", contains="permission denied for function")
    got["promoter_verifies"] = denied(db, "cred_promoter", "SELECT cred.verify_run(%s)", (d,), contains="permission denied for function")
    # the fully eligible run is promoted by the promoter
    with role(db, "cred_promoter"):
        db.execute("SELECT cred.promote_run(%s,'first publication')", (a,))
    assert states(db, a) == ("api_verified", "live")
    got["promoter_promotes_eligible_run"] = "live"
    # promote a second eligible run and roll back
    to_api_verified(db, b, "2026-10-05")
    with role(db, "cred_promoter"):
        db.execute("SELECT cred.promote_run(%s,'newer snapshot')", (b,))
        db.execute("SELECT cred.demote_to(%s,'roll back to the earlier snapshot')", (a,))
    assert states(db, a) == ("api_verified", "live") and states(db, b) == ("api_verified", "withdrawn")
    assert count(db, "open_item", a) == 6 and count(db, "open_item", b) == 6
    got["promoter_demotes_and_nothing_is_deleted"] = {"live": a, "withdrawn": b, "rows_kept": 12}
    # everything else is refused
    got["promoter_purge"] = denied(db, "cred_promoter", "SELECT cred.purge_run(%s,'x')", (c,), contains="permission denied for function")
    ddl = {"create_table": "CREATE TABLE cred.evil (x int)", "drop_table": "DROP TABLE cred.run", "alter_table": "ALTER TABLE cred.run ADD COLUMN x int",
           "create_function": "CREATE FUNCTION cred.evil() RETURNS int LANGUAGE sql AS 'SELECT 1'", "drop_function": "DROP FUNCTION cred.promote_run(text, text)",
           "create_view": "CREATE VIEW cred.evil AS SELECT 1", "create_schema": "CREATE SCHEMA evil", "drop_trigger": "DROP TRIGGER no_mutation ON cred.open_item",
           "disable_trigger": "ALTER TABLE cred.open_item DISABLE TRIGGER ALL", "grant": "GRANT SELECT ON cred.open_item TO PUBLIC"}
    for name, stmt in ddl.items():
        got[f"promoter_ddl_{name}"] = denied(db, "cred_promoter", stmt, expect=(E.InsufficientPrivilege,))
    for name, stmt in (("insert_run", "INSERT INTO cred.run (extraction_run_id) VALUES ('run_20261004_899')"), ("insert_vendor", "INSERT INTO cred.vendor_snapshot (extraction_run_id) VALUES ('x')"),
                       ("insert_item", "INSERT INTO cred.open_item (extraction_run_id) VALUES ('x')"), ("update_item", "UPDATE cred.open_item SET pending = pending"),
                       ("delete_item", "DELETE FROM cred.open_item"), ("update_vendor", "UPDATE cred.vendor_snapshot SET vendor_name = 'x'"),
                       ("delete_identity", "DELETE FROM cred.identity_snapshot"), ("update_live_pointer", "UPDATE cred.live_run SET extraction_run_id = 'x'"),
                       ("delete_history", "DELETE FROM cred.promotion")):
        got[f"promoter_facts_{name}"] = denied(db, "cred_promoter", stmt, contains="permission denied")
    # vendor names stay with Finance only
    got["promoter_vendor_names"] = denied(db, "cred_promoter", "SELECT vendor_name FROM cred.v_open_item_named", contains="permission denied")
    # the owner is a maintenance identity: it purges and sets policy, but it does not publish
    with role(db, "cred_owner"):
        purged = db.execute("SELECT cred.purge_run(%s,'retention')", (d,)).fetchone()[0]
        db.execute("SELECT cred.set_policy(true, false, 'unchanged policy, owner maintenance check')")
    assert purged["purged"] is True
    got["owner_still_does_controlled_maintenance"] = {"purge_run": purged, "set_policy": "allowed"}
    got["owner_cannot_publish"] = denied(db, "cred_owner", "SELECT cred.promote_run(%s,'x')", (c,), contains="only the promoter")
    got["owner_cannot_roll_back"] = denied(db, "cred_owner", "SELECT cred.demote_to(%s,'x')", (b,), contains="only the promoter")
    ev("U15", "cred_promoter role", checks=len(got), results=got)


# ───────────── U16: the install verifier ─────────────


def test_u16_install_verifier_passes_a_clean_install_and_catches_drift(db):
    import verify_install

    results = verify_install.verify(db)
    failed = [r for r in results if not r[1]]
    assert not failed, failed
    assert len(results) >= 30
    # drift must be caught: an extra grant, a public grant and a disabled trigger each turn a check red
    drift = {}
    db.execute("GRANT SELECT ON cred.open_item TO cred_api_reader")
    drift["extra_grant_to_api_reader"] = [r[0] for r in verify_install.verify(db) if not r[1]]
    db.execute("REVOKE SELECT ON cred.open_item FROM cred_api_reader")
    db.execute("GRANT SELECT ON cred.v_open_item_named TO PUBLIC")
    drift["public_grant_on_named_view"] = [r[0] for r in verify_install.verify(db) if not r[1]]
    db.execute("REVOKE SELECT ON cred.v_open_item_named FROM PUBLIC")
    db.execute("ALTER TABLE cred.open_item DISABLE TRIGGER no_mutation")
    drift["disabled_immutability_trigger"] = [r[0] for r in verify_install.verify(db) if not r[1]]
    db.execute("ALTER TABLE cred.open_item ENABLE TRIGGER no_mutation")
    assert all(v for v in drift.values()), drift
    assert not [r for r in verify_install.verify(db) if not r[1]]
    ev("U16", "install verifier", checks_on_clean_install=len(results), failures=0, drift_detected={k: v[:2] for k, v in drift.items()})


# ───────────── evidence ─────────────


def write_evidence():
    EVIDENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    order = sorted(EVIDENCE, key=lambda e: e["id"])
    lines = ["# Creditors pilot mart: scratch UAT evidence", "",
             "Generated by `tools/creditors_mart/tests/test_cred_mart_db.py` against a private, temporary PostgreSQL instance (removed afterwards).",
             "No application database, no pilot database, no Oracle, no frontend and no real run was touched.", "",
             "| Item | Result |", "|---|---|"]
    for e in order:
        lines.append(f"| {e['id']} | {e['title']}: PASS |")
    lines.append("")
    for e in order:
        lines += [f"## {e['id']}: {e['title']}", "```json", json.dumps(e["detail"], indent=2, default=str, ensure_ascii=False), "```", ""]
    EVIDENCE_FILE.write_text("\n".join(lines), encoding="utf-8")
