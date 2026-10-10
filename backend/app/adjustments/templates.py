"""Recurring provisions: templates that generate independent monthly adjustment rows, and the provision calendar.

A template is a definition (entity, line, location, type, FIXED amount or RATE on a metric, start and end month, policy, owner). Generating a month creates an ordinary
adjustment row for it (DRAFT, then submitted to REVIEW), so the report always reads the exact amount used for the month, never the template. A month that is closed is
reported as period-locked and is never silently moved forward. Generation on a basis month that is not complete is allowed and flagged provisional (the snapshot says so).
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import psycopg

from ..auth.service import Actor, audit
from . import service as svc
from .service import Problem


def tview(r: dict) -> dict:
    out = {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in r.items()}
    out["start_month"] = r["start_month"].strftime("%Y-%m")
    out["end_month"] = r["end_month"].strftime("%Y-%m") if r["end_month"] else None
    out["last_generated_month"] = r["last_generated_month"].strftime("%Y-%m") if r["last_generated_month"] else None
    return out


def fetch(conn, template_id: str) -> dict:
    r = conn.execute("SELECT * FROM adjustment_template WHERE template_id = %s", (template_id,)).fetchone()
    if r is None:
        raise Problem("No such template.", 404)
    return r


def create(conn, actor: Actor, p: dict) -> dict:
    svc.need(actor, svc.MAKERS, "create provision templates")
    p = {**p, "month": p.get("start_month", "")}
    shape = svc.validate_shape(p)
    if shape["basis_type"] == "MANUAL":
        raise Problem("A template is FIXED or RATE; manual amounts are one-off adjustments.")
    end = svc.month_start(p["end_month"]) if p.get("end_month") else None
    if end and end < shape["reporting_month"]:
        raise Problem("The end month is before the start month.")
    if shape["basis_type"] == "FIXED":
        amount = svc.signed(shape["effect"], shape["entered"])
        rate = metric = None
    else:
        amount, rate, metric = None, shape["rate"], shape["rate_metric"]
    try:
        r = conn.execute("""INSERT INTO adjustment_template (name, entity, management_line, location_type, location_code, adjustment_type, basis_type, fixed_amount_rupees, rate, rate_metric,
                              start_month, end_month, linked_policy, owner_user_id, created_by, effect)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
                         (str(p.get("name", "")).strip() or shape["management_line"], shape["entity"], shape["management_line"], shape["location_type"], shape["location_code"],
                          shape["adjustment_type"], shape["basis_type"], amount, rate, metric, shape["reporting_month"], end, shape["linked_policy"], actor.user_id, actor.user_id, shape["effect"])).fetchone()
    except psycopg.Error as e:
        conn.rollback()
        raise svc.db_error(e) from None
    audit(conn, actor.email, "template_created", "adjustment_template", str(r["template_id"]), {"name": r["name"]}, actor.user_id)
    conn.commit()
    return tview(r)


def listing(conn) -> list[dict]:
    return [tview(r) for r in conn.execute("SELECT * FROM adjustment_template ORDER BY name").fetchall()]


def change_status(conn, actor: Actor, template_id: str, action: str) -> dict:
    t = fetch(conn, template_id)
    ok = {"approve": ("DRAFT", "ACTIVE", svc.CHECKERS), "pause": ("ACTIVE", "PAUSED", svc.MAKERS), "resume": ("PAUSED", "ACTIVE", svc.MAKERS), "retire": (None, "RETIRED", svc.MAKERS)}
    if action not in ok:
        raise Problem("Unknown action.", 404)
    frm, to, roles = ok[action]
    svc.need(actor, roles, action + " templates")
    if frm and t["status"] != frm:
        raise Problem(f"The template is {t['status']}; it must be {frm} to {action}.", 409)
    if t["status"] == "RETIRED":
        raise Problem("A retired template stays retired.", 409)
    if action == "approve":
        single = conn.execute("SELECT value = 'on' AS on_ FROM app_setting WHERE key = 'single_user_mode'").fetchone()
        if str(t["created_by"]) == actor.user_id and not (single and single["on_"]):
            raise Problem("The creator of a template cannot approve it (maker-checker).", 403)
        conn.execute("UPDATE adjustment_template SET status = 'ACTIVE', approved_by = %s, approved_at = now() WHERE template_id = %s", (actor.user_id, template_id))
    else:
        conn.execute("UPDATE adjustment_template SET status = %s WHERE template_id = %s", (to, template_id))
    audit(conn, actor.email, "template_" + action, "adjustment_template", template_id, {"to_status": to}, actor.user_id)
    conn.commit()
    return tview(fetch(conn, template_id))


def covers(t: dict, month: date) -> bool:
    return t["start_month"] <= month and (t["end_month"] is None or month <= t["end_month"])


