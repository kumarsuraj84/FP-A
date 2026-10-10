"""Exception Inbox: ranked cases with an owner, due date, next action and an append-only history (migration 005). Workflow around evidence only: nothing here changes a
reported number and no case holds a finance fact; the evidence column is a snapshot of what triggered the case.

Score (agreed with ChatGPT, UNCALIBRATED until Finance has reviewed twelve months of history):
  final = min(100, (0.35 severity + 0.30 materiality + 0.15 recency + 0.20 actionability) * persistence), persistence 1.00 / 1.10 / 1.25 for 1-2 / 3-5 / 6+ detections;
  bands CRITICAL 80+ (or escalated), HIGH 60-79, MEDIUM 40-59, LOW below 40 (the database computes the band).
Dedupe key = sha256(type, entity, site, metric, period, subject). A live case is updated by SYSTEM_RECURRED; a case that was CLOSED and is detected again becomes a NEW case
linked by recurrence_of_case_id (recurrence_no + 1). REOPENED is only for a closure that was itself premature.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, timedelta
from decimal import Decimal

import psycopg

from ..adjustments.service import Problem, db_error, month_start
from ..auth.service import Actor, audit

WEIGHTS = (Decimal("0.35"), Decimal("0.30"), Decimal("0.15"), Decimal("0.20"))
DOMAINS = ("EXPENSE", "REVENUE", "CREDITORS", "CASH", "CONTROLS", "RELATED_PARTY", "MAPPING", "CLOSE")
DEFAULT_DUE_DAYS = {"CRITICAL": 2, "HIGH": 5, "MEDIUM": 10, "LOW": 20}
ASSIGNERS = ("fpa_manager", "finance_reviewer", "controller", "admin")
WORKERS = ("fpa_manager", "finance_reviewer", "controller", "admin")


def persistence(detections: int) -> Decimal:
    return Decimal("1.25") if detections >= 6 else Decimal("1.10") if detections >= 3 else Decimal("1.00")


def final_score(sev, mat, rec, act, detections: int = 1) -> Decimal:
    base = WEIGHTS[0] * Decimal(str(sev)) + WEIGHTS[1] * Decimal(str(mat)) + WEIGHTS[2] * Decimal(str(rec)) + WEIGHTS[3] * Decimal(str(act))
    return min(Decimal(100), (base * persistence(detections))).quantize(Decimal("0.01"))


def dedupe_key(c: dict) -> str:
    parts = (c["exception_type"], c.get("entity"), c.get("site_code"), c.get("metric_id"), c["period"].isoformat() if c.get("period") else None, c.get("subject_key"))
    return hashlib.sha256("|".join("<NULL>" if p is None else str(p).strip().upper() for p in parts).encode()).hexdigest()


def need(actor: Actor, roles: tuple, what: str) -> None:
    if actor.role not in roles:
        raise Problem(f"Your role ({actor.role}) cannot {what}.", 403)


def case_view(r: dict) -> dict:
    out = {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in r.items()}
    out["period"] = r["period"].strftime("%Y-%m") if r["period"] else None
    out["overdue"] = bool(r["due_date"] and r["due_date"] < date.today() and r["status"] != "CLOSED")
    out["recurring"] = r["recurrence_no"] > 1
    return out


def fetch(conn, case_id: str) -> dict:
    r = conn.execute("SELECT * FROM exception_case WHERE case_id = %s", (case_id,)).fetchone()
    if r is None:
        raise Problem("No such exception.", 404)
    return r


# --------------------------------------------------------------------------- system detection

def ingest(conn, candidates: list[dict]) -> dict:
    """Write detector output. Each candidate: exception_type, domain, entity, site_code, metric_id, period (date), subject_key, title, severity, materiality, recency, actionability
    (0-100), escalated, evidence (dict), drill_link, source_run_id. Returns counts. Detected by the system (no user)."""
    out = {"created": 0, "recurred": 0, "recurrence_cases": 0}
    for c in candidates:
        key = dedupe_key(c)
        live = conn.execute("SELECT * FROM exception_case WHERE dedupe_key = %s AND status <> 'CLOSED'", (key,)).fetchone()
        if live:
            score = final_score(c["severity"], c["materiality"], c["recency"], c["actionability"], live["detection_count"] + 1)
            conn.execute("INSERT INTO exception_event (case_id, event_type, to_status, actor_label, new_evidence, new_final_score) VALUES (%s, 'SYSTEM_RECURRED', %s, 'system', %s::jsonb, %s)",
                         (live["case_id"], live["status"], json.dumps(c.get("evidence", {}), default=str), score))
            out["recurred"] += 1
            continue
        last = conn.execute("SELECT case_id, recurrence_no FROM exception_case WHERE dedupe_key = %s ORDER BY created_at DESC LIMIT 1", (key,)).fetchone()
        score = final_score(c["severity"], c["materiality"], c["recency"], c["actionability"], 1)
        row = conn.execute("""INSERT INTO exception_case (dedupe_key, exception_type, domain, entity, site_code, metric_id, period, subject_key, title, recurrence_of_case_id, recurrence_no,
                                severity_score, materiality_score, recency_score, actionability_score, escalated, final_score, evidence, drill_link, source_run_id)
                              VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s) RETURNING case_id, band""",
                           (key, c["exception_type"], c["domain"], c.get("entity"), c.get("site_code"), c.get("metric_id"), c.get("period"), c.get("subject_key"), c["title"],
                            last["case_id"] if last else None, (last["recurrence_no"] + 1) if last else 1, c["severity"], c["materiality"], c["recency"], c["actionability"],
                            bool(c.get("escalated")), score, json.dumps(c.get("evidence", {}), default=str), c.get("drill_link"), c.get("source_run_id"))).fetchone()
        conn.execute("INSERT INTO exception_event (case_id, event_type, to_status, actor_label) VALUES (%s, 'DETECTED', 'OPEN', 'system')", (row["case_id"],))
        out["created"] += 1
        out["recurrence_cases"] += 1 if last else 0
    conn.commit()
    return out


# --------------------------------------------------------------------------- user actions

ACTIONS = {
    "acknowledge": ("ACKNOWLEDGED", "ACKNOWLEDGED", WORKERS, False),
    "resolve": ("RESOLVED", "RESOLVED", WORKERS, False),
    "return": ("RETURNED", "OPEN", ("finance_reviewer", "controller", "admin", "fpa_manager"), True),
    "close": ("CLOSED", "CLOSED", ("finance_reviewer", "controller", "admin", "fpa_manager"), True),
    "reopen": ("REOPENED", "OPEN", ("finance_reviewer", "controller", "admin", "fpa_manager"), True),
}


def add_event(conn, actor: Actor, case_id: str, etype: str, to: str, comment=None, **cols) -> None:
    names = ["case_id", "event_type", "to_status", "actor_user_id", "comment"] + list(cols)
    vals = [case_id, etype, to, actor.user_id, comment] + list(cols.values())
    try:
        conn.execute(f"INSERT INTO exception_event ({', '.join(names)}) VALUES ({', '.join(['%s'] * len(names))})", vals)
    except psycopg.Error as e:
        conn.rollback()
        raise db_error(e) from None
    audit(conn, actor.email, "exception_" + etype.lower(), "exception_case", case_id, {"to_status": to, "comment": comment}, actor.user_id)


def act(conn, actor: Actor, case_id: str, action: str, comment: str | None, closure_reason: str | None = None) -> dict:
    if action not in ACTIONS:
        raise Problem("Unknown action.", 404)
    etype, to, roles, reason = ACTIONS[action]
    need(actor, roles, action + " exceptions")
    if reason and len((comment or "").strip()) < 10:
        raise Problem("Give a reason of at least 10 characters.")
    fetch(conn, case_id)
    cols = {"closure_reason": closure_reason} if etype == "CLOSED" else {}
    if etype == "CLOSED" and not closure_reason:
        raise Problem("Choose a closure reason: RESOLVED_FIXED, FALSE_POSITIVE, ACCEPTED_RISK, DUPLICATE, SOURCE_FIXED or OTHER.")
    add_event(conn, actor, case_id, etype, to, comment, **cols)
    conn.commit()
    return case_view(fetch(conn, case_id))


def assign(conn, actor: Actor, case_id: str, owner_id: str, due: str | None, next_action: str | None) -> dict:
    need(actor, ASSIGNERS, "assign exceptions")
    c = fetch(conn, case_id)
    if not conn.execute("SELECT 1 FROM app_user WHERE user_id = %s AND active AND role <> 'viewer'", (owner_id,)).fetchone():
        raise Problem("Choose an active user who can work on exceptions (not a viewer).")
    due_d = None
    if due:
        try:
            due_d = date.fromisoformat(due)
        except ValueError:
            raise Problem("The due date must look like 2026-10-31.") from None
        if due_d < date.today():
            raise Problem("The due date is in the past.")
    add_event(conn, actor, case_id, "REASSIGNED" if c["owner_user_id"] else "ASSIGNED", c["status"], None, new_owner_user_id=owner_id, new_due_date=due_d,
              new_next_action=(next_action or "").strip() or None)
    conn.commit()
    return case_view(fetch(conn, case_id))


def set_due(conn, actor: Actor, case_id: str, due: str) -> dict:
    need(actor, ASSIGNERS, "reschedule exceptions")
    c = fetch(conn, case_id)
    try:
        d = date.fromisoformat(due)
    except ValueError:
        raise Problem("The due date must look like 2026-10-31.") from None
    add_event(conn, actor, case_id, "DUE_DATE_CHANGED", c["status"], None, new_due_date=d)
    conn.commit()
    return case_view(fetch(conn, case_id))


def set_next_action(conn, actor: Actor, case_id: str, text: str) -> dict:
    need(actor, WORKERS, "update the next action")
    c = fetch(conn, case_id)
    if len((text or "").strip()) < 5:
        raise Problem("Describe the next action.")
    add_event(conn, actor, case_id, "ACTION_UPDATED", c["status"], None, new_next_action=text.strip())
    conn.commit()
    return case_view(fetch(conn, case_id))


def comment(conn, actor: Actor, case_id: str, text: str) -> dict:
    if len((text or "").strip()) < 3:
        raise Problem("Write a comment.")
    c = fetch(conn, case_id)
    add_event(conn, actor, case_id, "COMMENTED", c["status"], text.strip())
    conn.commit()
    return case_view(fetch(conn, case_id))


# --------------------------------------------------------------------------- reads

def listing(conn, status: str | None, domain: str | None, band: str | None, owner: str | None, mine: str | None, search: str | None, top: int | None, limit: int, offset: int) -> dict:
    """Ranked: escalated first, then final score. Default view is the top 20 open cases; everything else is searchable."""
    where, args = [], []
    where.append("status = %s" if status else "status <> 'CLOSED'")
    if status:
        args.append(status.upper())
    for col, val in (("domain", domain), ("band", band), ("owner_user_id", owner)):
        if val:
            where.append(f"{col} = %s")
            args.append(val.upper() if col != "owner_user_id" else val)
    if mine:
        where.append("owner_user_id = %s")
        args.append(mine)
    if search:
        where.append("(title ILIKE %s OR subject_key ILIKE %s OR exception_type ILIKE %s)")
        args += [f"%{search}%"] * 3
    w = "WHERE " + " AND ".join(where)
    total = conn.execute(f"SELECT count(*) AS n FROM exception_case {w}", args).fetchone()["n"]
    lim = min(top, limit) if top else limit
    rows = conn.execute(f"SELECT * FROM exception_case {w} ORDER BY escalated DESC, final_score DESC, first_detected_at LIMIT %s OFFSET %s", args + [lim, offset]).fetchall()
    summary = conn.execute("SELECT band, count(*) AS n FROM exception_case WHERE status <> 'CLOSED' GROUP BY band").fetchall()
    unowned = conn.execute("SELECT count(*) AS n FROM exception_case WHERE status <> 'CLOSED' AND owner_user_id IS NULL").fetchone()["n"]
    overdue = conn.execute("SELECT count(*) AS n FROM exception_case WHERE status <> 'CLOSED' AND due_date < current_date").fetchone()["n"]
    return {"total": total, "shown": len(rows), "bands": {r["band"]: r["n"] for r in summary}, "unowned": unowned, "overdue": overdue, "items": [case_view(r) for r in rows],
            "default_due_days": DEFAULT_DUE_DAYS, "score_note": "Uncalibrated score: 0.35 severity + 0.30 materiality + 0.15 recency + 0.20 actionability, times a persistence factor; to be calibrated on twelve months of history."}


def history(conn, case_id: str) -> list[dict]:
    fetch(conn, case_id)
    return [dict(r) for r in conn.execute("""SELECT e.seq, e.event_type, e.from_status, e.to_status, e.comment, e.closure_reason, e.new_due_date, e.new_next_action, e.at,
                                                    coalesce(u.email, e.actor_label) AS actor, coalesce(o.email, NULL) AS new_owner
                                             FROM exception_event e LEFT JOIN app_user u ON u.user_id = e.actor_user_id LEFT JOIN app_user o ON o.user_id = e.new_owner_user_id
                                             WHERE e.case_id = %s ORDER BY e.seq""", (case_id,)).fetchall()]


def lineage(conn, case_id: str) -> list[dict]:
    """The chain of earlier closed cases this one recurs from."""
    out, cur = [], fetch(conn, case_id)
    while cur["recurrence_of_case_id"]:
        cur = fetch(conn, str(cur["recurrence_of_case_id"]))
        out.append({"case_id": str(cur["case_id"]), "status": cur["status"], "closed_at": cur["closed_at"], "closure_reason": cur["closure_reason"], "recurrence_no": cur["recurrence_no"]})
    return out
