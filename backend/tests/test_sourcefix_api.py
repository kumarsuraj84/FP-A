"""Source Fix Candidate queue: the pure ranking and thresholds (no database) and the HTTP flow against the real app database inside one rolled-back transaction."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.appdb.conn import app_connection
from app.auth import router as auth_router
from app.auth import service as auth
from app.sourcefix import router as sf_router
from app.sourcefix import service as svc

try:
    _c = app_connection()
    _c.close()
    HAVE_DB = True
except Exception:  # noqa: BLE001
    HAVE_DB = False
H = {"X-FPA-Request": "1"}
PW = "Correct-Horse-Battery-9"
CR = 10_000_000


def line(req, ledger="L1", frm="02-Employee Cost", to="16-Miscellaneous Expenses", month=date(2026, 5, 1), cm=None, amt=-1_000_000, site="10"):
    return {"source_entity": "RETAIL", "ledger_key": ledger, "original_group": frm, "corrected_group": to, "original_month": month, "corrected_month": cm, "source_amount_snapshot": D(amt), "site_code": site, "request_id": req}


def test_a_recurring_group_reclass_is_ranked_by_recurrence_materiality_and_breadth():
    rows = [line(f"r{i}", month=date(2026, 4 + i % 4, 1), amt=-4_000_000, site=str(10 + i)) for i in range(6)]
    c = svc.derive(rows, [])
    assert len(c) == 1
    x = c[0]
    assert x["issue_type"] == "RECURRING_GROUP_RECLASS" and x["line_count"] == 6 and x["months_affected"] == 4 and x["consecutive_months"] == 4 and x["site_count"] == 6
    assert x["cumulative_amount_cr"] == D("2.4000") and x["from_value"] == "02-Employee Cost" and x["to_value"] == "16-Miscellaneous Expenses" and len(x["origin_ids"]) == 6
    assert x["first_seen"] == date(2026, 4, 1) and x["last_seen"] == date(2026, 7, 1)
    assert 0 < x["score"] <= 100 and "Fix the upstream ledger-to-management-group mapping" in x["recommended_fix"]


def test_below_the_thresholds_nothing_is_raised_and_bigger_patterns_rank_higher():
    assert svc.derive([line("a"), line("b")], []) == []
    small = svc.derive([line(f"s{i}", ledger="S", amt=-300_000) for i in range(5)], [])[0]
    big = svc.derive([line(f"b{i}", ledger="B", month=date(2026, 4 + i % 5, 1), amt=-5_000_000, site=str(i)) for i in range(10)], [])[0]
    assert big["score"] > small["score"]


def test_month_shift_and_mapping_churn_patterns():
    rows = [line(f"m{i}", ledger="M", to=None, cm=date(2026, 5 + i, 1) if False else date(2026, 6 + i % 3, 1), month=date(2026, 5 + i % 3, 1)) for i in range(5)]
    c = svc.derive(rows, [])
    assert c and c[0]["issue_type"] == "RECURRING_MONTH_SHIFT" and c[0]["to_value"] == "+1" and "Capture the expense month" in c[0]["recommended_fix"]
    maps = [{"mapping_id": f"id{v}", "domain": "LEDGER_GROUP", "source_key": "Salary", "mapped_value": f"g{v}", "version": v} for v in (1, 2, 3)]
    m = svc.derive([], maps)
    assert m[0]["issue_type"] == "RECURRING_MAPPING_CHANGE" and m[0]["months_affected"] == 2 and m[0]["origin_ids"] == ["id1", "id2", "id3"]
    assert svc.derive([], maps[:2]) == []


def test_pattern_key_is_stable_and_distinguishes_patterns():
    a = svc.pattern_key("RECURRING_GROUP_RECLASS", "RETAIL", "L1", "x", "y")
    assert a == svc.pattern_key("recurring_group_reclass", "retail", "l1", "X", "Y") != svc.pattern_key("RECURRING_GROUP_RECLASS", "RETAIL", "L1", "x", "z")


pytestmark_db = pytest.mark.skipif(not HAVE_DB, reason="fpa_app not reachable")


class Shared:
    def __init__(self):
        self.c = app_connection()
        self.c.execute("SAVEPOINT sp")

    def execute(self, *a, **k):
        return self.c.execute(*a, **k)

    def commit(self):
        self.c.execute("RELEASE SAVEPOINT sp")
        self.c.execute("SAVEPOINT sp")

    def rollback(self):
        self.c.execute("ROLLBACK TO SAVEPOINT sp")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture()
def env(monkeypatch):
    s = Shared()
    for mod in (auth, sf_router):
        monkeypatch.setattr(mod, "app_connection", lambda: s)
    app = FastAPI()
    app.include_router(auth_router.router)
    app.include_router(sf_router.router)
    s.execute("UPDATE app_user SET role = 'viewer' WHERE role = 'admin'")      # inside this rolled-back transaction only
    auth.bootstrap_admin("boss@example.test", "Boss", PW)
    admin = TestClient(app)
    admin.post("/api/v1/auth/login", json={"email": "boss@example.test", "password": PW}, headers=H)
    uid = s.execute("SELECT user_id FROM app_user WHERE email = 'boss@example.test'").fetchone()["user_id"]

    def person(email, role):
        t = admin.post("/api/v1/auth/admin/users", json={"email": email, "display_name": email, "role": role}, headers=H).json()["data"]["temporary_password"]
        c = TestClient(app)
        c.post("/api/v1/auth/login", json={"email": email, "password": t}, headers=H)
        c.post("/api/v1/auth/change-password", json={"current_password": t, "new_password": "A-Fresh-Passphrase-42"}, headers=H)
        c.post("/api/v1/auth/login", json={"email": email, "password": "A-Fresh-Passphrase-42"}, headers=H)
        return c
    try:
        yield {"admin": admin, "person": person, "db": s, "uid": uid}
    finally:
        s.c.rollback()
        s.c.close()


def active_correction(db, uid, key, month="2026-05-01", site="10", requested_days_ago=0):
    rid = db.execute("INSERT INTO correction_request (scope_type, correction_type, source_entity, reason_code, reason_text, evidence_reference, requested_by, created_by) "
                     "VALUES ('LINE', 'GROUP', 'RETAIL', 'WRONG_CLASSIFICATION', 'booked to the wrong management group', 'ticket', %s, %s) RETURNING request_id", (uid, uid)).fetchone()["request_id"]
    db.execute("INSERT INTO correction_line (request_id, source_entity, source_line_key, fingerprint, source_amount_snapshot, voucher_key, ledger_key, site_code, original_group, corrected_group, original_month) "
               "VALUES (%s, 'RETAIL', %s, %s, -4000000, 'V', 'L77', %s, '02-Employee Cost', '16-Miscellaneous Expenses', %s)", (rid, key, "a" * 64, site, month))
    for et, to in (("CREATED", "DRAFT"), ("SUBMITTED", "SUBMITTED"), ("APPROVED", "APPROVED"), ("ACTIVATED", "ACTIVE")):
        db.execute("INSERT INTO correction_event (request_id, event_type, to_status, actor_user_id, comment) VALUES (%s, %s, %s, %s, NULL)", (rid, et, to, uid))
    if requested_days_ago:
        db.execute("SELECT 1")          # requested_at is the insert time; the validation test moves the fix date instead
    return rid


def seed(db, uid, n=6):
    for i in range(n):
        active_correction(db, uid, f"{9000 + i}", month=f"2026-0{4 + i % 4}-01", site=str(10 + i))


@pytestmark_db
def test_refresh_raises_a_ranked_candidate_with_origin_ids_and_is_idempotent(env):
    seed(env["db"], env["uid"])
    r = env["admin"].post("/api/v1/source-fixes/refresh", headers=H).json()["data"]
    assert r["raised"] >= 1
    lst = env["admin"].get("/api/v1/source-fixes").json()["data"]
    top = next(c for c in lst["items"] if c["subject_key"] == "L77")
    assert top["status"] == "OPEN" and top["line_count"] == 6 and len(top["origin_ids"]) == 6 and top["post_fix_validation"] == "NOT_VALIDATED" and "Advisory only" in lst["advisory"]
    assert lst["calibration_status"] == "UNCALIBRATED" and top["threshold_version"] == svc.THRESHOLD_VERSION
    again = env["admin"].post("/api/v1/source-fixes/refresh", headers=H).json()["data"]
    assert again["raised"] == 0 and again["updated"] >= 1
    assert "Source fix candidates" in env["admin"].get("/api/v1/source-fixes/export").json()["data"]["text"]


@pytestmark_db
def test_the_data_team_records_a_fix_and_the_platform_validates_or_fails_it(env):
    seed(env["db"], env["uid"])
    admin = env["admin"]
    admin.post("/api/v1/source-fixes/refresh", headers=H)
    cid = next(c for c in admin.get("/api/v1/source-fixes").json()["data"]["items"] if c["subject_key"] == "L77")["candidate_id"]
    assert admin.post(f"/api/v1/source-fixes/{cid}/acknowledge", json={}, headers=H).json()["data"]["status"] == "ACKNOWLEDGED"
    assert admin.post(f"/api/v1/source-fixes/{cid}/implemented", json={"fix_date": (date.today() + timedelta(days=3)).isoformat()}, headers=H).status_code == 422
    # a fix dated yesterday: corrections created today are AFTER it, so the pattern is still recurring
    yday = (date.today() - timedelta(days=1)).isoformat()
    r = admin.post(f"/api/v1/source-fixes/{cid}/implemented", json={"fix_date": yday, "comment": "ledger remapped in the extraction layer"}, headers=H).json()["data"]
    assert r["status"] == "FIX_IMPLEMENTED" and r["post_fix_validation"] == "PENDING"
    active_correction(env["db"], env["uid"], "9100", month=date.today().replace(day=1).isoformat())        # the same pattern posted again in the fix month
    res = admin.post("/api/v1/source-fixes/refresh", headers=H).json()["data"]
    assert res["still_recurring"] == 1
    assert admin.get(f"/api/v1/source-fixes/{cid}").json()["data"]["status"] == "STILL_RECURRING" and admin.get(f"/api/v1/source-fixes/{cid}").json()["data"]["post_fix_validation"] == "FAILED"
    hist = admin.get(f"/api/v1/source-fixes/{cid}/history").json()["data"]
    assert [h["event_type"] for h in hist] == ["DETECTED", "ACKNOWLEDGED", "FIX_IMPLEMENTED", "VALIDATION_FAILED"] and hist[-1]["actor"] == "system"


@pytestmark_db
def test_a_fix_with_no_later_correction_over_a_complete_month_is_validated(env):
    db, uid, admin = env["db"], env["uid"], env["admin"]
    seed(db, uid)
    admin.post("/api/v1/source-fixes/refresh", headers=H)
    cid = next(c for c in admin.get("/api/v1/source-fixes").json()["data"]["items"] if c["subject_key"] == "L77")["candidate_id"]
    old = (date.today() - timedelta(days=70)).isoformat()
    admin.post(f"/api/v1/source-fixes/{cid}/implemented", json={"fix_date": old}, headers=H)
    # every seeded line posted in April to July: none in or after the fix month, so nothing came back after the fix and a complete month has passed
    res = admin.post("/api/v1/source-fixes/refresh", headers=H).json()["data"]
    assert res["validated"] == 1 and res["still_recurring"] == 0
    got = admin.get(f"/api/v1/source-fixes/{cid}").json()["data"]
    assert got["status"] == "VALIDATED" and got["post_fix_validation"] == "PASSED"


@pytestmark_db
def test_roles_dismiss_reason_owners_and_no_write_path_to_finance_or_mapping(env):
    seed(env["db"], env["uid"])
    admin = env["admin"]
    admin.post("/api/v1/source-fixes/refresh", headers=H)
    cid = next(c for c in admin.get("/api/v1/source-fixes").json()["data"]["items"] if c["subject_key"] == "L77")["candidate_id"]
    v = env["person"]("view@example.test", "viewer")
    assert v.get("/api/v1/source-fixes").status_code == 200
    assert v.post(f"/api/v1/source-fixes/{cid}/acknowledge", json={}, headers=H).status_code == 403
    assert v.post("/api/v1/source-fixes/refresh", headers=H).status_code == 403
    assert admin.post(f"/api/v1/source-fixes/{cid}/dismiss", json={"comment": "no"}, headers=H).status_code == 422
    o = admin.post(f"/api/v1/source-fixes/{cid}/owners", json={"finance_owner": "FP&A Manager", "data_owner": "Extraction team"}, headers=H).json()["data"]
    assert o["finance_owner"] == "FP&A Manager" and o["data_owner"] == "Extraction team"
    assert admin.post(f"/api/v1/source-fixes/{cid}/dismiss", json={"comment": "it was a one-off migration cleanup"}, headers=H).json()["data"]["status"] == "DISMISSED"
    import psycopg
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        env["db"].execute("UPDATE source_fix_candidate SET status = 'VALIDATED'")
    env["db"].rollback()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        env["db"].execute("UPDATE mapping_rule SET status = 'ACTIVE'")
    env["db"].rollback()
