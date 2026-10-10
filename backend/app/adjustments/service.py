"""Adjustments and Provisions: business logic over the fpa_app tables (migrations 002 and 003).

Amounts are entered as a positive magnitude plus an EFFECT on profit (COST reduces profit, INCOME raises it) and stored in the management engine's line sign
(profit-effect sign: a cost provision is negative). RATE adjustments take the rate and a basis metric from the management engine; the amount is derived, previewed at
create, and FROZEN at submit (the basis is re-read at submit; from SUBMITTED on, the snapshot never changes; to change it, reverse and create a new one).
All state changes are INSERTs into adjustment_event; the database validates the transition, maker-checker, period lock and field freezing, and this layer maps its
errors to plain messages. Every action is also written to audit_event.
"""
from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

import psycopg

from ..auth.service import Actor, audit
from ..mgmt import app_register
from ..mgmt import engine as eng
from ..mgmt import service as msvc

CR = Decimal(10_000_000)
TYPES = ("PROVISION", "MANAGEMENT_JOURNAL", "INCOME_ADJUSTMENT", "ONE_TIME", "INTERCOMPANY_ELIMINATION", "COGS_MANAGEMENT_CORRECTION")
BASES = ("FIXED", "RATE", "MANUAL")
ENTITIES = ("SUBCO", "HOLDCO", "CONSOLIDATED")
LOCATIONS = ("STORES", "DC", "HO")
EFFECTS = ("COST", "INCOME")
METRICS = {"net_sales": "Net sales of the store sites (revenue from operations)", "material_cost": "Material cost of the store sites"}
LINE_KEYS = {k for k, _, _, f in eng.LINES if f[0] == "atom"}
MAKERS = ("fpa_manager", "controller", "admin")                       # may create, edit a draft, submit, withdraw, request a reversal
CHECKERS = ("fpa_manager", "finance_reviewer", "controller", "admin")  # may approve, activate, reject (the database enforces maker-checker when single_user_mode is off)


