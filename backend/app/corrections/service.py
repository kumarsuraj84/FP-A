"""Corrections: reclassification of existing finance lines (management group and/or expense month). No amount is ever entered: the amount stays in gold_fpa.

A request has one or more lines. Scope LINE = one line; VOUCHER = every P&L line of one voucher entry (expanded into line children); BULK = several lines with the SAME
target. Each line stores the source key (gold entity + cost_tag_key), a fingerprint of the immutable finance fields (v1, computed here from gold), an audit copy of the
amount, and the original and corrected group and month. The fingerprint is re-read from gold at APPROVE and ACTIVATE and by the source check; a difference stops the
action with 'source changed'. All state changes are events; the database validates transition, maker-checker, period lock (original AND corrected month) and freezing.
"""
from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

import psycopg

from ..adjustments.service import Problem, db_error, month_start
from ..auth.service import Actor, audit
from ..mgmt import config as cfg
from . import overlay as ov

CR = Decimal(10_000_000)
MAKERS = ("fpa_manager", "controller", "admin")
CHECKERS = ("fpa_manager", "finance_reviewer", "controller", "admin")
REASONS = ("WRONG_CLASSIFICATION", "WRONG_MONTH", "LATE_INVOICE_TIMING", "WRONG_SOURCE_MAPPING", "MANAGEMENT_RECLASSIFICATION", "OTHER")
ENTITIES = ("RETAIL", "VENTURES")
FP_VERSION = "v1"
P_L_GROUPS = sorted(g for g in cfg.KEY_OF_GROUP)


def _amt(x) -> str:
    """Amounts in the fingerprint: null is zero and the scale does not matter (100 and 100.00 are the same line)."""
    d = Decimal(x or 0)
    return format(d.quantize(Decimal(1)) if d == d.to_integral() else d.normalize(), "f")


def fingerprint(g: dict) -> str:
    """v1: sha256 over the immutable finance fields of the line, joined with a unit separator. Release status is NOT part of it (it legitimately moves unposted -> posted)."""
    parts = (g["entity"], g["cost_tag_key"], g["glcode"], g["tag_site_code"], g["entdt"].isoformat(), _amt(g["damount"]), _amt(g["camount"]), g["entcode"])
    return hashlib.sha256("\x1f".join("" if p is None else str(p) for p in parts).encode()).hexdigest()


def need(actor: Actor, roles: tuple, what: str) -> None:
    if actor.role not in roles:
        raise Problem(f"Your role ({actor.role}) cannot {what}.", 403)


def need_gold(gold) -> None:
    if gold is None:
        raise Problem("The finance data (gold_fpa) is not available, so source lines cannot be read. Start the API with FPA_SOURCE=gold.", 503)


def gold_lines(gold, entity: str, keys: list[int] | None = None, voucher: str | None = None) -> list[dict]:
    need_gold(gold)
    with gold.session("pnl") as g:
        if voucher:
            return g.execute("""SELECT cost_tag_key, entity, entcode, entdt, glcode, glname, fin_group, tag_site_code, site_kind, damount, camount, profit_effect
                                FROM gold_fpa.voucher_lines WHERE entity = %s AND entcode = %s AND cost_tag_key IS NOT NULL ORDER BY cost_tag_key""", (entity, voucher)).fetchall()
        return g.execute(ov.GOLD_LINE_SQL, (entity, keys or [])).fetchall()


def describe(g: dict, lmap: dict, site_loc: dict) -> dict | None:
    """The correctable facts of a source line, or None when it is not a P&L line (excluded ledger, unmapped group, unknown location)."""
    grp = ov.line_group(g, lmap)
    key = cfg.KEY_OF_GROUP.get(grp) if grp and grp != cfg.EXCLUDED else None
    loc = ov.location_of(g, site_loc)
    if key is None or loc is None:
        return None
    return {"group": grp, "key": key, "location_type": loc, "month": g["entdt"].replace(day=1)}


