"""Integration tests for fpa_app migration 004 (corrections), run as the app login inside a transaction that is always rolled back. Skipped without fpa_app."""
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
FP = "a" * 64


@pytest.fixture()
def db():
    c = app_connection()
    try:
        yield c
    finally:
        c.rollback()
        c.close()


def user(c, email, role="fpa_manager"):
    return c.execute("INSERT INTO app_user (email, display_name, role, password_hash) VALUES (%s, 'Test', %s, 'x') RETURNING user_id", (email, role)).fetchone()["user_id"]


def request(c, uid, ctype="GROUP", scope="LINE", entity="RETAIL"):
    return c.execute("INSERT INTO correction_request (scope_type, correction_type, source_entity, reason_code, reason_text, evidence_reference, requested_by, created_by) "
                     "VALUES (%s, %s, %s, 'WRONG_CLASSIFICATION', 'booked to the wrong management group', 'ticket 1', %s, %s) RETURNING request_id", (scope, ctype, entity, uid, uid)).fetchone()["request_id"]


def line(c, rid, key="K1", entity="RETAIL", **kw):
    row = dict(request_id=rid, source_entity=entity, source_line_key=key, fingerprint=FP, source_amount_snapshot="1000.0000", voucher_key="V1", ledger_key="L1", site_code="10",
               original_group="other_opex", corrected_group="employee_cost", original_month="2031-04-01")
    row.update(kw)
    return c.execute(f"INSERT INTO correction_line ({', '.join(row)}) VALUES ({', '.join(['%s'] * len(row))}) RETURNING line_id", list(row.values())).fetchone()["line_id"]


def event(c, rid, uid, etype, to, comment=None):
    c.execute("INSERT INTO correction_event (request_id, event_type, to_status, actor_user_id, comment) VALUES (%s, %s, %s, %s, %s)", (rid, etype, to, uid, comment))


def status(c, rid):
    return c.execute("SELECT status FROM correction_request WHERE request_id = %s", (rid,)).fetchone()["status"]


def activate(c, rid, uid):
    event(c, rid, uid, "CREATED", "DRAFT")
    event(c, rid, uid, "SUBMITTED", "SUBMITTED")
    event(c, rid, uid, "APPROVED", "APPROVED")
    event(c, rid, uid, "ACTIVATED", "ACTIVE")


def test_lifecycle_overlay_appears_when_active_and_has_no_amount(db):
    u = user(db, "c1@example.test")
    r = request(db, u)
    line(db, r)
    activate(db, r, u)
    assert status(db, r) == "ACTIVE"
    ov = db.execute("SELECT * FROM v_correction_overlay WHERE request_id = %s", (r,)).fetchone()
    assert ov["corrected_group"] == "employee_cost" and ov["corrected_month"] is None and ov["source_line_key"] == "K1"
    assert not any("amount" in k for k in ov)
    event(db, r, u, "REVERSAL_REQUESTED", "REVERSAL_REQUESTED", "booked in error, undo it")
    assert db.execute("SELECT count(*) AS n FROM v_correction_overlay WHERE request_id = %s", (r,)).fetchone()["n"] == 1
    event(db, r, u, "REVERSAL_APPROVED", "REVERSED")
    assert db.execute("SELECT count(*) AS n FROM v_correction_overlay WHERE request_id = %s", (r,)).fetchone()["n"] == 0


def test_nothing_applies_before_activation(db):
    u = user(db, "c2@example.test")
    r = request(db, u)
    line(db, r)
    event(db, r, u, "CREATED", "DRAFT")
    event(db, r, u, "SUBMITTED", "SUBMITTED")
    event(db, r, u, "APPROVED", "APPROVED")
    assert db.execute("SELECT count(*) AS n FROM v_correction_overlay WHERE request_id = %s", (r,)).fetchone()["n"] == 0


def test_second_active_correction_on_the_same_line_is_refused(db):
    u = user(db, "c3@example.test")
    r1, r2 = request(db, u), request(db, u)
    line(db, r1)
    line(db, r2, corrected_group="rent")
    activate(db, r1, u)
    event(db, r2, u, "CREATED", "DRAFT")
    event(db, r2, u, "SUBMITTED", "SUBMITTED")
    event(db, r2, u, "APPROVED", "APPROVED")
    with pytest.raises(psycopg.errors.UniqueViolation):
        event(db, r2, u, "ACTIVATED", "ACTIVE")


def test_same_key_in_the_other_entity_is_a_different_line(db):
    u = user(db, "c4@example.test")
    r1, r2 = request(db, u), request(db, u, entity="VENTURES")
    line(db, r1)
    line(db, r2, entity="VENTURES")
    activate(db, r1, u)
    activate(db, r2, u)
    assert db.execute("SELECT count(*) AS n FROM v_correction_overlay WHERE source_line_key = 'K1'").fetchone()["n"] >= 2


def test_a_correction_must_change_something_and_respect_its_type(db):
    u = user(db, "c5@example.test")
    r = request(db, u)
    with pytest.raises(psycopg.errors.CheckViolation):
        line(db, r, corrected_group="other_opex")
    db.rollback()
    u = user(db, "c5b@example.test")
    r = request(db, u, ctype="GROUP")
    with pytest.raises(psycopg.errors.CheckViolation):
        line(db, r, corrected_month="2031-05-01")


