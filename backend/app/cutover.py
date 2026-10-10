"""Recording a cut-over from a legacy file source to the governed app source (adjustments register, mapping). The administrator sees the validation, and only an IDENTICAL result can be
recorded; the record keeps what they saw, the first month the app is the source, who and when (append-only, migration 013). Switching the environment variable itself (FPA_ADJ_SOURCE,
FPA_MAPPING_SOURCE) stays a deliberate deployment step: the record is the evidence, not the switch."""
from __future__ import annotations

import json
from datetime import date

import psycopg

from .adjustments.service import Problem, db_error, month_start
from .auth.service import Actor, audit


def record(conn, actor: Actor, domain: str, first_month: str, comment: str, validation: dict) -> dict:
    if actor.role != "admin":
        raise Problem("Only an administrator records a cut-over.", 403)
    if len((comment or "").strip()) < 10:
        raise Problem("Write what was decided in at least 10 characters.")
    m = month_start(first_month)
    if not validation.get("identical"):
        raise Problem("The validation is not identical: resolve the differences before recording a cut-over.", 409)
    try:
        row = conn.execute("INSERT INTO cutover_record (domain, first_month, validation, identical, comment, actor_user_id) VALUES (%s, %s, %s::jsonb, true, %s, %s) RETURNING cutover_id, at",
                           (domain, m, json.dumps(validation, default=str), comment.strip(), actor.user_id)).fetchone()
    except psycopg.Error as e:
        conn.rollback()
        raise db_error(e) from None
    audit(conn, actor.email, "cutover_recorded", "cutover", f"{domain}:{m.strftime('%Y-%m')}", {"cutover_id": row["cutover_id"], "comment": comment.strip()}, actor.user_id)
    conn.commit()
    return {"cutover_id": row["cutover_id"], "domain": domain, "first_month": m.strftime("%Y-%m"), "at": row["at"],
            "next": "Now set the environment variable (FPA_ADJ_SOURCE=app or FPA_MAPPING_SOURCE=app) and restart the API. The old files are history from here on."}


def history(conn) -> list[dict]:
    return [dict(r) | {"first_month": r["first_month"].strftime("%Y-%m")} for r in conn.execute(
        "SELECT c.cutover_id, c.domain, c.first_month, c.identical, c.comment, c.at, u.email AS actor FROM cutover_record c LEFT JOIN app_user u ON u.user_id = c.actor_user_id ORDER BY c.cutover_id DESC").fetchall()]