def line_view(r: dict) -> dict:
    out = {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in r.items()}
    out["source_amount_cr"] = (Decimal(r["source_amount_snapshot"]) / CR).quantize(Decimal("0.0001"))
    out["original_month"] = r["original_month"].strftime("%Y-%m")
    out["corrected_month"] = r["corrected_month"].strftime("%Y-%m") if r["corrected_month"] else None
    return out


def view(conn, request_id: str, with_lines: bool = True) -> dict:
    r = conn.execute("SELECT * FROM correction_request WHERE request_id = %s", (request_id,)).fetchone()
    if r is None:
        raise Problem("No such correction.", 404)
    out = {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in r.items()}
    n = conn.execute("SELECT count(*) AS n, coalesce(sum(source_amount_snapshot), 0) AS total FROM correction_line WHERE request_id = %s", (request_id,)).fetchone()
    out["line_count"], out["source_total_cr"] = n["n"], (Decimal(n["total"]) / CR).quantize(Decimal("0.0001"))
    out["counts_in_management_total"] = r["status"] in ("ACTIVE", "REVERSAL_REQUESTED")
    if with_lines:
        out["lines"] = [line_view(x) for x in conn.execute("SELECT * FROM correction_line WHERE request_id = %s ORDER BY created_at, source_line_key", (request_id,)).fetchall()]
    return out


def event(conn, actor: Actor, request_id: str, etype: str, to: str, comment: str | None = None) -> None:
    try:
        conn.execute("INSERT INTO correction_event (request_id, event_type, to_status, actor_user_id, comment) VALUES (%s, %s, %s, %s, %s)", (request_id, etype, to, actor.user_id, comment))
    except psycopg.Error as e:
        conn.rollback()
        raise db_error(e) from None
    audit(conn, actor.email, "correction_" + etype.lower(), "correction_request", str(request_id), {"to_status": to, "comment": comment}, actor.user_id)


# --------------------------------------------------------------------------- create