class Problem(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message, self.status = message, status


def month_start(m: str) -> date:
    try:
        y, mo = int(m[:4]), int(m[5:7])
        if len(m) != 7 or m[4] != "-" or not 1 <= mo <= 12:
            raise ValueError
        return date(y, mo, 1)
    except (ValueError, IndexError):
        raise Problem("The month must look like 2026-10.") from None


def money(v, name: str = "amount") -> Decimal:
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise Problem(f"The {name} is not a number.") from None
    if not d.is_finite() or d <= 0 or d > Decimal("1000000000000"):
        raise Problem(f"The {name} must be a positive number of rupees (the effect says whether it is a cost or income).")
    return d.quantize(Decimal("0.0001"))


def signed(effect: str, magnitude: Decimal) -> Decimal:
    return -magnitude if effect == "COST" else magnitude


def db_error(e: psycopg.Error) -> Problem:
    msg = (e.diag.message_primary or str(e)).split("\n")[0]
    if isinstance(e, psycopg.errors.InsufficientPrivilege):
        return Problem(msg, 403)
    if isinstance(e, psycopg.errors.UniqueViolation):
        return Problem("An adjustment for this template and month already exists.", 409)
    if isinstance(e, (psycopg.errors.CheckViolation, psycopg.errors.NotNullViolation, psycopg.errors.ForeignKeyViolation)):
        return Problem(msg, 422)
    return Problem("The database refused the change.", 500)


# --------------------------------------------------------------------------- validation and the rate basis

def validate_shape(p: dict) -> dict:
    out = {}
    out["reporting_month"] = month_start(p.get("month", ""))
    for key, allowed, label in (("entity", ENTITIES, "entity"), ("location_type", LOCATIONS, "location type"), ("adjustment_type", TYPES, "adjustment type"), ("basis_type", BASES, "basis")):
        v = str(p.get(key, "")).upper()
        if v not in allowed:
            raise Problem(f"Choose a valid {label}.")
        out[key] = v
    line = str(p.get("management_line", ""))
    if line not in LINE_KEYS or eng.line_targets(out["location_type"], line) is None:
        raise Problem("Choose a management line that exists for that location type.")
    out["management_line"] = line
    if out["entity"] == "CONSOLIDATED" and out["adjustment_type"] != "INTERCOMPANY_ELIMINATION":
        raise Problem("Only an intercompany elimination can be booked to the consolidated entity.")
    ref, narr = str(p.get("supporting_reference", "")).strip(), str(p.get("narrative", "")).strip()
    if len(ref) < 3:
        raise Problem("Give a supporting reference (document, policy, email or workbook cell).")
    if len(narr) < 10:
        raise Problem("Explain the adjustment in at least 10 characters.")
    if out["basis_type"] == "MANUAL" and len(narr) < 30:
        raise Problem("A manual amount needs a fuller explanation (at least 30 characters).")
    out.update(supporting_reference=ref, narrative=narr, location_code=(str(p["location_code"]).strip() or None) if p.get("location_code") else None,
               linked_policy=(str(p["linked_policy"]).strip() or None) if p.get("linked_policy") else None)
    effect = str(p.get("effect", "")).upper()
    if effect not in EFFECTS:
        raise Problem("Say whether the amount is a COST (reduces profit) or INCOME (raises profit).")
    out["effect"] = effect
    if out["basis_type"] == "RATE":
        metric = str(p.get("rate_metric", ""))
        if metric not in METRICS:
            raise Problem("Choose a rate basis: " + ", ".join(METRICS) + ".")
        try:
            rate = Decimal(str(p.get("rate")))
        except (InvalidOperation, ValueError):
            raise Problem("The rate is not a number.") from None
        if not (Decimal(0) < rate <= Decimal(1)):
            raise Problem("Give the rate as a fraction between 0 and 1 (0.01 is 1 percent).")
        out["rate"], out["rate_metric"] = rate, metric
    else:
        out["entered"] = money(p.get("amount_rupees"))
    return out


def need_gold(gold) -> None:
    if gold is None:
        raise Problem("The management data (gold_fpa) is not available, so a rate basis or an impact preview cannot be calculated. Start the API with FPA_SOURCE=gold.", 503)


def metric_snapshot(gold, entity: str, month: date, metric: str) -> dict:
    """The basis value for a rate adjustment, read from the management book of that month. Rupees, positive. `partial_month` marks a basis the month has not completed."""
    m = month.strftime("%Y-%m")
    need_gold(gold)
    with gold.session("pnl") as g:
        book = msvc.fetch_book(g, m, m)
        asof = msvc.as_of(g)
        last = msvc.available_months(g)[-1]
        ents = ("SUBCO", "HOLDCO") if entity == "CONSOLIDATED" else (entity,)
        key = "revenue" if metric == "net_sales" else "material_cost"
        cr = sum((book.cells.get((m, e, "STORES", key), Decimal(0)) for e in ents), Decimal(0))
        partial = bool(asof and asof.strftime("%Y-%m") == m and asof.day < 28) or m > last
        header = msvc.header(g)
    return {"metric": metric, "value_rupees": str((abs(cr) * CR).quantize(Decimal("0.0001"))), "month": m, "as_of": header["as_of_date"], "run_id": header["run_id"], "partial_month": partial}


def derive(shape: dict, snap: dict | None) -> tuple[Decimal | None, Decimal | None, Decimal, dict | None]:
    """(entered, rate, signed amount, snapshot)."""
    if shape["basis_type"] == "RATE":
        mag = (Decimal(snap["value_rupees"]) * shape["rate"]).quantize(Decimal("0.0001"))
        if mag <= 0:
            raise Problem("The basis metric for that month is zero, so the rate gives no amount.")
        return None, shape["rate"], signed(shape["effect"], mag), snap
    return signed(shape["effect"], shape["entered"]), None, signed(shape["effect"], shape["entered"]), None


# --------------------------------------------------------------------------- persistence

COLUMNS = ("adjustment_id, template_id, reporting_month, entity, management_line, location_type, location_code, adjustment_type, basis_type, entered_amount_rupees, rate, rate_metric, "
           "metric_snapshot, adjustment_amount_rupees, calculation_version, calculated_at, supporting_reference, narrative, linked_policy, owner_user_id, status, reversal_of_id, "
           "created_by, created_at, submitted_at, approved_by, approved_at, activated_at")


def view(r: dict) -> dict:
    out = {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in r.items()}
    out["month"] = r["reporting_month"].strftime("%Y-%m")
    out["amount_rupees"] = r["adjustment_amount_rupees"]
    out["amount_cr"] = (r["adjustment_amount_rupees"] / CR).quantize(Decimal("0.0001"))
    out["effect"] = "COST" if r["adjustment_amount_rupees"] < 0 else "INCOME"
    out["provisional"] = r["status"] in ("DRAFT", "REVIEW", "APPROVED") or bool((r.get("metric_snapshot") or {}).get("partial_month"))
    out["counts_in_management_total"] = r["status"] in ("ACTIVE", "REVERSAL_REQUESTED")
    return out


def fetch(conn, adjustment_id: str) -> dict:
    r = conn.execute(f"SELECT {COLUMNS} FROM adjustment WHERE adjustment_id = %s", (adjustment_id,)).fetchone()
    if r is None:
        raise Problem("No such adjustment.", 404)
    return r


def event(conn, actor: Actor, adjustment_id: str, etype: str, to: str, comment: str | None = None, request_id: str | None = None) -> None:
    try:
        conn.execute("INSERT INTO adjustment_event (adjustment_id, event_type, to_status, actor_user_id, comment, request_id) VALUES (%s, %s, %s, %s, %s, %s)",
                     (adjustment_id, etype, to, actor.user_id, comment, request_id))
    except psycopg.Error as e:
        conn.rollback()
        raise db_error(e) from None
    audit(conn, actor.email, "adjustment_" + etype.lower(), "adjustment", str(adjustment_id), {"to_status": to, "comment": comment}, actor.user_id)


def need(actor: Actor, roles: tuple, what: str) -> None:
    if actor.role not in roles:
        raise Problem(f"Your role ({actor.role}) cannot {what}.", 403)


def insert(conn, actor: Actor, shape: dict, derived: tuple, template_id=None) -> str:
    entered, rate, amount, snap = derived
    try:
        row = conn.execute("""INSERT INTO adjustment (template_id, reporting_month, entity, management_line, location_type, location_code, adjustment_type, basis_type, entered_amount_rupees, rate,
                                  rate_metric, metric_snapshot, adjustment_amount_rupees, calculated_at, supporting_reference, narrative, linked_policy, owner_user_id, created_by)
                              VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s) RETURNING adjustment_id""",
                           (template_id, shape["reporting_month"], shape["entity"], shape["management_line"], shape["location_type"], shape["location_code"], shape["adjustment_type"],
                            shape["basis_type"], entered, rate, shape.get("rate_metric"), json.dumps(snap) if snap else None, amount, msvc_now() if snap else None,
                            shape["supporting_reference"], shape["narrative"], shape["linked_policy"], actor.user_id, actor.user_id)).fetchone()
    except psycopg.Error as e:
        conn.rollback()
        raise db_error(e) from None
    aid = str(row["adjustment_id"])
    event(conn, actor, aid, "CREATED", "DRAFT")
    return aid


def msvc_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def create(conn, gold, actor: Actor, payload: dict) -> dict:
    need(actor, MAKERS, "create adjustments")
    shape = validate_shape(payload)
    snap = metric_snapshot(gold, shape["entity"], shape["reporting_month"], shape["rate_metric"]) if shape["basis_type"] == "RATE" else None
    aid = insert(conn, actor, shape, derive(shape, snap))
    conn.commit()
    return view(fetch(conn, aid))


def update_draft(conn, gold, actor: Actor, adjustment_id: str, payload: dict) -> dict:
    need(actor, MAKERS, "edit adjustments")
    cur = fetch(conn, adjustment_id)
    if cur["status"] != "DRAFT":
        raise Problem("Only a draft can be edited. Reverse an active adjustment and create a new one.", 409)
    shape = validate_shape(payload)
    snap = metric_snapshot(gold, shape["entity"], shape["reporting_month"], shape["rate_metric"]) if shape["basis_type"] == "RATE" else None
    entered, rate, amount, snap = derive(shape, snap)
    try:
        conn.execute("""UPDATE adjustment SET reporting_month = %s, entity = %s, management_line = %s, location_type = %s, location_code = %s, adjustment_type = %s, basis_type = %s,
                            entered_amount_rupees = %s, rate = %s, rate_metric = %s, metric_snapshot = %s::jsonb, adjustment_amount_rupees = %s, calculated_at = %s,
                            supporting_reference = %s, narrative = %s, linked_policy = %s WHERE adjustment_id = %s""",
                     (shape["reporting_month"], shape["entity"], shape["management_line"], shape["location_type"], shape["location_code"], shape["adjustment_type"], shape["basis_type"],
                      entered, rate, shape.get("rate_metric"), json.dumps(snap) if snap else None, amount, msvc_now() if snap else None, shape["supporting_reference"], shape["narrative"],
                      shape["linked_policy"], adjustment_id))
    except psycopg.Error as e:
        conn.rollback()
        raise db_error(e) from None
    audit(conn, actor.email, "adjustment_draft_edited", "adjustment", adjustment_id, {}, actor.user_id)
    conn.commit()
    return view(fetch(conn, adjustment_id))


def submit(conn, gold, actor: Actor, adjustment_id: str, request_id: str | None = None) -> dict:
    """A RATE adjustment re-reads its basis now and freezes the snapshot; everything freezes at SUBMITTED."""
    need(actor, MAKERS, "submit adjustments")
    cur = fetch(conn, adjustment_id)
    if cur["status"] != "DRAFT":
        raise Problem("Only a draft can be submitted.", 409)
    if cur["basis_type"] == "RATE":
        snap = metric_snapshot(gold, cur["entity"], cur["reporting_month"], cur["rate_metric"])
        mag = (Decimal(snap["value_rupees"]) * cur["rate"]).quantize(Decimal("0.0001"))
        if mag <= 0:
            raise Problem("The basis metric for that month is zero, so the rate gives no amount.")
        amount = -mag if cur["adjustment_amount_rupees"] < 0 else mag
        try:
            conn.execute("UPDATE adjustment SET metric_snapshot = %s::jsonb, adjustment_amount_rupees = %s, calculated_at = %s WHERE adjustment_id = %s",
                         (json.dumps(snap), amount, msvc_now(), adjustment_id))
        except psycopg.Error as e:
            conn.rollback()
            raise db_error(e) from None
    event(conn, actor, adjustment_id, "SUBMITTED", "REVIEW", None, request_id)
    conn.commit()
    return view(fetch(conn, adjustment_id))


ACTIONS = {
    # name: (event type, to status, roles, needs a reason, what)
    "approve": ("APPROVED", "APPROVED", CHECKERS, False, "approve adjustments"),
    "activate": ("ACTIVATED", "ACTIVE", CHECKERS, False, "activate adjustments"),
    "reject": ("REJECTED", "REJECTED", CHECKERS, True, "reject adjustments"),
    "withdraw": ("WITHDRAWN", "WITHDRAWN", MAKERS, False, "withdraw adjustments"),
    "request-reversal": ("REVERSAL_REQUESTED", "REVERSAL_REQUESTED", MAKERS, True, "request a reversal"),
    "approve-reversal": ("REVERSAL_APPROVED", "REVERSED", CHECKERS, False, "approve a reversal"),
    "reject-reversal": ("REVERSAL_REJECTED", "ACTIVE", CHECKERS, True, "reject a reversal"),
}


def act(conn, actor: Actor, adjustment_id: str, action: str, comment: str | None, request_id: str | None = None) -> dict:
    if action not in ACTIONS:
        raise Problem("Unknown action.", 404)
    etype, to, roles, reason, what = ACTIONS[action]
    need(actor, roles, what)
    if reason and len((comment or "").strip()) < 10:
        raise Problem("Give a reason of at least 10 characters.")
    fetch(conn, adjustment_id)
    event(conn, actor, adjustment_id, etype, to, comment, request_id)
    conn.commit()
    return view(fetch(conn, adjustment_id))


def comment(conn, actor: Actor, adjustment_id: str, text: str) -> dict:
    if len((text or "").strip()) < 3:
        raise Problem("Write a comment.")
    fetch(conn, adjustment_id)
    event(conn, actor, adjustment_id, "COMMENTED", "DRAFT", text.strip())     # the database sets to_status to the current status
    conn.commit()
    return view(fetch(conn, adjustment_id))


def listing(conn, month: str | None, status: str | None, entity: str | None, line: str | None, limit: int, offset: int) -> dict:
    where, args = [], []
    for col, val in (("reporting_month", month_start(month) if month else None), ("status", status), ("entity", entity), ("management_line", line)):
        if val:
            where.append(f"{col} = %s")
            args.append(val)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(f"SELECT count(*) AS n FROM adjustment {w}", args).fetchone()["n"]
    rows = conn.execute(f"SELECT {COLUMNS} FROM adjustment {w} ORDER BY reporting_month DESC, created_at DESC LIMIT %s OFFSET %s", args + [limit, offset]).fetchall()
    return {"total": total, "items": [view(r) for r in rows]}


def history(conn, adjustment_id: str) -> list[dict]:
    fetch(conn, adjustment_id)
    rows = conn.execute("""SELECT e.seq, e.event_type, e.from_status, e.to_status, e.comment, e.at, u.email AS actor_email, u.display_name AS actor_name
                           FROM adjustment_event e LEFT JOIN app_user u ON u.user_id = e.actor_user_id WHERE e.adjustment_id = %s ORDER BY e.seq""", (adjustment_id,)).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- impact preview

def preview(conn, gold, shape_or_id, entity_view: str = "consolidated") -> dict:
    """Store EBITDA and Corporate EBITDA with and without the adjustment, for its month. Runs the management engine twice. An ACTIVE adjustment is already in the base."""
    if isinstance(shape_or_id, str):
        a = fetch(conn, shape_or_id)
        row = app_register.engine_row(a, "proposed")
        month, line, loc, entity, already = a["reporting_month"].strftime("%Y-%m"), a["management_line"], a["location_type"], a["entity"], a["status"] in ("ACTIVE", "REVERSAL_REQUESTED")
    else:
        shape = shape_or_id
        snap = metric_snapshot(gold, shape["entity"], shape["reporting_month"], shape["rate_metric"]) if shape["basis_type"] == "RATE" else None
        _, _, amount, snap = derive(shape, snap)
        fake = {"adjustment_id": "00000000", "reporting_month": shape["reporting_month"], "entity": shape["entity"], "location_type": shape["location_type"], "management_line": shape["management_line"],
                "adjustment_type": shape["adjustment_type"], "basis_type": shape["basis_type"], "adjustment_amount_rupees": amount, "metric_snapshot": snap, "narrative": shape["narrative"]}
        row = app_register.engine_row(fake, "proposed")
        month, line, loc, entity, already = shape["reporting_month"].strftime("%Y-%m"), shape["management_line"], shape["location_type"], shape["entity"], False
    need_gold(gold)
    out = {"month": month, "entity": entity, "line": line, "location_type": loc, "amount_cr": row["amount"].quantize(Decimal("0.0001")), "already_in_management_total": already, "views": {}}
    keys = (line_target(loc, line), "total_store_expenses", "store_ebitda", "total_corporate", "corporate_ebitda")
    with gold.session("pnl") as g:
        for ev in ("consolidated", "subco", "holdco") if entity_view == "all" else (entity_view,):
            base = msvc.run(g, month, month, True, ev)
            withit = base if already else msvc.run(g, month, month, True, ev, extra_register=[row])
            bl, wl = {x["key"]: x for x in base["lines"]}, {x["key"]: x for x in withit["lines"]}
            out["views"][ev] = {k: {"before": bl[k]["values"][month]["total"], "after": wl[k]["values"][month]["total"],
                                    "change": (wl[k]["values"][month]["total"] - bl[k]["values"][month]["total"]).quantize(Decimal("0.0001"))} for k in dict.fromkeys(keys) if k in bl}
    out["note"] = ("Management Total = Book + Reclass + approved Adjustment. A proposed adjustment is shown here only; it counts in the official total once ACTIVE."
                   + (" The basis month is not complete, so a rate-based amount stays provisional." if row["status"] == "proposed" and not already and row.get("rule") == "rate" else ""))
    return out


def line_target(loc: str, line: str) -> str:
    return eng.line_targets(loc, line) or line