def test_fingerprint_must_be_64_hex(db):
    u = user(db, "c6@example.test")
    r = request(db, u)
    with pytest.raises(psycopg.errors.CheckViolation):
        line(db, r, fingerprint="short")


def test_lines_are_frozen_after_submission_and_cannot_be_added(db):
    u = user(db, "c7@example.test")
    r = request(db, u)
    line(db, r)
    event(db, r, u, "CREATED", "DRAFT")
    event(db, r, u, "SUBMITTED", "SUBMITTED")
    with pytest.raises(psycopg.errors.CheckViolation):
        line(db, r, key="K2")
    db.rollback()


def test_the_app_login_cannot_change_status_or_flags_or_delete(db):
    u = user(db, "c8@example.test")
    r = request(db, u)
    line(db, r)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("UPDATE correction_request SET status = 'ACTIVE' WHERE request_id = %s", (r,))
    db.rollback()
    u = user(db, "c8b@example.test")
    r = request(db, u)
    line(db, r)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("UPDATE correction_line SET group_active = true WHERE request_id = %s", (r,))
    db.rollback()
    u = user(db, "c8c@example.test")
    r = request(db, u)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("DELETE FROM correction_request WHERE request_id = %s", (r,))


def test_requester_cannot_approve_when_single_user_mode_is_off(db):
    maker, checker = user(db, "c9a@example.test"), user(db, "c9b@example.test")
    r = request(db, maker)
    line(db, r)
    event(db, r, maker, "CREATED", "DRAFT")
    event(db, r, maker, "SUBMITTED", "SUBMITTED")
    db.execute("UPDATE app_setting SET value = 'off' WHERE key = 'single_user_mode'")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        event(db, r, maker, "APPROVED", "APPROVED")
    db.rollback()


def test_closed_month_blocks_approval_and_soft_close_needs_a_controller(db):
    u, ctl = user(db, "c10a@example.test"), user(db, "c10b@example.test", role="controller")
    r = request(db, u, ctype="EXPENSE_MONTH")
    line(db, r, corrected_group=None, corrected_month="2031-08-01", original_month="2031-07-01")
    db.execute("INSERT INTO reporting_period_status (entity, period, status) VALUES ('SUBCO', '2031-08-01', 'SOFT_CLOSED')")
    event(db, r, u, "CREATED", "DRAFT")
    event(db, r, u, "SUBMITTED", "SUBMITTED")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        event(db, r, u, "APPROVED", "APPROVED")
    db.rollback()
    u, ctl = user(db, "c10c@example.test"), user(db, "c10d@example.test", role="controller")
    r = request(db, u, ctype="EXPENSE_MONTH")
    line(db, r, key="K9", corrected_group=None, corrected_month="2031-10-01", original_month="2031-09-01")
    db.execute("INSERT INTO reporting_period_status (entity, period, status) VALUES ('SUBCO', '2031-10-01', 'SOFT_CLOSED')")
    event(db, r, u, "CREATED", "DRAFT")
    event(db, r, u, "SUBMITTED", "SUBMITTED")
    event(db, r, ctl, "APPROVED", "APPROVED")
    assert status(db, r) == "APPROVED"
    db.execute("UPDATE reporting_period_status SET status = 'FINAL_CLOSED' WHERE entity = 'SUBCO' AND period = '2031-10-01'")
    with pytest.raises(psycopg.errors.CheckViolation):
        event(db, r, ctl, "ACTIVATED", "ACTIVE")


def test_source_change_pauses_the_overlay_and_source_fix_supersedes_it(db):
    u = user(db, "c11@example.test")
    r = request(db, u)
    line(db, r)
    activate(db, r, u)
    event(db, r, u, "SOURCE_CHANGED", "SOURCE_REVIEW_REQUIRED")
    assert db.execute("SELECT count(*) AS n FROM v_correction_overlay WHERE request_id = %s", (r,)).fetchone()["n"] == 0
    event(db, r, u, "SOURCE_RECONFIRMED", "ACTIVE", "checked again, source still wrong")
    assert db.execute("SELECT count(*) AS n FROM v_correction_overlay WHERE request_id = %s", (r,)).fetchone()["n"] == 1
    event(db, r, u, "SOURCE_NOW_MATCHES", "SUPERSEDED_BY_SOURCE")
    assert db.execute("SELECT count(*) AS n FROM v_correction_overlay WHERE request_id = %s", (r,)).fetchone()["n"] == 0


def test_submit_needs_a_line_and_events_are_append_only(db):
    u = user(db, "c12@example.test")
    r = request(db, u)
    event(db, r, u, "CREATED", "DRAFT")
    with pytest.raises(psycopg.errors.CheckViolation):
        event(db, r, u, "SUBMITTED", "SUBMITTED")
    db.rollback()
    u = user(db, "c12b@example.test")
    r = request(db, u)
    event(db, r, u, "CREATED", "DRAFT")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("DELETE FROM correction_event WHERE request_id = %s", (r,))
