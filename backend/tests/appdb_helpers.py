"""Helpers for tests that need a closed reporting period. The period moves only through events (migration 008), so a test walks the real transitions as a throwaway admin
inside its own rolled-back transaction."""
from __future__ import annotations

import uuid

ORDER = ["OPEN", "SOFT_CLOSED", "MANAGEMENT_CLOSED", "FINAL_CLOSED"]


def set_period(c, entity: str, period: str, target: str) -> None:
    """Walk entity/period from its current status up to `target` (SOFT_CLOSED, MANAGEMENT_CLOSED or FINAL_CLOSED)."""
    uid = c.execute("INSERT INTO app_user (email, display_name, role, password_hash) VALUES (%s, 'Closer', 'admin', 'x') RETURNING user_id", (f"closer-{uuid.uuid4().hex[:8]}@example.test",)).fetchone()["user_id"]
    row = c.execute("SELECT status FROM reporting_period_status WHERE entity = %s AND period = %s", (entity, period)).fetchone()
    cur = row["status"] if row else "OPEN"
    for step in ORDER[ORDER.index(cur) + 1: ORDER.index(target) + 1]:
        c.execute("INSERT INTO reporting_period_event (entity, period, from_status, to_status, actor_user_id, reason) VALUES (%s, %s, %s, %s, %s, 'test period close step')", (entity, period, cur, step, uid))
        cur = step