def create(conn, gold, actor: Actor, p: dict) -> dict:
    need(actor, MAKERS, "create corrections")
    entity = str(p.get("source_entity", "")).upper()
    if entity not in ENTITIES:
        raise Problem("Choose the books: RETAIL (SubCo) or VENTURES (HoldCo).")
    scope = str(p.get("scope", "LINE")).upper()
    if scope not in ("LINE", "VOUCHER", "BULK"):
        raise Problem("The scope is LINE, VOUCHER or BULK.")
    cg = (p.get("corrected_group") or None)
    cm = month_start(p["corrected_month"]) if p.get("corrected_month") else None
    if cg is None and cm is None:
        raise Problem("Choose a corrected management group, a corrected expense month, or both.")
    if cg is not None and cg not in cfg.KEY_OF_GROUP:
        raise Problem("The corrected group is not a Management P&L group.")
    ctype = "BOTH" if cg and cm else ("GROUP" if cg else "EXPENSE_MONTH")
    reason = str(p.get("reason_code", "")).upper()
    if reason not in REASONS:
        raise Problem("Choose a reason code: " + ", ".join(REASONS) + ".")
    text, evidence = str(p.get("reason_text", "")).strip(), str(p.get("evidence_reference", "")).strip()
    if len(text) < 10:
        raise Problem("Explain the reason in at least 10 characters.")
    if len(evidence) < 3:
        raise Problem("Give the evidence reference (ticket, email, document).")
    if reason == "OTHER" and len(text) < 30:
        raise Problem("A reason code of OTHER needs a fuller explanation (at least 30 characters).")
    if scope == "VOUCHER":
        src = gold_lines(gold, entity, voucher=str(p.get("voucher", "")).strip())
        if not src:
            raise Problem("No P&L lines found for that voucher.", 404)
    else:
        try:
            keys = sorted({int(k) for k in p.get("line_keys", [])})
        except (TypeError, ValueError):
            raise Problem("Line keys are numbers (cost_tag_key).") from None
        if not keys or (scope == "LINE" and len(keys) != 1):
            raise Problem("A LINE correction has exactly one line; a BULK correction has one or more with the same target.")
        if len(keys) > 500:
            raise Problem("At most 500 lines in one request.")
        src = gold_lines(gold, entity, keys)
        if len(src) != len(keys):
            raise Problem("Some lines do not exist in the finance data: " + ", ".join(str(k) for k in set(keys) - {s["cost_tag_key"] for s in src}), 404)
    lmap, sloc = cfg.ledger_map(), cfg.site_loc()
    lines, skipped = [], []
    for g in src:
        d = describe(g, lmap, sloc)
        if d is None:
            skipped.append(g["cost_tag_key"])
            continue
        new_g = cg if cg and cg != d["group"] else None
        new_m = cm if cm and cm != d["month"] else None
        if new_g is None and new_m is None:
            skipped.append(g["cost_tag_key"])
            continue
        lines.append((g, d, new_g, new_m))
    if not lines:
        raise Problem("Nothing to correct: the lines are not Management P&L lines, or already have that group and month.")
    if scope == "VOUCHER" and skipped:
        pass                                    # a voucher expands into its P&L lines; non-P&L lines are simply not part of the correction
    elif skipped:
        raise Problem("These lines cannot be corrected (not a P&L line, or already in that group and month): " + ", ".join(str(k) for k in skipped))
    try:
        rid = str(conn.execute("""INSERT INTO correction_request (scope_type, correction_type, source_entity, reason_code, reason_text, evidence_reference, requested_by, created_by)
                                  VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING request_id""", (scope, ctype, entity, reason, text, evidence, actor.user_id, actor.user_id)).fetchone()["request_id"])
        for g, d, new_g, new_m in lines:
            conn.execute("""INSERT INTO correction_line (request_id, source_entity, source_line_key, fingerprint, fingerprint_version, source_amount_snapshot, voucher_key, ledger_key, site_code,
                                original_group, corrected_group, original_month, corrected_month) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                         (rid, entity, str(g["cost_tag_key"]), fingerprint(g), FP_VERSION, Decimal(g["profit_effect"]).quantize(Decimal("0.0001")), g["entcode"], str(g["glcode"]),
                          str(g["tag_site_code"]) if g["tag_site_code"] is not None else None, d["group"], new_g, d["month"], new_m))
    except psycopg.Error as e:
        conn.rollback()
        raise db_error(e) from None
    event(conn, actor, rid, "CREATED", "DRAFT")
    conn.commit()
    return view(conn, rid)


# --------------------------------------------------------------------------- source check and actions

def check_lines(conn, gold, request_id: str) -> dict:
    """Re-read every line from gold and compare the fingerprint. -> {state: UNCHANGED | NOW_MATCHES | CHANGED_DIFFERENTLY | ORPHANED, details}. Records source_state on each line."""
    need_gold(gold)
    req = conn.execute("SELECT source_entity FROM correction_request WHERE request_id = %s", (request_id,)).fetchone()
    if req is None:
        raise Problem("No such correction.", 404)
    lines = conn.execute("SELECT * FROM correction_line WHERE request_id = %s", (request_id,)).fetchall()
    src = {g["cost_tag_key"]: g for g in gold_lines(gold, req["source_entity"], [int(x["source_line_key"]) for x in lines])}
    lmap, sloc = cfg.ledger_map(), cfg.site_loc()
    states, detail = [], []
    for ln in lines:
        g = src.get(int(ln["source_line_key"]))
        if g is None:
            st = "ORPHANED"
        elif fingerprint(g) == ln["fingerprint"]:
            d = describe(g, lmap, sloc)
            same_group = ln["corrected_group"] is None or (d is not None and d["group"] == ln["corrected_group"])
            same_month = ln["corrected_month"] is None or (d is not None and d["month"] == ln["corrected_month"])
            st = "NOW_MATCHES" if d is not None and d["group"] != ln["original_group"] and same_group and same_month else (
                "CHANGED_DIFFERENTLY" if d is not None and (d["group"] != ln["original_group"] or d["month"] != ln["original_month"]) else "UNCHANGED")
        else:
            st = "CHANGED_DIFFERENTLY"
        conn.execute("UPDATE correction_line SET source_state = %s WHERE line_id = %s", (st, ln["line_id"]))
        states.append(st)
        if st != "UNCHANGED":
            detail.append({"source_line_key": ln["source_line_key"], "state": st})
    overall = ("ORPHANED" if "ORPHANED" in states else "CHANGED_DIFFERENTLY" if "CHANGED_DIFFERENTLY" in states else "NOW_MATCHES" if states and all(s == "NOW_MATCHES" for s in states) else "UNCHANGED")
    return {"state": overall, "details": detail}


ACTIONS = {
    "submit": ("SUBMITTED", "SUBMITTED", MAKERS, False, "submit corrections", False),
    "approve": ("APPROVED", "APPROVED", CHECKERS, False, "approve corrections", True),
    "activate": ("ACTIVATED", "ACTIVE", CHECKERS, False, "activate corrections", True),
    "reject": ("REJECTED", "REJECTED", CHECKERS, True, "reject corrections", False),
    "withdraw": ("WITHDRAWN", "WITHDRAWN", MAKERS, False, "withdraw corrections", False),
    "void": ("VOIDED", "WITHDRAWN", CHECKERS, True, "void an approved correction", False),
    "request-reversal": ("REVERSAL_REQUESTED", "REVERSAL_REQUESTED", MAKERS, True, "request a reversal", False),
    "approve-reversal": ("REVERSAL_APPROVED", "REVERSED", CHECKERS, False, "approve a reversal", False),
    "reject-reversal": ("REVERSAL_REJECTED", "ACTIVE", CHECKERS, True, "reject a reversal", False),
    "reconfirm-source": ("SOURCE_RECONFIRMED", "ACTIVE", CHECKERS, True, "reconfirm a correction after a source change", True),
}


def act(conn, gold, actor: Actor, request_id: str, action: str, comment: str | None) -> dict:
    if action not in ACTIONS:
        raise Problem("Unknown action.", 404)
    etype, to, roles, reason, what, recheck = ACTIONS[action]
    need(actor, roles, what)
    if reason and len((comment or "").strip()) < 10:
        raise Problem("Give a reason of at least 10 characters.")
    if recheck:
        res = check_lines(conn, gold, request_id)
        if res["state"] != "UNCHANGED" and action != "reconfirm-source":
            conn.commit()                              # keep the source_state that the check recorded
            raise Problem("Source changed: the finance line no longer matches what was requested (" + res["state"] + "); the correction needs review.", 409)
    event(conn, actor, request_id, etype, to, comment)
    conn.commit()
    return view(conn, request_id)


def source_check(conn, gold, actor: Actor) -> dict:
    """Walk every ACTIVE correction: SOURCE_CHANGED pauses the overlay, SOURCE_NOW_MATCHES supersedes it. Run after each data refresh (admin, controller or manager)."""
    need(actor, MAKERS, "run the source check")
    out = {"checked": 0, "changed": [], "superseded": []}
    for r in conn.execute("SELECT request_id FROM correction_request WHERE status IN ('ACTIVE', 'SOURCE_REVIEW_REQUIRED') ORDER BY requested_at").fetchall():
        rid = str(r["request_id"])
        res = check_lines(conn, gold, rid)
        status = conn.execute("SELECT status FROM correction_request WHERE request_id = %s", (rid,)).fetchone()["status"]
        out["checked"] += 1
        if res["state"] == "NOW_MATCHES":
            event(conn, actor, rid, "SOURCE_NOW_MATCHES", "SUPERSEDED_BY_SOURCE", "The finance data now carries the corrected classification; the overlay is no longer needed.")
            out["superseded"].append(rid)
        elif res["state"] in ("CHANGED_DIFFERENTLY", "ORPHANED") and status == "ACTIVE":
            event(conn, actor, rid, "SOURCE_CHANGED", "SOURCE_REVIEW_REQUIRED", "Source " + res["state"].lower().replace("_", " ") + " since the correction was approved.")
            out["changed"].append(rid)
        conn.commit()
    return out


# --------------------------------------------------------------------------- impact preview, list, history

def preview(conn, gold, request_id: str) -> dict:
    """Before / reclass / after by management group and by month for the lines of a request, from the finance amounts. Net zero is shown, not assumed."""
    need_gold(gold)
    lines = conn.execute("SELECT * FROM correction_line WHERE request_id = %s", (request_id,)).fetchall()
    if not lines:
        raise Problem("No such correction, or it has no lines.", 404)
    req = conn.execute("SELECT source_entity FROM correction_request WHERE request_id = %s", (request_id,)).fetchone()
    src = {g["cost_tag_key"]: g for g in gold_lines(gold, req["source_entity"], [int(x["source_line_key"]) for x in lines])}
    by_group, by_month, stores = defaultdict(Decimal), defaultdict(Decimal), set()
    for ln in lines:
        g = src.get(int(ln["source_line_key"]))
        if g is None:
            raise Problem("A source line no longer exists: Source changed.", 409)
        a = Decimal(g["profit_effect"]) / CR
        og, om = ln["original_group"], ln["original_month"].strftime("%Y-%m")
        ng, nm = ln["corrected_group"] or og, ln["corrected_month"].strftime("%Y-%m") if ln["corrected_month"] else om
        by_group[og] -= a
        by_group[ng] += a
        by_month[om] -= a
        by_month[nm] += a
        if ln["site_code"]:
            stores.add(ln["site_code"])
    q = lambda x: x.quantize(Decimal("0.0001"))  # noqa: E731
    return {"lines": len(lines), "stores": len(stores), "source_total_cr": q(sum((Decimal(src[int(x["source_line_key"])]["profit_effect"]) for x in lines), Decimal(0)) / CR),
            "by_group": {k: q(v) for k, v in sorted(by_group.items())}, "by_month": {k: q(v) for k, v in sorted(by_month.items())},
            "net_by_group_cr": q(sum(by_group.values(), Decimal(0))), "net_by_month_cr": q(sum(by_month.values(), Decimal(0))),
            "note": "Movement in crore in the profit-effect sign (a cost moved INTO a group makes that group more negative). Both nets are zero: a correction never changes the total."}


def listing(conn, status: str | None, entity: str | None, limit: int, offset: int) -> dict:
    where, args = [], []
    for col, val in (("status", status), ("source_entity", entity)):
        if val:
            where.append(f"{col} = %s")
            args.append(val)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    counts = {r["status"]: r["n"] for r in conn.execute("SELECT status, count(*) AS n FROM correction_request GROUP BY status").fetchall()}
    total = conn.execute(f"SELECT count(*) AS n FROM correction_request {w}", args).fetchone()["n"]
    ids = [str(r["request_id"]) for r in conn.execute(f"SELECT request_id FROM correction_request {w} ORDER BY requested_at DESC LIMIT %s OFFSET %s", args + [limit, offset]).fetchall()]
    return {"total": total, "counts": counts, "items": [view(conn, i, with_lines=False) for i in ids]}


def history(conn, request_id: str) -> list[dict]:
    view(conn, request_id, with_lines=False)
    return [dict(r) for r in conn.execute("""SELECT e.seq, e.event_type, e.from_status, e.to_status, e.comment, e.at, u.email AS actor_email, u.display_name AS actor_name
                                             FROM correction_event e LEFT JOIN app_user u ON u.user_id = e.actor_user_id WHERE e.request_id = %s ORDER BY e.seq""", (request_id,)).fetchall()]