def generate(conn, gold, actor: Actor, month: str) -> dict:
    """One adjustment per ACTIVE template that covers the month and has none yet. Returns what was created and what was skipped, with the reason."""
    svc.need(actor, svc.MAKERS, "generate provisions")
    m = svc.month_start(month)
    created, skipped = [], []
    for t in conn.execute("SELECT * FROM adjustment_template WHERE status = 'ACTIVE' ORDER BY name").fetchall():
        tid = str(t["template_id"])
        if not covers(t, m):
            continue
        if conn.execute("SELECT 1 FROM adjustment WHERE template_id = %s AND reporting_month = %s AND status NOT IN ('REJECTED', 'WITHDRAWN', 'REVERSED')", (tid, m)).fetchone():
            skipped.append({"template": t["name"], "reason": "already generated"})
            continue
        if not conn.execute("SELECT fpa_app.period_is_writable(%s, %s) AS ok", (t["entity"], m)).fetchone()["ok"]:
            skipped.append({"template": t["name"], "reason": "period locked: a controller must reopen the month"})
            continue
        shape = {"reporting_month": m, "entity": t["entity"], "management_line": t["management_line"], "location_type": t["location_type"], "location_code": t["location_code"],
                 "adjustment_type": t["adjustment_type"], "basis_type": t["basis_type"], "supporting_reference": f"Template {t['name']}", "narrative": f"Generated from the recurring template {t['name']} for {month}.",
                 "linked_policy": t["linked_policy"], "effect": t["effect"]}
        try:
            if t["basis_type"] == "FIXED":
                shape["entered"] = abs(Decimal(t["fixed_amount_rupees"]))
                derived = svc.derive(shape, None)
            else:
                shape["rate"], shape["rate_metric"] = t["rate"], t["rate_metric"]
                derived = svc.derive(shape, svc.metric_snapshot(gold, t["entity"], m, t["rate_metric"]))
            aid = svc.insert(conn, actor, shape, derived, template_id=tid)
            svc.event(conn, actor, aid, "SUBMITTED", "REVIEW")
            conn.execute("UPDATE adjustment_template SET last_generated_month = greatest(coalesce(last_generated_month, %s), %s) WHERE template_id = %s", (m, m, tid))
            conn.commit()
            created.append({"template": t["name"], "adjustment_id": aid, "provisional": bool((derived[3] or {}).get("partial_month"))})
        except Problem as e:
            conn.rollback()
            skipped.append({"template": t["name"], "reason": e.message})
    return {"month": month, "created": created, "skipped": skipped}


def calendar(conn, from_month: str, to_month: str, today: date | None = None) -> dict:
    """Template x month grid. Cell states: active, proposed (draft, review or approved), missing (due, nothing exists), future, locked (month closed), n/a (outside the template)."""
    lo, hi = svc.month_start(from_month), svc.month_start(to_month)
    if hi < lo or (hi.year - lo.year) * 12 + hi.month - lo.month > 35:
        raise Problem("Choose a window of at most 36 months.")
    today = today or date.today()
    cur = date(today.year, today.month, 1)
    months, y, mo = [], lo.year, lo.month
    while date(y, mo, 1) <= hi:
        months.append(date(y, mo, 1))
        y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    rows = []
    adj = {}
    for a in conn.execute("SELECT adjustment_id, template_id, reporting_month, status, adjustment_amount_rupees FROM adjustment WHERE template_id IS NOT NULL AND reporting_month BETWEEN %s AND %s "
                          "AND status NOT IN ('REJECTED', 'WITHDRAWN', 'REVERSED')", (lo, hi)).fetchall():
        adj[(str(a["template_id"]), a["reporting_month"])] = a
    locked = {(r["entity"], r["period"]) for r in conn.execute("SELECT entity, period FROM reporting_period_status WHERE status IN ('MANAGEMENT_CLOSED', 'FINAL_CLOSED') AND period BETWEEN %s AND %s", (lo, hi)).fetchall()}
    for t in conn.execute("SELECT * FROM adjustment_template WHERE status IN ('ACTIVE', 'PAUSED') ORDER BY name").fetchall():
        cells = {}
        for m in months:
            a = adj.get((str(t["template_id"]), m))
            if not covers(t, m):
                st = "n/a"
            elif a is not None:
                st = "active" if a["status"] in ("ACTIVE", "REVERSAL_REQUESTED") else "proposed"
            elif (t["entity"], m) in locked:
                st = "locked"
            elif m > cur:
                st = "future"
            elif t["status"] == "PAUSED":
                st = "paused"
            else:
                st = "missing"
            cells[m.strftime("%Y-%m")] = {"state": st, "adjustment_id": str(a["adjustment_id"]) if a else None,
                                          "amount_cr": (a["adjustment_amount_rupees"] / svc.CR).quantize(Decimal("0.0001")) if a else None}
        rows.append({"template_id": str(t["template_id"]), "name": t["name"], "entity": t["entity"], "line": t["management_line"], "status": t["status"], "cells": cells})
    rows.sort(key=lambda r: (-sum(c["state"] == "missing" for c in r["cells"].values()), r["name"]))     # missing first
    return {"months": [m.strftime("%Y-%m") for m in months], "rows": rows, "legend": ["active", "proposed", "missing", "future", "locked", "paused", "n/a"]}
