"""Month-end close readiness: can Finance trust and close this period? One checklist per entity and month, built from what the platform already governs: data load and
controls, provisions, adjustments, corrections, unmapped ledgers, intercompany, exceptions. Blockers (not a percentage) drive the decision.

Check status: PASS | ATTENTION (can close only with a reviewer override and comment) | BLOCKED (prevents the management close) | PENDING (a manual sign-off is due) | NA.
A sign-off or override records the fingerprint of the evidence the person saw; if the evidence changes afterwards the sign-off is stale and the item is open again.
The period moves only by event (migration 008): OPEN -> SOFT_CLOSED -> MANAGEMENT_CLOSED -> FINAL_CLOSED, and REOPENED by a controller with a reason."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal

import psycopg

from ..adjustments import templates as tpl
from ..adjustments.service import Problem, db_error, month_start
from ..auth.service import Actor, audit
from ..mgmt import service as msvc

D = Decimal
ENTITIES = ("SUBCO", "HOLDCO")
GOLD_ENTITY = {"SUBCO": "RETAIL", "HOLDCO": "VENTURES"}
UNMAPPED_BLOCK_CR = D("0.05")
MANUAL = ("intercompany", "pnl_certification")
TITLES = {
    "revenue_loaded": "Revenue loaded for the whole month", "cogs_loaded": "COGS loaded", "data_controls": "Data controls pass", "provisions": "Required provisions generated",
    "adjustments": "Adjustments approved", "corrections": "Corrections cleared", "unmapped": "Ledgers mapped to a management group", "intercompany": "Intercompany reconciliation signed off",
    "exceptions": "Critical exceptions handled", "pnl_certification": "Management P&L certified",
}
ORDER = list(TITLES)


def sig(evidence) -> str:
    return hashlib.sha256(json.dumps(evidence, sort_keys=True, default=str).encode()).hexdigest()[:16]


def chk(key: str, status: str, summary: str, evidence=None, link: str | None = None) -> dict:
    return {"key": key, "title": TITLES[key], "status": status, "summary": summary, "evidence": evidence or {}, "link": link, "manual": key in MANUAL}


def month_end(m: date) -> date:
    nxt = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    return nxt.fromordinal(nxt.toordinal() - 1)


def period_status(app, entity: str, m: date) -> str:
    r = app.execute("SELECT status FROM reporting_period_status WHERE entity = %s AND period = %s", (entity, m)).fetchone()
    return r["status"] if r else "OPEN"


# --------------------------------------------------------------------------- the checks

def gold_checks(gold, entity: str, m: date) -> list[dict]:
    key = m.strftime("%Y-%m")
    out = []
    with gold.session("pnl") as g:
        months, asof = msvc.available_months(g), msvc.as_of(g)
        complete = bool(asof and key in months and asof >= month_end(m))
        data_to = asof.isoformat() if asof else None
        ctx = msvc.run(g, key, key) if key in months else None
        book = ctx["book"] if ctx else None
        if entity == "HOLDCO":
            out.append(chk("revenue_loaded", "NA", "HoldCo has no store revenue."))
            out.append(chk("cogs_loaded", "NA", "HoldCo has no store COGS."))
        else:
            rev = book.cells.get((key, "SUBCO", "STORES", "revenue"), D(0)) if book else D(0)
            if key not in months:
                out.append(chk("revenue_loaded", "BLOCKED", f"{key} is not in the data yet.", {"month": key}))
            elif not complete:
                out.append(chk("revenue_loaded", "BLOCKED", f"The month is not complete: data runs to {data_to}.", {"month": key, "data_to": data_to}))
            else:
                out.append(chk("revenue_loaded", "PASS" if rev > 0 else "BLOCKED", f"Revenue {rev.quantize(D('0.01'))} Cr.", {"revenue_cr": str(rev.quantize(D('0.0001')))}, "/mgmt"))
            cg = book.cogs.get(key, D(0)) if book else D(0)
            out.append(chk("cogs_loaded", "PASS" if (cg > 0 and complete) else "BLOCKED", f"COGS {cg.quantize(D('0.01'))} Cr." if cg > 0 else "No COGS for the month.", {"cogs_cr": str(cg.quantize(D('0.0001')))}))
        fails = g.execute("SELECT control_id, dimension, variance FROM pnl.v_control WHERE verdict <> 'PASS' AND dimension = %s", (key,)).fetchall()
        out.append(chk("data_controls", "BLOCKED" if fails else "PASS", f"{len(fails)} control(s) fail for {key}." if fails else "Every control passes for the month.",
                       {"failing": [{"control": f["control_id"], "variance": str(f["variance"])} for f in fails]}, "/control/inbox"))
        exc = [e for e in (book.exceptions.values() if book else []) if key in e["months"] and abs(e["amount_cr"]) > 0]
        big = [e for e in exc if abs(e["amount_cr"]) >= UNMAPPED_BLOCK_CR]
        out.append(chk("unmapped", "BLOCKED" if big else "ATTENTION" if exc else "PASS",
                       f"{len(big)} material unmapped ledger(s)." if big else f"{len(exc)} small unmapped ledger(s)." if exc else "Every ledger has a management group.",
                       {"material": [{"ledger": e["ledger"], "net_cr": str(e["amount_cr"].quantize(D('0.0001')))} for e in big], "small": len(exc) - len(big)}, "/mgmt/mapping"))
        try:
            from ..gold import intercompany as ic
            d = ic.compute(g)
            carried_ok = d["loan"].get("carried_years_mirror", True) if d.get("loan") else True
            ev = {"carried_years_mirror": bool(carried_ok), "loan_variance_cr": str(d["controls"].get("loan_mirror_variance_cr")), "service_unmatched_cr": str(d["controls"].get("service_unmatched_cr"))}
            out.append(chk("intercompany", "BLOCKED" if not carried_ok else "PENDING", "The years both companies carry no longer mirror." if not carried_ok else "Review the intercompany tie, then sign it off.", ev, "/related-party"))
        except Exception:  # noqa: BLE001  not configured on this install
            out.append(chk("intercompany", "PENDING", "Intercompany is not configured here; sign off when reviewed outside the platform.", {}))
    return out


def app_checks(app, entity: str, m: date) -> list[dict]:
    key = m.strftime("%Y-%m")
    out = []
    cal = tpl.calendar(app, key, key)
    mine = [r for r in cal["rows"] if r["entity"] == entity]
    missing = [r["name"] for r in mine if r["cells"][key]["state"] in ("missing", "locked")]
    active = [r for r in mine if r["cells"][key]["state"] != "n/a"]
    out.append(chk("provisions", "NA" if not active else "BLOCKED" if missing else "PASS",
                   "No recurring provisions are due." if not active else f"Missing: {', '.join(missing)}." if missing else f"All {len(active)} due provisions exist.", {"missing": missing, "due": len(active)}, "/control/adjustments"))
    pend = app.execute("""SELECT status, count(*) AS n FROM adjustment WHERE reporting_month = %s AND (entity = %s OR entity = 'CONSOLIDATED') AND status IN ('DRAFT', 'REVIEW', 'APPROVED', 'REVERSAL_REQUESTED') GROUP BY status""", (m, entity)).fetchall()
    prov = app.execute("""SELECT count(*) AS n FROM adjustment WHERE reporting_month = %s AND entity = %s AND status IN ('ACTIVE', 'REVERSAL_REQUESTED') AND coalesce((metric_snapshot ->> 'partial_month')::boolean, false)""", (m, entity)).fetchone()["n"]
    npend = sum(r["n"] for r in pend)
    out.append(chk("adjustments", "ATTENTION" if (npend or prov) else "PASS", (f"{npend} adjustment(s) not yet active" if npend else "") + (" and " if npend and prov else "") + (f"{prov} on an incomplete basis month" if prov else "") or "Every adjustment of the month is active.",
                   {"pending": {r["status"]: r["n"] for r in pend}, "partial_basis": prov}, "/control/adjustments"))
    src = GOLD_ENTITY[entity]
    cor = app.execute("""SELECT r.status, count(DISTINCT r.request_id) AS n FROM correction_request r JOIN correction_line l USING (request_id)
                         WHERE r.source_entity = %s AND (l.original_month = %s OR l.corrected_month = %s) AND r.status IN ('SUBMITTED', 'APPROVED', 'SOURCE_REVIEW_REQUIRED', 'REVERSAL_REQUESTED') GROUP BY r.status""", (src, m, m)).fetchall()
    cs = {r["status"]: r["n"] for r in cor}
    out.append(chk("corrections", "BLOCKED" if cs.get("SOURCE_REVIEW_REQUIRED") else "ATTENTION" if cs else "PASS",
                   f"{cs.get('SOURCE_REVIEW_REQUIRED')} correction(s) need a source review." if cs.get("SOURCE_REVIEW_REQUIRED") else f"{sum(cs.values())} correction(s) pending." if cs else "No correction is pending for the month.", {"pending": cs}, "/control/corrections"))
    ex = app.execute("""SELECT count(*) AS n FROM exception_case WHERE status <> 'CLOSED' AND period = %s AND band = 'CRITICAL' AND (entity = %s OR entity IS NULL OR entity = 'CONSOLIDATED')""", (m, entity)).fetchone()["n"]
    out.append(chk("exceptions", "ATTENTION" if ex else "PASS", f"{ex} critical exception(s) still open for the month." if ex else "No critical exception is open for the month.", {"critical_open": ex}, "/control/inbox"))
    out.append(chk("pnl_certification", "PENDING", "A controller certifies the management P&L after the management close.", {"entity": entity, "month": key}))
    return out


def apply_signoffs(app, entity: str, m: date, checks: list[dict]) -> None:
    """Attach the latest sign-off to each check; a sign-off whose evidence fingerprint no longer matches is stale and does not count."""
    latest = {}
    for r in app.execute("SELECT DISTINCT ON (check_key) check_key, decision, evidence_sig, comment, at, actor_user_id FROM close_signoff WHERE entity = %s AND period = %s ORDER BY check_key, signoff_id DESC", (entity, m)).fetchall():
        latest[r["check_key"]] = r
    names = {r["user_id"]: r["email"] for r in app.execute("SELECT user_id, email FROM app_user").fetchall()}
    for c in checks:
        c["signature"] = sig(c["evidence"])
        s = latest.get(c["key"])
        c["signoff"] = None
        c["effective"] = c["status"]
        if s and s["decision"] != "WITHDRAWN":
            valid = s["evidence_sig"] == c["signature"]
            c["signoff"] = {"decision": s["decision"], "comment": s["comment"], "at": s["at"], "by": names.get(s["actor_user_id"]), "stale": not valid}
            if valid and c["status"] in ("ATTENTION", "PENDING"):
                c["effective"] = "PASS"
        # a BLOCKED item is never cleared by a sign-off: the cause must be fixed


def readiness(app, gold, entity: str, month: str) -> dict:
    if entity not in ENTITIES:
        raise Problem("Choose SUBCO or HOLDCO.")
    m = month_start(month)
    checks = (gold_checks(gold, entity, m) if gold is not None else []) + app_checks(app, entity, m)
    if gold is None:
        checks += [chk("revenue_loaded", "BLOCKED", "The finance data (gold_fpa) is not available.", {})]
    checks.sort(key=lambda c: ORDER.index(c["key"]))
    apply_signoffs(app, entity, m, checks)
    blockers = [c for c in checks if c["effective"] == "BLOCKED"]
    open_items = [c for c in checks if c["effective"] in ("ATTENTION", "PENDING")]
    applicable = [c for c in checks if c["effective"] != "NA"]
    passed = [c for c in applicable if c["effective"] == "PASS"]
    status = period_status(app, entity, m)
    prov = any(c["key"] in ("provisions", "adjustments", "corrections", "revenue_loaded") and c["effective"] != "PASS" and c["effective"] != "NA" for c in checks)
    ready_mgmt = not blockers and not [c for c in open_items if c["key"] != "pnl_certification"]
    return {"entity": entity, "month": month, "period_status": status, "outcome": "BLOCKED" if blockers else "NEEDS_ATTENTION" if open_items else "READY",
            "readiness_pct": round(100 * len(passed) / len(applicable)) if applicable else 100, "blockers": [{"key": c["key"], "title": c["title"], "summary": c["summary"]} for c in blockers],
            "management_pnl": "PROVISIONAL" if prov else "COMPLETE", "can_management_close": ready_mgmt and status == "SOFT_CLOSED", "can_final_close": status == "MANAGEMENT_CLOSED" and not blockers and not open_items,
            "checks": checks, "note": "Blockers decide the close; the percentage is secondary. A reviewer override or sign-off records the evidence it was based on and goes stale if the evidence changes."}


# --------------------------------------------------------------------------- sign-off and period actions

def signoff(app, gold, actor: Actor, entity: str, month: str, check_key: str, decision: str, comment: str) -> dict:
    r = readiness(app, gold, entity, month)
    c = next((x for x in r["checks"] if x["key"] == check_key), None)
    if c is None:
        raise Problem("Unknown checklist item.", 404)
    decision = decision.upper()
    if decision not in ("SIGNED_OFF", "OVERRIDDEN", "WITHDRAWN"):
        raise Problem("The decision is SIGNED_OFF, OVERRIDDEN or WITHDRAWN.")
    if len((comment or "").strip()) < 10:
        raise Problem("Write the comment or reason in at least 10 characters.")
    if decision != "WITHDRAWN":
        if c["status"] == "BLOCKED":
            raise Problem("A blocker cannot be signed off or overridden: fix its cause first.", 409)
        if c["status"] in ("PASS", "NA"):
            raise Problem("This item already passes; nothing to sign off.", 409)
        if c["manual"] and decision != "SIGNED_OFF":
            raise Problem("A manual checklist item is signed off, not overridden.")
        if not c["manual"] and decision != "OVERRIDDEN":
            raise Problem("An item with attention points is overridden with a comment.")
    try:
        app.execute("INSERT INTO close_signoff (entity, period, check_key, decision, evidence_sig, comment, actor_user_id) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (entity, month_start(month), check_key, decision, c["signature"], comment.strip(), actor.user_id))
    except psycopg.Error as e:
        app.rollback()
        raise db_error(e) from None
    audit(app, actor.email, "close_" + decision.lower(), "close_item", f"{entity}:{month}:{check_key}", {"comment": comment.strip()}, actor.user_id)
    app.commit()
    return readiness(app, gold, entity, month)


ACTIONS = {"soft-close": "SOFT_CLOSED", "management-close": "MANAGEMENT_CLOSED", "final-close": "FINAL_CLOSED", "reopen": "REOPENED"}


def period_action(app, gold, actor: Actor, entity: str, month: str, action: str, reason: str) -> dict:
    if action not in ACTIONS:
        raise Problem("Unknown action.", 404)
    r = readiness(app, gold, entity, month)
    m = month_start(month)
    if action == "soft-close":
        rev = next((c for c in r["checks"] if c["key"] == "revenue_loaded"), None)
        if rev and entity == "SUBCO" and rev["status"] == "BLOCKED" and "not complete" in rev["summary"]:
            raise Problem("The month is not complete yet, so it cannot be soft-closed.", 409)
    if action == "management-close" and not r["can_management_close"]:
        why = "; ".join(f"{b['title']}: {b['summary']}" for b in r["blockers"]) or "; ".join(f"{c['title']} is open" for c in r["checks"] if c["effective"] in ("ATTENTION", "PENDING") and c["key"] != "pnl_certification") or "the period must be soft-closed first"
        raise Problem("The management close is not allowed yet: " + why, 409)
    if action == "final-close" and not r["can_final_close"]:
        raise Problem("The final close needs the management close, no blocker and every item signed off, including the certification of the management P&L.", 409)
    try:
        app.execute("INSERT INTO reporting_period_event (entity, period, to_status, actor_user_id, reason) VALUES (%s, %s, %s, %s, %s)", (entity, m, ACTIONS[action], actor.user_id, reason or ""))
    except psycopg.Error as e:
        app.rollback()
        raise db_error(e) from None
    audit(app, actor.email, "period_" + action.replace("-", "_"), "reporting_period", f"{entity}:{month}", {"to_status": ACTIONS[action], "reason": reason}, actor.user_id)
    app.commit()
    return readiness(app, gold, entity, month)


def periods(app, from_month: str, to_month: str) -> list[dict]:
    lo, hi = month_start(from_month), month_start(to_month)
    rows = {(r["entity"], r["period"]): r for r in app.execute("SELECT entity, period, status, changed_at FROM reporting_period_status WHERE period BETWEEN %s AND %s", (lo, hi)).fetchall()}
    out, y, mo = [], lo.year, lo.month
    while date(y, mo, 1) <= hi:
        d = date(y, mo, 1)
        out.append({"month": d.strftime("%Y-%m"), **{e.lower(): (rows[(e, d)]["status"] if (e, d) in rows else "OPEN") for e in ENTITIES}})
        y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    return out


def period_history(app, entity: str, month: str) -> list[dict]:
    return [dict(r) for r in app.execute("""SELECT e.from_status, e.to_status, e.reason, e.at, u.email AS actor FROM reporting_period_event e LEFT JOIN app_user u ON u.user_id = e.actor_user_id
                                            WHERE e.entity = %s AND e.period = %s ORDER BY e.event_id""", (entity, month_start(month))).fetchall()]
