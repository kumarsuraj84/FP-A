"""Exception Inbox over HTTP against the real app database (one rolled-back connection) and, for detection, the real gold_fpa. Skipped without fpa_app."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.appdb.conn import app_connection
from app.auth import router as auth_router
from app.auth import service as auth
from app.inbox import router as inbox_router
from app.inbox import service as svc

try:
    _c = app_connection()
    _c.close()
    HAVE_DB = True
except Exception:  # noqa: BLE001
    HAVE_DB = False
pytestmark = pytest.mark.skipif(not HAVE_DB, reason="fpa_app not reachable")
H = {"X-FPA-Request": "1"}
PW = "Correct-Horse-Battery-9"


def gold_db():
    try:
        from app.gold import db as gold
        url = gold.database_url()
        if not url:
            return None
        db = gold.GoldDb(url)
        with db.session("pnl") as g:
            g.execute("SELECT 1").fetchone()
        return db
    except Exception:  # noqa: BLE001
        return None


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
    for mod in (auth, inbox_router):
        monkeypatch.setattr(mod, "app_connection", lambda: s)
    app = FastAPI()
    app.include_router(auth_router.router)
    app.include_router(inbox_router.router)
    app.state.db = gold_db()
    s.execute("UPDATE app_user SET role = 'viewer' WHERE role = 'admin'")      # inside this rolled-back transaction only: a real administrator may exist now
    auth.bootstrap_admin("boss@example.test", "Boss", PW)
    admin = TestClient(app)
    admin.post("/api/v1/auth/login", json={"email": "boss@example.test", "password": PW}, headers=H)

    def person(email, role):
        r = admin.post("/api/v1/auth/admin/users", json={"email": email, "display_name": email, "role": role}, headers=H).json()["data"]
        t = r["temporary_password"]
        c = TestClient(app)
        c.post("/api/v1/auth/login", json={"email": email, "password": t}, headers=H)
        c.post("/api/v1/auth/change-password", json={"current_password": t, "new_password": "A-Fresh-Passphrase-42"}, headers=H)
        c.post("/api/v1/auth/login", json={"email": email, "password": "A-Fresh-Passphrase-42"}, headers=H)
        c.user_id = r["user_id"]
        return c
    try:
        yield {"app": app, "person": person, "db": s}
    finally:
        s.c.rollback()
        s.c.close()


def cand(**kw):
    c = {"exception_type": "LINE_MONTH_MOVE", "domain": "EXPENSE", "entity": "CONSOLIDATED", "metric_id": "rent", "period": date(2031, 4, 1), "subject_key": "rent", "title": "Rent moved 30%",
         "severity": 70, "materiality": 60, "recency": 90, "actionability": 60, "escalated": False, "evidence": {"observed_cr": "1.2"}}
    c.update(kw)
    return c


def test_score_formula_and_persistence():
    assert svc.final_score(70, 60, 90, 60) == D("68.00")                       # 0.35*70 + 0.30*60 + 0.15*90 + 0.20*60
    assert svc.final_score(70, 60, 90, 60, 3) == D("74.80") and svc.final_score(70, 60, 90, 60, 6) == D("85.00")
    assert svc.final_score(100, 100, 100, 100, 6) == D("100.00")
    assert svc.dedupe_key(cand()) == svc.dedupe_key(cand(title="another title")) != svc.dedupe_key(cand(subject_key="employee_cost"))


def test_ingest_dedupes_recurs_and_links_a_new_case_after_close(env):
    db = env["db"]
    r = svc.ingest(db, [cand()])
    assert r["created"] == 1
    r = svc.ingest(db, [cand(severity=90)])
    assert r["recurred"] == 1 and r["created"] == 0
    case = db.execute("SELECT * FROM exception_case WHERE metric_id = 'rent' AND period = '2031-04-01'").fetchone()
    assert case["detection_count"] == 2 and case["status"] == "OPEN"
    rev = env["person"]("rev@example.test", "finance_reviewer")
    assert rev.post(f"/api/v1/exceptions/{case['case_id']}/close", json={"comment": "agreed with finance as seasonal", "closure_reason": "ACCEPTED_RISK"}, headers=H).json()["data"]["status"] == "CLOSED"
    r = svc.ingest(db, [cand()])
    assert r["created"] == 1 and r["recurrence_cases"] == 1
    new = db.execute("SELECT * FROM exception_case WHERE metric_id = 'rent' AND status = 'OPEN'").fetchone()
    assert new["recurrence_no"] == 2 and new["recurrence_of_case_id"] == case["case_id"]
    one = rev.get(f"/api/v1/exceptions/{new['case_id']}").json()["data"]
    assert one["recurring"] is True and len(one["lineage"]) == 1


def test_ranked_list_shows_escalated_first_and_top_20_by_default(env):
    db = env["db"]
    svc.ingest(db, [cand(subject_key=f"s{i}", metric_id=f"m{i}", severity=10 + i, materiality=10 + i) for i in range(25)] + [cand(subject_key="blocker", metric_id="close", severity=20, escalated=True)])
    m = env["person"]("mgr@example.test", "fpa_manager")
    d = m.get("/api/v1/exceptions").json()["data"]
    assert d["shown"] == 20 and d["total"] == 26 and d["items"][0]["subject_key"] == "blocker" and d["items"][0]["band"] == "CRITICAL"
    scores = [float(x["final_score"]) for x in d["items"][1:]]
    assert scores == sorted(scores, reverse=True)
    assert d["unowned"] == 26 and "Uncalibrated" in d["score_note"]
    assert m.get("/api/v1/exceptions", params={"search": "Rent", "limit": 100}).json()["data"]["total"] == 26


def test_assign_work_resolve_and_only_a_reviewer_closes(env):
    db = env["db"]
    svc.ingest(db, [cand()])
    cid = str(db.execute("SELECT case_id FROM exception_case").fetchone()["case_id"])
    mgr, own, rev = env["person"]("mgr2@example.test", "fpa_manager"), env["person"]("own@example.test", "fpa_manager"), env["person"]("rev2@example.test", "finance_reviewer")
    soon = (date.today() + timedelta(days=5)).isoformat()
    a = mgr.post(f"/api/v1/exceptions/{cid}/assign", json={"owner_user_id": own.user_id, "due_date": soon, "next_action": "check the rent invoices"}, headers=H).json()["data"]
    assert a["owner_user_id"] == own.user_id and a["due_date"] == soon and a["next_action"] == "check the rent invoices" and a["overdue"] is False
    assert mgr.post(f"/api/v1/exceptions/{cid}/assign", json={"owner_user_id": own.user_id, "due_date": "2020-01-01"}, headers=H).status_code == 422
    assert own.post(f"/api/v1/exceptions/{cid}/acknowledge", json={}, headers=H).json()["data"]["status"] == "ACKNOWLEDGED"
    assert own.post(f"/api/v1/exceptions/{cid}/resolve", json={"comment": "invoices corrected at source"}, headers=H).json()["data"]["status"] == "RESOLVED"
    db.execute("UPDATE app_setting SET value = 'off' WHERE key = 'single_user_mode'")
    r = own.post(f"/api/v1/exceptions/{cid}/close", json={"comment": "closing my own item now", "closure_reason": "RESOLVED_FIXED"}, headers=H)
    assert r.status_code == 403
    assert rev.post(f"/api/v1/exceptions/{cid}/close", json={"comment": "checked and agreed by finance", "closure_reason": "RESOLVED_FIXED"}, headers=H).json()["data"]["status"] == "CLOSED"
    h = rev.get(f"/api/v1/exceptions/{cid}/history").json()["data"]
    assert [e["event_type"] for e in h] == ["DETECTED", "ASSIGNED", "ACKNOWLEDGED", "RESOLVED", "CLOSED"] and h[0]["actor"] == "system"


def test_viewer_reads_and_comments_only_and_anonymous_reads_nothing(env):
    svc.ingest(env["db"], [cand()])
    cid = str(env["db"].execute("SELECT case_id FROM exception_case").fetchone()["case_id"])
    v = env["person"]("view@example.test", "viewer")
    assert v.get("/api/v1/exceptions").status_code == 200
    assert v.post(f"/api/v1/exceptions/{cid}/acknowledge", json={}, headers=H).status_code == 403
    assert v.post(f"/api/v1/exceptions/{cid}/comment", json={"comment": "a viewer can comment"}, headers=H).status_code == 200
    assert TestClient(env["app"]).get("/api/v1/exceptions").status_code == 401


@pytest.mark.skipif(gold_db() is None, reason="gold_fpa not reachable")
def test_detection_runs_the_detectors_on_real_data_and_is_idempotent(env):
    m = env["person"]("mgr3@example.test", "fpa_manager")
    r = m.post("/api/v1/exceptions/detect", headers=H)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["candidates"] >= 0 and d["errors"] == [], d
    first = m.get("/api/v1/exceptions", params={"limit": 500, "status": "OPEN"}).json()["data"]["total"]
    again = m.post("/api/v1/exceptions/detect", headers=H).json()["data"]
    assert again["created"] == 0
    assert m.get("/api/v1/exceptions", params={"limit": 500, "status": "OPEN"}).json()["data"]["total"] == first


class FakeG:
    """A stand-in for the gold connection: returns canned rows in the order the detector asks for them."""

    def __init__(self, *results):
        self.results = list(results)

    def execute(self, *a, **k):
        rows = self.results.pop(0)
        return type("R", (), {"fetchall": lambda s: rows, "fetchone": lambda s: rows[0] if rows else None})()


def test_creditors_detectors_apply_the_versioned_thresholds_and_never_carry_a_vendor_name():
    from app.inbox import detectors_cc as cc
    from app.inbox.detectors import THRESHOLDS
    D_ = D
    today = date.today()
    rows = [{"vendor_ref": "Vaaa", "cr_open": D_(600_000_000), "dr_open": D_(0), "overdue": D_(500_000_000), "old_cr": D_(0), "over90": D_(0), "due_unavail": D_(0), "oldest_days": 10, "as_of": today},
            {"vendor_ref": "Vbbb", "cr_open": D_(400_000_000), "dr_open": D_(0), "overdue": D_(150_000_000), "old_cr": D_(200_000_000), "over90": D_(0), "due_unavail": D_(0), "oldest_days": 10, "as_of": today},
            {"vendor_ref": "Vccc", "cr_open": D_(0), "dr_open": D_(30_000_000), "overdue": D_(0), "old_cr": D_(0), "over90": D_(0), "due_unavail": D_(0), "oldest_days": 10, "as_of": today}]
    out = cc.creditors(FakeG(rows), THRESHOLDS)
    types = {c["exception_type"] for c in out}
    assert {"CREDITORS_OVERDUE_SHARE", "CREDITORS_OLD_PAYABLE", "CREDITORS_VENDOR_CONCENTRATION", "CREDITORS_DEBIT_BALANCE"} <= types
    conc = [c for c in out if c["exception_type"] == "CREDITORS_VENDOR_CONCENTRATION"]
    assert [c["subject_key"] for c in conc] == ["Vaaa", "Vbbb"]                          # 500 and 150 of 650 overdue pass 15 percent, ranked by size
    assert next(c for c in out if c["exception_type"] == "CREDITORS_DEBIT_BALANCE")["subject_key"] == "Vccc"
    assert all("vendor_name" not in c["evidence"] for c in out)
    quiet = [{"vendor_ref": "Vaaa", "cr_open": D_(600_000_000), "dr_open": D_(0), "overdue": D_(10_000_000), "old_cr": D_(0), "over90": D_(0), "due_unavail": D_(0), "oldest_days": 10, "as_of": today}]
    assert cc.creditors(FakeG(quiet), THRESHOLDS) == []


def test_cash_detectors_flag_stale_data_negative_and_high_till_balances_and_a_bank_control_exception():
    from app.inbox import detectors_cc as cc
    from app.inbox.detectors import THRESHOLDS
    old = date.today() - timedelta(days=5)
    till = [{"site_code": 11, "cumulative_balance": D(-500_000), "unposted_net": D(0), "as_of_date": old}, {"site_code": 12, "cumulative_balance": D(5_000_000), "unposted_net": D(0), "as_of_date": old},
            {"site_code": 13, "cumulative_balance": D(100_000), "unposted_net": D(2_000_000), "as_of_date": old}]
    bank = [{"ledger_name": "A", "prior_year_closing": None, "has_movement": True, "last_posted_date": old - timedelta(days=60), "posted_closing": D(1)},
            {"ledger_name": "B", "prior_year_closing": D(5), "has_movement": True, "last_posted_date": old, "posted_closing": D(1)}]
    out = cc.cash(FakeG(till, [], bank), THRESHOLDS)
    by = {(c["exception_type"], c.get("site_code")): c for c in out}
    assert ("CASH_DATA_STALE", None) in by and by[("CASH_DATA_STALE", None)]["evidence"]["age_days"] == 5
    assert ("CASH_STORE_NEGATIVE", "11") in by and ("CASH_STORE_HIGH", "12") in by and ("CASH_STORE_HIGH", "13") not in by            # a very high balance flags at once
    assert ("CASH_UNPOSTED_GAP", "13") in by
    untied = by[("BANK_UNTIED_OPENING", None)]
    assert untied["domain"] == "CONTROLS" and untied["escalated"] is True and untied["evidence"]["ledgers_without_tied_opening"] == 1           # a control exception, escalated whatever the rupees
    assert by[("BANK_STALE_LEDGER", None)]["evidence"]["stale_ledgers"] == 1
    assert cc.cash(FakeG([], []), THRESHOLDS) == []


def test_debit_balance_wording_is_finance_safe_and_oldest_bill_and_due_unavailable_are_flagged():
    from app.inbox import detectors_cc as cc
    from app.inbox.detectors import THRESHOLDS
    today = date.today()
    base = {"cr_open": D(0), "dr_open": D(0), "overdue": D(0), "old_cr": D(0), "over90": D(0), "due_unavail": D(0), "oldest_days": 10, "as_of": today}
    rows = [{**base, "vendor_ref": "Vdeb", "dr_open": D(40_000_000)}, {**base, "vendor_ref": "Vold", "cr_open": D(60_000_000), "oldest_days": 500},
            {**base, "vendor_ref": "Vnodue", "cr_open": D(500_000_000), "due_unavail": D(300_000_000)}]
    out = cc.creditors(FakeG(rows), THRESHOLDS)
    by = {c["exception_type"]: c for c in out}
    assert by["CREDITORS_DEBIT_BALANCE"]["title"] == "Creditor debit balance: classification pending" and "overpay" not in by["CREDITORS_DEBIT_BALANCE"]["title"].lower()
    assert by["CREDITORS_OLDEST_BILL"]["subject_key"] == "Vold" and by["CREDITORS_OLDEST_BILL"]["evidence"]["oldest_open_bill_days"] == 500
    assert "CREDITORS_DUE_UNAVAILABLE" in by


@pytest.mark.skipif(not HAVE_DB, reason="fpa_app not reachable")
def test_trend_detectors_use_the_platforms_own_snapshots_and_stay_silent_on_the_first_day():
    from app.inbox import detectors_cc as cc
    from app.inbox.detectors import THRESHOLDS
    c = app_connection()
    try:
        d1, d2 = date(2031, 3, 1), date(2031, 3, 2)

        def day(as_of, overdue_a, over90):
            base = {"dr_open": D(0), "old_cr": D(0), "due_unavail": D(0), "oldest_days": 10, "as_of": as_of}
            return [{**base, "vendor_ref": "Va", "cr_open": D(500_000_000), "overdue": D(overdue_a), "over90": D(over90 // 2)}, {**base, "vendor_ref": "Vb", "cr_open": D(500_000_000), "overdue": D(100_000_000), "over90": D(over90 // 2)}]
        first = cc.creditors(FakeG(day(d1, 100_000_000, 100_000_000)), THRESHOLDS, c)
        assert not [x for x in first if x["exception_type"] in ("CREDITORS_AGEING_MIGRATION", "CREDITORS_OVERDUE_RISING", "CREDITORS_CONCENTRATION_RISING")]
        second = {x["exception_type"]: x for x in cc.creditors(FakeG(day(d2, 300_000_000, 250_000_000)), THRESHOLDS, c)}
        assert float(second["CREDITORS_AGEING_MIGRATION"]["evidence"]["over90_share_change_pp"]) == pytest.approx(15.0) and second["CREDITORS_AGEING_MIGRATION"]["evidence"]["over90_change_cr"] == "15.0000"
        assert "CREDITORS_OVERDUE_RISING" in second and second["CREDITORS_CONCENTRATION_RISING"]["subject_key"] == "Va" and float(second["CREDITORS_CONCENTRATION_RISING"]["evidence"]["share_change_pp"]) == pytest.approx(25.0)
        # the same day recorded twice does not duplicate or compare with itself
        assert c.execute("SELECT count(*) AS n FROM metric_snapshot WHERE domain = 'CREDITORS' AND metric = 'aggregate' AND as_of = %s", (d2,)).fetchone()["n"] == 1
        # till cash high for three snapshots in a row flags; two does not
        for k in range(3):
            cd = date(2031, 4, 1 + k)
            till = [{"site_code": 12, "cumulative_balance": D(1_500_000), "unposted_net": D(0), "as_of_date": cd}]
            out = cc.cash(FakeG(till, [], []), THRESHOLDS, c)
            flagged = [x for x in out if x["exception_type"] == "CASH_STORE_HIGH"]
            assert (len(flagged) == 1) == (k == 2)
        import psycopg
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("UPDATE metric_snapshot SET value = '{}'::jsonb")
    finally:
        c.rollback()
        c.close()


def test_every_case_is_stamped_with_the_threshold_version():
    from app.inbox import detectors
    stamped = detectors.stamp([{"exception_type": "X", "evidence": {}}])
    assert stamped[0]["evidence"] == {"threshold_version": detectors.THRESHOLD_VERSION, "calibration_status": "UNCALIBRATED"} and detectors.THRESHOLD_VERSION.endswith("-3")
