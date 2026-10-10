"""Integration tests for fpa_app migration 002 (adjustments). They run against the real app database as the app login inside a transaction that is always rolled
back, so nothing is left behind. Skipped when fpa_app is not reachable."""
from __future__ import annotations

import psycopg
import pytest

from app.appdb.conn import app_connection

try:
    _c = app_connection()
    _c.close()
    HAVE_DB = True
except Exception:  # noqa: BLE001
    HAVE_DB = False

pytestmark = pytest.mark.skipif(not HAVE_DB, reason="fpa_app not reachable")


@pytest.fixture()
def db():
    c = app_connection()
    try:
        yield c
    finally:
        c.rollback()
        c.close()


def user(c, email: str) -> str:
    return c.execute("INSERT INTO app_user (email, display_name, role, password_hash) VALUES (%s, 'Test', 'fpa_manager', 'x') RETURNING user_id", (email,)).fetchone()["user_id"]


def adjustment(c, uid, month="2031-04-01", **kw) -> str:
    row = dict(reporting_month=month, entity="SUBCO", management_line="employee_cost", location_type="STORES", adjustment_type="PROVISION", basis_type="FIXED",
               entered_amount_rupees="-1000.0000", adjustment_amount_rupees="-1000.0000", supporting_reference="policy ref", narrative="monthly gratuity provision", owner_user_id=uid, created_by=uid)
    row.update(kw)
    cols = ", ".join(row)
    return c.execute(f"INSERT INTO adjustment ({cols}) VALUES ({', '.join(['%s'] * len(row))}) RETURNING adjustment_id", list(row.values())).fetchone()["adjustment_id"]


def event(c, aid, uid, etype, to, comment=None):
    c.execute("INSERT INTO adjustment_event (adjustment_id, event_type, to_status, actor_user_id, comment) VALUES (%s, %s, %s, %s, %s)", (aid, etype, to, uid, comment))


def status(c, aid):
    return c.execute("SELECT status FROM adjustment WHERE adjustment_id = %s", (aid,)).fetchone()["status"]


def lifecycle(c, aid, uid):
    event(c, aid, uid, "CREATED", "DRAFT")
    event(c, aid, uid, "SUBMITTED", "REVIEW")
    event(c, aid, uid, "APPROVED", "APPROVED")
    event(c, aid, uid, "ACTIVATED", "ACTIVE")


def test_full_lifecycle_moves_status_only_by_events(db):
    u = user(db, "t1@example.test")
    a = adjustment(db, u)
    assert status(db, a) == "DRAFT"
    lifecycle(db, a, u)
    assert status(db, a) == "ACTIVE"
    assert db.execute("SELECT count(*) AS n FROM v_adjustment_active WHERE adjustment_id = %s", (a,)).fetchone()["n"] == 1
    event(db, a, u, "REVERSAL_REQUESTED", "REVERSAL_REQUESTED", "wrong rate used for the month")
    event(db, a, u, "REVERSAL_APPROVED", "REVERSED")
    assert status(db, a) == "REVERSED"
    assert [r["seq"] for r in db.execute("SELECT seq FROM adjustment_event WHERE adjustment_id = %s ORDER BY seq", (a,)).fetchall()] == list(range(1, 7))


def test_app_login_cannot_set_status_directly(db):
    u = user(db, "t2@example.test")
    a = adjustment(db, u)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("UPDATE adjustment SET status = 'ACTIVE' WHERE adjustment_id = %s", (a,))


def test_illegal_transition_is_refused(db):
    u = user(db, "t3@example.test")
    a = adjustment(db, u)
    event(db, a, u, "CREATED", "DRAFT")
    with pytest.raises(psycopg.errors.CheckViolation):
        event(db, a, u, "ACTIVATED", "ACTIVE")


def test_meaning_columns_are_frozen_after_submission_but_editable_in_draft(db):
    u = user(db, "t4@example.test")
    a = adjustment(db, u)
    event(db, a, u, "CREATED", "DRAFT")
    db.execute("UPDATE adjustment SET narrative = 'edited while still a draft' WHERE adjustment_id = %s", (a,))
    event(db, a, u, "SUBMITTED", "REVIEW")
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("UPDATE adjustment SET entered_amount_rupees = -5, adjustment_amount_rupees = -5 WHERE adjustment_id = %s", (a,))


