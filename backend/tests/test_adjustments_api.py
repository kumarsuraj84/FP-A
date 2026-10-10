"""Adjustments API end to end (HTTP, real app database, real gold_fpa for rate and preview). One shared connection whose commit is a no-op, rolled back at the end, so no
user, adjustment or audit row is left behind. Skipped without fpa_app; the gold-backed tests are skipped without gold_fpa."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adjustments import router as adj_router
from app.adjustments import service as svc
from app.appdb.conn import app_connection
from app.auth import router as auth_router
from app.auth import service as auth

try:
    _c = app_connection()
    _c.close()
    HAVE_DB = True
except Exception:  # noqa: BLE001
    HAVE_DB = False
pytestmark = pytest.mark.skipif(not HAVE_DB, reason="fpa_app not reachable")

H = {"X-FPA-Request": "1"}
PW = "Correct-Horse-Battery-9"


class Shared:
    """One real connection for the whole test. commit() releases a savepoint and opens the next; rollback() undoes only the work since the last commit, like a request
    that fails and rolls back its own transaction in production."""

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


@pytest.fixture()
def env(monkeypatch):
    s = Shared()
    monkeypatch.setattr(auth, "app_connection", lambda: s)
    monkeypatch.setattr(adj_router, "app_connection", lambda: s)
    app = FastAPI()
    app.include_router(auth_router.router)
    app.include_router(adj_router.router)
    app.state.db = gold_db()
    s.execute("UPDATE app_user SET role = 'viewer' WHERE role = 'admin'")      # inside this rolled-back transaction only: a real administrator may exist now
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
        yield {"app": app, "admin": admin, "person": person, "db": s, "gold": app.state.db}
    finally:
        s.c.rollback()
        s.c.close()


FIXED = {"month": "2031-04", "entity": "SUBCO", "management_line": "employee_cost", "location_type": "STORES", "adjustment_type": "PROVISION", "basis_type": "FIXED",
         "amount_rupees": "100000", "effect": "COST", "supporting_reference": "Gratuity policy 2031", "narrative": "monthly gratuity provision for stores"}


def post(c, url, body=None):
    return c.post("/api/v1/adjustments" + url, json=body or {}, headers=H)


def test_signed_in_manager_runs_the_whole_lifecycle_and_history_is_complete(env):
    m = env["person"]("mgr@example.test", "fpa_manager")
    r = post(m, "", FIXED)
    assert r.status_code == 200, r.text
    a = r.json()["data"]
    assert a["status"] == "DRAFT" and a["amount_rupees"] == "-100000.0000" and a["effect"] == "COST" and a["counts_in_management_total"] is False
    aid = a["adjustment_id"]
    assert post(m, f"/{aid}/submit").json()["data"]["status"] == "REVIEW"
    assert post(m, f"/{aid}/approve").json()["data"]["status"] == "APPROVED"
    assert post(m, f"/{aid}/activate").json()["data"]["counts_in_management_total"] is True
    assert post(m, f"/{aid}/request-reversal", {"comment": "provision no longer needed"}).json()["data"]["status"] == "REVERSAL_REQUESTED"
    assert post(m, f"/{aid}/approve-reversal").json()["data"]["status"] == "REVERSED"
    h = m.get(f"/api/v1/adjustments/{aid}/history").json()["data"]
    assert [e["event_type"] for e in h] == ["CREATED", "SUBMITTED", "APPROVED", "ACTIVATED", "REVERSAL_REQUESTED", "REVERSAL_APPROVED"]
    assert all(e["actor_email"] == "mgr@example.test" for e in h)


def test_viewer_cannot_write_but_can_read_and_anonymous_cannot_read(env):
    v = env["person"]("view@example.test", "viewer")
    assert post(v, "", FIXED).status_code == 403
    assert v.get("/api/v1/adjustments").status_code == 200
    assert TestClient(env["app"]).get("/api/v1/adjustments").status_code == 401


def test_write_without_header_is_refused_and_validation_messages_are_plain(env):
    m = env["person"]("mgr2@example.test", "fpa_manager")
    assert m.post("/api/v1/adjustments", json=FIXED).status_code == 403
    for bad, text in (({"amount_rupees": "-5"}, "positive"), ({"effect": "x"}, "COST"), ({"narrative": "short"}, "10 characters"), ({"management_line": "nope"}, "management line"),
                      ({"entity": "CONSOLIDATED"}, "elimination"), ({"month": "2031-13"}, "month")):
        r = post(m, "", {**FIXED, **bad})
        assert r.status_code == 422 and text in r.json()["detail"], (bad, r.text)


def test_draft_is_editable_then_frozen_and_withdraw_works(env):
    m = env["person"]("mgr3@example.test", "fpa_manager")
    aid = post(m, "", FIXED).json()["data"]["adjustment_id"]
    r = m.put(f"/api/v1/adjustments/{aid}", json={**FIXED, "amount_rupees": "250000"}, headers=H)
    assert r.json()["data"]["amount_rupees"] == "-250000.0000"
    post(m, f"/{aid}/submit")
    assert m.put(f"/api/v1/adjustments/{aid}", json=FIXED, headers=H).status_code == 409
    assert post(m, f"/{aid}/reject", {"comment": "short"}).status_code == 422
    assert post(m, f"/{aid}/reject", {"comment": "amount not supported by the policy"}).json()["data"]["status"] == "REJECTED"


def test_maker_checker_follows_single_user_mode(env):
    maker, checker = env["person"]("maker@example.test", "fpa_manager"), env["person"]("checker@example.test", "finance_reviewer")
    aid = post(maker, "", FIXED).json()["data"]["adjustment_id"]
    post(maker, f"/{aid}/submit")
    env["db"].execute("UPDATE app_setting SET value = 'off' WHERE key = 'single_user_mode'")
    assert post(maker, f"/{aid}/approve").status_code == 403
    r = post(checker, f"/{aid}/approve"); assert r.status_code == 200, r.text
    assert post(checker, "", FIXED).status_code == 403                          # a reviewer checks, does not create


def test_closed_period_blocks_new_adjustments_with_a_clear_message(env):
    m = env["person"]("mgr4@example.test", "fpa_manager")
    env["db"].execute("INSERT INTO reporting_period_status (entity, period, status) VALUES ('SUBCO', '2031-05-01', 'FINAL_CLOSED')")
    r = post(m, "", {**FIXED, "month": "2031-05"})
    assert r.status_code == 422 and "closed" in r.json()["detail"]


def test_template_generation_calendar_and_closed_month_are_never_shifted(env):
    m = env["person"]("mgr5@example.test", "fpa_manager")
    t = m.post("/api/v1/adjustments/templates", json={**FIXED, "name": "Gratuity", "start_month": "2020-01", "end_month": "2020-06"}, headers=H).json()["data"]
    assert t["status"] == "DRAFT" and t["effect"] == "COST" and t["fixed_amount_rupees"] == "-100000.0000"
    assert m.post(f"/api/v1/adjustments/templates/{t['template_id']}/approve", headers=H).json()["data"]["status"] == "ACTIVE"
    env["db"].execute("INSERT INTO reporting_period_status (entity, period, status) VALUES ('SUBCO', '2020-03-01', 'FINAL_CLOSED')")
    g = m.post("/api/v1/adjustments/templates/generate/2020-02", headers=H).json()["data"]
    assert len(g["created"]) == 1 and not g["skipped"]
    again = m.post("/api/v1/adjustments/templates/generate/2020-02", headers=H).json()["data"]
    assert again["skipped"][0]["reason"] == "already generated"
    locked = m.post("/api/v1/adjustments/templates/generate/2020-03", headers=H).json()["data"]
    assert "period locked" in locked["skipped"][0]["reason"]
    cal = m.get("/api/v1/adjustments/calendar", params={"from_month": "2019-12", "to_month": "2020-07"}).json()["data"]
    row = next(r for r in cal["rows"] if r["template_id"] == t["template_id"])
    assert row["cells"]["2019-12"]["state"] == "n/a" and row["cells"]["2020-02"]["state"] == "proposed" and row["cells"]["2020-03"]["state"] == "locked"
    assert row["cells"]["2020-04"]["state"] == "missing" and row["cells"]["2020-07"]["state"] == "n/a"


def test_active_adjustments_reach_the_engine_only_through_the_app_register(env, monkeypatch):
    m = env["person"]("mgr6@example.test", "fpa_manager")
    aid = post(m, "", FIXED).json()["data"]["adjustment_id"]
    from app.mgmt import app_register
    monkeypatch.setattr(app_register, "app_connection", lambda: env["db"])
    monkeypatch.setenv("FPA_ADJ_SOURCE", "app")
    assert not [r for r in app_register.active_rows() if r["month"] == "2031-04"]       # a draft is not in the management total
    post(m, f"/{aid}/submit"), post(m, f"/{aid}/approve"), post(m, f"/{aid}/activate")
    rows = [r for r in app_register.active_rows() if r["month"] == "2031-04"]
    assert len(rows) == 1 and rows[0]["amount"] == app_register.Decimal("-0.0100") and rows[0]["kind"] == "provision" and rows[0]["entity"] == "SUBCO"
    monkeypatch.setenv("FPA_ADJ_SOURCE", "csv")
    assert app_register.active_rows() == []


@pytest.mark.skipif(gold_db() is None, reason="gold_fpa not reachable")
def test_rate_adjustment_freezes_its_basis_and_preview_shows_store_and_corporate_ebitda(env):
    m = env["person"]("mgr7@example.test", "fpa_manager")
    body = {**FIXED, "basis_type": "RATE", "rate": "0.005", "rate_metric": "net_sales", "month": "2026-08"}
    body.pop("amount_rupees")
    r = post(m, "", body)
    assert r.status_code == 200, r.text
    a = r.json()["data"]
    assert a["metric_snapshot"]["metric"] == "net_sales" and a["metric_snapshot"]["partial_month"] is False and D(a["amount_rupees"]) < 0
    p = m.get(f"/api/v1/adjustments/{a['adjustment_id']}/preview", params={"entity_view": "consolidated"}).json()["data"]["views"]["consolidated"]
    assert {"store_ebitda", "corporate_ebitda", "employee_cost"} <= set(p)
    assert abs(D(p["store_ebitda"]["change"]) - D(p["corporate_ebitda"]["change"])) <= D("0.0001") and abs(D(p["store_ebitda"]["change"]) - D(p["employee_cost"]["change"])) <= D("0.0001") and D(p["store_ebitda"]["change"]) < 0
    snap = a["metric_snapshot"]
    post(m, f"/{a['adjustment_id']}/submit")
    again = m.get(f"/api/v1/adjustments/{a['adjustment_id']}").json()["data"]
    assert again["status"] == "REVIEW" and again["metric_snapshot"]["value_rupees"] == snap["value_rupees"]


@pytest.mark.skipif(gold_db() is None, reason="gold_fpa not reachable")
def test_preview_of_an_unsaved_hocost_leaves_store_ebitda_unchanged(env):
    m = env["person"]("mgr8@example.test", "fpa_manager")
    r = post(m, "/preview", {**FIXED, "location_type": "HO", "management_line": "other_expenses", "month": "2026-08"})
    assert r.status_code == 200, r.text
    v = r.json()["data"]["views"]["consolidated"]
    assert D(v["store_ebitda"]["change"]) == 0 and D(v["corporate_ebitda"]["change"]) < 0


from decimal import Decimal as D  # noqa: E402
