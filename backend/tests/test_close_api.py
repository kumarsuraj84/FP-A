"""Month-end close over HTTP against the real app database (one rolled-back connection) and, for the shape tests, the real gold_fpa. Skipped without fpa_app."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.appdb.conn import app_connection
from app.auth import router as auth_router
from app.auth import service as auth
from app.close import router as close_router
from app.close import service as svc

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


GOLD = gold_db()


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
    for mod in (auth, close_router):
        monkeypatch.setattr(mod, "app_connection", lambda: s)
    app = FastAPI()
    app.include_router(auth_router.router)
    app.include_router(close_router.router)
    app.state.db = GOLD
    s.execute("UPDATE app_user SET role = 'viewer' WHERE role = 'admin'")      # inside this rolled-back transaction only
    auth.bootstrap_admin("boss@example.test", "Boss", PW)
    admin = TestClient(app)
    admin.post("/api/v1/auth/login", json={"email": "boss@example.test", "password": PW}, headers=H)

    def person(email, role):
        t = admin.post("/api/v1/auth/admin/users", json={"email": email, "display_name": email, "role": role}, headers=H).json()["data"]["temporary_password"]
        c = TestClient(app)
        c.post("/api/v1/auth/login", json={"email": email, "password": t}, headers=H)
        c.post("/api/v1/auth/change-password", json={"current_password": t, "new_password": "A-Fresh-Passphrase-42"}, headers=H)
        c.post("/api/v1/auth/login", json={"email": email, "password": "A-Fresh-Passphrase-42"}, headers=H)
        return c
    try:
        yield {"app": app, "person": person, "db": s, "admin": admin}
    finally:
        s.c.rollback()
        s.c.close()


def clean_gold(entity, m):
    """A deterministic set of data checks for the flow tests: everything loaded and clean, intercompany pending its sign-off."""
    return [svc.chk("revenue_loaded", "PASS", "ok", {"x": 1}), svc.chk("cogs_loaded", "PASS", "ok"), svc.chk("data_controls", "PASS", "ok"), svc.chk("unmapped", "PASS", "ok"),
            svc.chk("intercompany", "PENDING", "review", {"loan_variance_cr": "1"})]


def go(c, url, body=None):
    return c.post("/api/v1/close" + url, json=body or {}, headers=H)


@pytest.mark.skipif(GOLD is None, reason="gold_fpa not reachable")
def test_readiness_of_a_complete_month_has_the_whole_checklist_in_order(env):
    m = env["person"]("mgr@example.test", "fpa_manager")
    d = m.get("/api/v1/close/readiness", params={"entity": "SUBCO", "month": "2026-08"}).json()["data"]
    assert [c["key"] for c in d["checks"]] == svc.ORDER
    by = {c["key"]: c for c in d["checks"]}
    assert by["revenue_loaded"]["status"] == "PASS" and by["pnl_certification"]["status"] == "PENDING" and by["intercompany"]["status"] in ("PENDING", "BLOCKED")
    assert d["period_status"] == "OPEN" and d["outcome"] in ("NEEDS_ATTENTION", "BLOCKED") and 0 <= d["readiness_pct"] < 100
    h = m.get("/api/v1/close/readiness", params={"entity": "HOLDCO", "month": "2026-08"}).json()["data"]
    assert {c["key"]: c for c in h["checks"]}["revenue_loaded"]["status"] == "NA"


@pytest.mark.skipif(GOLD is None, reason="gold_fpa not reachable")
def test_the_partial_current_month_is_blocked_and_cannot_be_soft_closed(env):
    m = env["person"]("mgr2@example.test", "fpa_manager")
    d = m.get("/api/v1/close/readiness", params={"entity": "SUBCO", "month": "2026-10"}).json()["data"]
    rev = next(c for c in d["checks"] if c["key"] == "revenue_loaded")
    assert rev["status"] == "BLOCKED" and "not complete" in rev["summary"] and d["outcome"] == "BLOCKED" and d["management_pnl"] == "PROVISIONAL"
    assert go(m, "/period/soft-close", {"entity": "SUBCO", "month": "2026-10", "reason": "closing the month early"}).status_code == 409
    assert go(m, "/signoff", {"entity": "SUBCO", "month": "2026-10", "check_key": "revenue_loaded", "decision": "OVERRIDDEN", "comment": "override the blocker please"}).status_code == 409


def test_full_close_flow_with_signoff_stale_evidence_and_roles(env, monkeypatch):
    monkeypatch.setattr(svc, "gold_checks", lambda g, e, m: clean_gold(e, m))
    mgr, rev = env["person"]("mgr3@example.test", "fpa_manager"), env["person"]("rev@example.test", "finance_reviewer")
    ctl = env["admin"]
    body = {"entity": "SUBCO", "month": "2020-05"}
    r = mgr.get("/api/v1/close/readiness", params=body).json()["data"]
    assert r["outcome"] == "NEEDS_ATTENTION" and r["can_management_close"] is False
    assert go(mgr, "/period/soft-close", {**body, "reason": "month complete and reviewed"}).json()["data"]["period_status"] == "SOFT_CLOSED"
    assert go(mgr, "/period/management-close", {**body, "reason": "closing for management"}).status_code == 409          # intercompany not signed off
    db = env["db"]
    db.execute("UPDATE app_setting SET value = 'off' WHERE key = 'single_user_mode'")
    assert go(mgr, "/signoff", {**body, "check_key": "intercompany", "decision": "SIGNED_OFF", "comment": "reconciled with HoldCo ledger"}).status_code == 403      # a manager is not a reviewer
    assert go(rev, "/signoff", {**body, "check_key": "intercompany", "decision": "SIGNED_OFF", "comment": "reconciled with HoldCo ledger"}).status_code == 200
    # the evidence changes after the sign-off: the sign-off is stale and the item is open again
    monkeypatch.setattr(svc, "gold_checks", lambda g, e, m: [c if c["key"] != "intercompany" else svc.chk("intercompany", "PENDING", "review", {"loan_variance_cr": "2"}) for c in clean_gold(e, m)])
    stale = rev.get("/api/v1/close/readiness", params=body).json()["data"]
    ic = next(c for c in stale["checks"] if c["key"] == "intercompany")
    assert ic["effective"] == "PENDING" and ic["signoff"]["stale"] is True and stale["can_management_close"] is False
    monkeypatch.setattr(svc, "gold_checks", lambda g, e, m: clean_gold(e, m))
    assert go(rev, "/signoff", {**body, "check_key": "intercompany", "decision": "SIGNED_OFF", "comment": "reconciled again"}).status_code == 200      # fresh sign-off on the current evidence
    assert rev.get("/api/v1/close/readiness", params=body).json()["data"]["can_management_close"] is True
    assert go(mgr, "/period/management-close", {**body, "reason": "closing for management"}).status_code == 403            # needs a reviewer
    assert go(rev, "/period/management-close", {**body, "reason": "closing for management"}).json()["data"]["period_status"] == "MANAGEMENT_CLOSED"
    assert go(rev, "/period/final-close", {**body, "reason": "final close of the month"}).status_code == 409                # certification missing
    assert go(rev, "/signoff", {**body, "check_key": "pnl_certification", "decision": "SIGNED_OFF", "comment": "certified by finance"}).status_code == 403      # controller only
    assert go(ctl, "/signoff", {**body, "check_key": "pnl_certification", "decision": "SIGNED_OFF", "comment": "certified by the controller"}).status_code == 200
    assert go(rev, "/period/final-close", {**body, "reason": "final close of the month"}).status_code == 403                # controller only
    assert go(ctl, "/period/final-close", {**body, "reason": "final close of the month"}).json()["data"]["period_status"] == "FINAL_CLOSED"
    assert go(ctl, "/period/reopen", {**body, "reason": "short"}).status_code == 422
    assert go(rev, "/period/reopen", {**body, "reason": "a late invoice needs booking"}).status_code == 403
    assert go(ctl, "/period/reopen", {**body, "reason": "a late invoice needs booking"}).json()["data"]["period_status"] == "REOPENED"
    hist = rev.get("/api/v1/close/history", params=body).json()["data"]
    assert [h["to_status"] for h in hist] == ["SOFT_CLOSED", "MANAGEMENT_CLOSED", "FINAL_CLOSED", "REOPENED"] and all(h["actor"] for h in hist)


def test_writability_follows_the_period_status(env, monkeypatch):
    monkeypatch.setattr(svc, "gold_checks", lambda g, e, m: clean_gold(e, m))
    ctl = env["admin"]
    body = {"entity": "SUBCO", "month": "2020-06"}
    w = lambda: env["db"].execute("SELECT fpa_app.period_is_writable('SUBCO', '2020-06-01') AS w").fetchone()["w"]  # noqa: E731
    assert w() is True                                                                      # open
    go(ctl, "/period/soft-close", {**body, "reason": "month complete and reviewed"})
    assert w() is True                                                                      # soft-closed: still writable (a controller approves changes)
    go(ctl, "/signoff", {**body, "check_key": "intercompany", "decision": "SIGNED_OFF", "comment": "reconciled with HoldCo ledger"})
    assert go(ctl, "/period/management-close", {**body, "reason": "closing for management"}).status_code == 200
    assert w() is False                                                                     # management-closed: no ordinary change
    go(ctl, "/period/reopen", {**body, "reason": "a late invoice needs booking"})
    assert w() is True                                                                      # reopened


def test_viewer_reads_but_cannot_act_and_the_app_login_cannot_write_the_status_table(env, monkeypatch):
    monkeypatch.setattr(svc, "gold_checks", lambda g, e, m: clean_gold(e, m))
    v = env["person"]("view@example.test", "viewer")
    assert v.get("/api/v1/close/periods", params={"from_month": "2020-01", "to_month": "2020-03"}).status_code == 200
    assert go(v, "/period/soft-close", {"entity": "SUBCO", "month": "2020-07", "reason": "closing as a viewer"}).status_code == 403
    import psycopg
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        env["db"].execute("UPDATE reporting_period_status SET status = 'FINAL_CLOSED'")
    env["db"].rollback()