def test_maker_checker_when_single_user_mode_is_off(db):
    maker, checker = user(db, "t5a@example.test"), user(db, "t5b@example.test")
    a = adjustment(db, maker)
    event(db, a, maker, "CREATED", "DRAFT")
    event(db, a, maker, "SUBMITTED", "REVIEW")
    db.execute("UPDATE app_setting SET value = 'off' WHERE key = 'single_user_mode'")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        event(db, a, maker, "APPROVED", "APPROVED")
    db.rollback()


def test_checker_can_approve_when_single_user_mode_is_off(db):
    maker, checker = user(db, "t6a@example.test"), user(db, "t6b@example.test")
    a = adjustment(db, maker)
    event(db, a, maker, "CREATED", "DRAFT")
    event(db, a, maker, "SUBMITTED", "REVIEW")
    db.execute("UPDATE app_setting SET value = 'off' WHERE key = 'single_user_mode'")
    event(db, a, checker, "APPROVED", "APPROVED")
    assert status(db, a) == "APPROVED"
    assert db.execute("SELECT approved_by FROM adjustment WHERE adjustment_id = %s", (a,)).fetchone()["approved_by"] == checker


def test_rejection_needs_a_reason(db):
    u = user(db, "t7@example.test")
    a = adjustment(db, u)
    event(db, a, u, "CREATED", "DRAFT")
    event(db, a, u, "SUBMITTED", "REVIEW")
    with pytest.raises(psycopg.errors.CheckViolation):
        event(db, a, u, "REJECTED", "REJECTED", "no")


def test_closed_period_refuses_new_and_activation(db):
    u = user(db, "t8@example.test")
    # the app login cannot close a period itself in this test, so close one through the projection it may update (a plain INSERT is allowed for status rows)
    db.execute("INSERT INTO reporting_period_status (entity, period, status) VALUES ('SUBCO', '2031-05-01', 'FINAL_CLOSED')")
    with pytest.raises(psycopg.errors.CheckViolation):
        adjustment(db, u, month="2031-05-01")


def test_events_are_append_only(db):
    u = user(db, "t9@example.test")
    a = adjustment(db, u)
    event(db, a, u, "CREATED", "DRAFT")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("DELETE FROM adjustment_event WHERE adjustment_id = %s", (a,))


def test_rate_basis_needs_metric_snapshot_and_no_entered_amount(db):
    u = user(db, "t10@example.test")
    with pytest.raises(psycopg.errors.CheckViolation):
        adjustment(db, u, basis_type="RATE", entered_amount_rupees=None, rate="0.01", rate_metric="net_sales", adjustment_amount_rupees="-5")


def test_one_live_adjustment_per_template_and_month(db):
    u = user(db, "t11@example.test")
    t = db.execute("INSERT INTO adjustment_template (name, entity, management_line, location_type, adjustment_type, basis_type, fixed_amount_rupees, start_month, owner_user_id, created_by) "
                   "VALUES ('Gratuity', 'SUBCO', 'employee_cost', 'STORES', 'PROVISION', 'FIXED', -1000, '2031-01-01', %s, %s) RETURNING template_id", (u, u)).fetchone()["template_id"]
    adjustment(db, u, template_id=t)
    with pytest.raises(psycopg.errors.UniqueViolation):
        adjustment(db, u, template_id=t)


def test_period_is_keyed_by_entity_and_consolidated_needs_both(db):
    u = user(db, "t12@example.test")
    db.execute("INSERT INTO reporting_period_status (entity, period, status) VALUES ('SUBCO', '2031-06-01', 'FINAL_CLOSED')")
    adjustment(db, u, month="2031-06-01", entity="HOLDCO", location_type="HO")
    with pytest.raises(psycopg.errors.CheckViolation):
        adjustment(db, u, month="2031-06-01", entity="CONSOLIDATED", adjustment_type="INTERCOMPANY_ELIMINATION")


def test_rate_adjustment_with_frozen_basis_snapshot(db):
    u = user(db, "t13@example.test")
    a = adjustment(db, u, basis_type="RATE", entered_amount_rupees=None, rate="0.01", rate_metric="net_sales", adjustment_amount_rupees="-250000.0000",
                   metric_snapshot='{"metric": "net_sales", "value": 25000000, "run_id": "r1"}', calculated_at="2031-04-02T00:00:00Z")
    event(db, a, u, "CREATED", "DRAFT")
    event(db, a, u, "SUBMITTED", "REVIEW")
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("UPDATE adjustment SET metric_snapshot = '{}' WHERE adjustment_id = %s", (a,))
