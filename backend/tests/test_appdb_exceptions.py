"""Integration tests for fpa_app migration 005 (exceptions), run as the app login inside a transaction that is always rolled back. Skipped without fpa_app."""
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


def user(c, email, role="fpa_manager"):
    return c.execute("INSERT INTO app_user (email, display_name, role, password_hash) VALUES (%s, 'Test', %s, 'x') RETURNING user_id", (email, role)).fetchone()["user_id"]


def case(c, key="k1", score=70, **kw):
    row = dict(dedupe_key=key, exception_type="EXPENSE_SPIKE", domain="EXPENSE", entity="SUBCO", metric_id="store_expense", period="2031-04-01", title="Expense spike",
               severity_score=score, materiality_score=score, recency_score=score, actionability_score=score, final_score=score)
    row.update(kw)
    cid = c.execute(f"INSERT INTO exception_case ({', '.join(row)}) VALUES ({', '.join(['%s'] * len(row))}) RETURNING case_id", list(row.values())).fetchone()["case_id"]
    c.execute("INSERT INTO exception_event (case_id, event_type, to_status, actor_label) VALUES (%s, 'DETECTED', 'OPEN', 'system')", (cid,))
    return cid


def ev(c, cid, uid, etype, to=None, comment=None, **kw):
    cols = dict(case_id=cid, event_type=etype, to_status=to or "OPEN", actor_user_id=uid, comment=comment)
    cols.update(kw)
    c.execute(f"INSERT INTO exception_event ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})", list(cols.values()))


def row(c, cid):
    return c.execute("SELECT * FROM exception_case WHERE case_id = %s", (cid,)).fetchone()


def test_assign_acknowledge_resolve_close_cycle(db):
    mgr, rev, own = user(db, "e1m@example.test"), user(db, "e1r@example.test", "finance_reviewer"), user(db, "e1o@example.test")
    c = case(db)
    assert row(db, c)["status"] == "OPEN" and row(db, c)["band"] == "HIGH"
    ev(db, c, mgr, "ASSIGNED", new_owner_user_id=own, new_due_date="2031-05-15", new_next_action="check the vendor invoices")
    r = row(db, c)
    assert r["owner_user_id"] == own and str(r["due_date"]) == "2031-05-15" and r["next_action"] == "check the vendor invoices"
    ev(db, c, own, "ACKNOWLEDGED", "ACKNOWLEDGED")
    ev(db, c, own, "RESOLVED", "RESOLVED", "invoices corrected in the source")
    ev(db, c, rev, "CLOSED", "CLOSED", "checked and agreed by finance", closure_reason="RESOLVED_FIXED")
    r = row(db, c)
    assert r["status"] == "CLOSED" and r["closure_reason"] == "RESOLVED_FIXED" and r["closed_at"] is not None


def test_owner_cannot_close_own_work_when_single_user_mode_is_off(db):
    own = user(db, "e2o@example.test", "finance_reviewer")
    c = case(db)
    ev(db, c, own, "ASSIGNED", new_owner_user_id=own)
    db.execute("UPDATE app_setting SET value = 'off' WHERE key = 'single_user_mode'")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        ev(db, c, own, "CLOSED", "CLOSED", "closing my own item now", closure_reason="OTHER")
    db.rollback()


def test_action_owner_cannot_close_and_viewer_cannot_write(db):
    own, view = user(db, "e3o@example.test", "fpa_manager"), user(db, "e3v@example.test", "viewer")
    c = case(db)
    db.execute("UPDATE app_setting SET value = 'off' WHERE key = 'single_user_mode'")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        ev(db, c, own, "CLOSED", "CLOSED", "trying to close it myself", closure_reason="OTHER")
    db.rollback()
    c = case(db, key="k2")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        ev(db, c, view, "ACKNOWLEDGED", "ACKNOWLEDGED")
    db.rollback()
    view = user(db, "e3w@example.test", "viewer")
    c = case(db, key="k3")
    ev(db, c, view, "COMMENTED", comment="a viewer may comment")


def test_close_needs_reason_and_closed_case_accepts_only_reopen_or_comment(db):
    rev = user(db, "e4@example.test", "finance_reviewer")
    c = case(db)
    with pytest.raises(psycopg.errors.CheckViolation):
        ev(db, c, rev, "CLOSED", "CLOSED", "no reason code given here")
    db.rollback()
    rev = user(db, "e4b@example.test", "finance_reviewer")
    c = case(db, key="k5")
    ev(db, c, rev, "CLOSED", "CLOSED", "false alarm confirmed by finance", closure_reason="FALSE_POSITIVE")
    with pytest.raises(psycopg.errors.CheckViolation):
        ev(db, c, rev, "ACKNOWLEDGED", "ACKNOWLEDGED")
    db.rollback()
    rev = user(db, "e4c@example.test", "finance_reviewer")
    c = case(db, key="k6")
    ev(db, c, rev, "CLOSED", "CLOSED", "false alarm confirmed by finance", closure_reason="FALSE_POSITIVE")
    ev(db, c, rev, "REOPENED", "OPEN", "closed too early, the source is still wrong")
    assert row(db, c)["status"] == "OPEN" and row(db, c)["closure_reason"] is None


def test_one_live_case_per_dedupe_key_and_a_new_linked_case_after_close(db):
    rev = user(db, "e5@example.test", "finance_reviewer")
    c1 = case(db, key="dup")
    with pytest.raises(psycopg.errors.UniqueViolation):
        case(db, key="dup")
    db.rollback()
    rev = user(db, "e5b@example.test", "finance_reviewer")
    c1 = case(db, key="dup2")
    ev(db, c1, rev, "CLOSED", "CLOSED", "resolved and agreed by finance", closure_reason="RESOLVED_FIXED")
    c2 = case(db, key="dup2", recurrence_of_case_id=c1, recurrence_no=2)
    assert row(db, c2)["recurrence_no"] == 2 and row(db, c2)["recurrence_of_case_id"] == c1


def test_system_recurrence_updates_the_open_case(db):
    c = case(db, score=50)
    db.execute("INSERT INTO exception_event (case_id, event_type, to_status, actor_label, new_evidence, new_final_score) VALUES (%s, 'SYSTEM_RECURRED', 'OPEN', 'system', %s, 85)",
               (c, '{"observed": 1}'))
    r = row(db, c)
    assert r["detection_count"] == 2 and float(r["final_score"]) == 85 and r["band"] == "CRITICAL" and r["evidence"] == {"observed": 1}


def test_escalation_overrides_the_score_band_and_status_is_event_only(db):
    c = case(db, score=10, escalated=True)
    assert row(db, c)["band"] == "CRITICAL"
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("UPDATE exception_case SET status = 'CLOSED' WHERE case_id = %s", (c,))
    db.rollback()
    c = case(db, key="k9")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("DELETE FROM exception_event WHERE case_id = %s", (c,))
