"""Moving the adjustment register from the spreadsheet (CSV) to the app, with evidence.

import_register: administrator only, one time, idempotent (a legacy row already imported is skipped). Each importable CSV row becomes an adjustment (source legacy_csv_import, FIXED, in the
engine's line sign) that arrives ACTIVE (event IMPORTED) or, when the row was only proposed, in REVIEW (IMPORTED_PROPOSED). Rows the engine evaluates against the books (the HoldCo stop-gap and
the true-up rows) cannot be entered as an amount; they stay engine rows and are still read in app mode.
validate_register: the Management P&L under the CSV source against the app source for a window; identical means the cut-over changes no number.
record_cutover: see app/cutover.py."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import psycopg

from ..auth.service import Actor
from ..mgmt import app_register as ar
from ..mgmt import config as cfg
from ..mgmt import engine as eng
from ..mgmt import service as msvc
from ..mapping.service import diff_lines
from . import service as svc
from .service import Problem

CR = Decimal(10_000_000)


def import_register(conn, actor: Actor) -> dict:
    if actor.role != "admin":
        raise Problem("Only an administrator imports the legacy register.", 403)
    have = {r["supporting_reference"] for r in conn.execute("SELECT supporting_reference FROM adjustment WHERE source = 'legacy_csv_import'").fetchall()}
    made, skipped_existing, engine_rows, invalid = 0, 0, [], []
    for r in cfg.adjustments():
        if ar.is_engine_row(r):
            engine_rows.append(r["id"])
            continue
        if not ar.importable(r):
            invalid.append({"id": r.get("id"), "reason": "unknown kind or missing month/amount"})
            continue
        ref = f"legacy:{r['id']}:{r['mis_line']}"          # one legacy id can carry two lines (a salary moved between lines)
        if ref in have:
            skipped_existing += 1
            continue
        loc, line, ent = r["location_type"], r["mis_line"], r["entity"]
        if ent not in ("SUBCO", "HOLDCO") or loc not in svc.LOCATIONS or eng.line_targets(loc, line) is None or (line not in svc.LINE_KEYS and line != "director_remuneration"):
            invalid.append({"id": r["id"], "reason": f"line {line} / location {loc} / entity {ent} is not valid"})
            continue
        rupees = (Decimal(r["amount"]) * CR).quantize(Decimal("0.0001"))
        note = f"{r.get('rule', '')} ({r.get('source', '')}). {r.get('note', '')}".strip()
        narrative = note if len(note) >= 10 else "Legacy register row imported from the spreadsheet."
        month = date(int(r["month"][:4]), int(r["month"][5:7]), 1)
        try:
            row = conn.execute("""INSERT INTO adjustment (reporting_month, entity, management_line, location_type, adjustment_type, basis_type, entered_amount_rupees, adjustment_amount_rupees,
                                      supporting_reference, narrative, owner_user_id, created_by, source)
                                  VALUES (%s, %s, %s, %s, %s, 'FIXED', %s, %s, %s, %s, %s, %s, 'legacy_csv_import') RETURNING adjustment_id""",
                               (month, ent, line, loc, ar.TYPE_OF_KIND[r["kind"]], rupees, rupees, ref, narrative[:2000], actor.user_id, actor.user_id)).fetchone()
        except psycopg.Error as e:
            conn.rollback()
            raise svc.db_error(e) from None
        aid = str(row["adjustment_id"])
        svc.event(conn, actor, aid, "CREATED", "DRAFT")
        proposed = r.get("status") == "proposed"
        svc.event(conn, actor, aid, "IMPORTED_PROPOSED" if proposed else "IMPORTED", "REVIEW" if proposed else "ACTIVE", "Imported once from the legacy spreadsheet register.")
        made += 1
    conn.commit()
    return {"imported": made, "skipped_existing": skipped_existing, "kept_as_engine_rows": len(engine_rows), "not_importable": invalid,
            "next": "Run the validation; when it reports identical, record the cut-over and set FPA_ADJ_SOURCE=app."}


def validate_register(gold, lo: str | None, hi: str | None) -> dict:
    if gold is None:
        raise Problem("The management data (gold_fpa) is not available.", 503)
    with gold.session("pnl") as g:
        months = msvc.available_months(g)
        lo, hi = lo or months[0], hi or months[-1]
        with ar.forced("csv"):
            a = _lines(g, lo, hi)
        with ar.forced("app"):
            b = _lines(g, lo, hi)
    mlist = [m for m in months if lo <= m <= hi]
    diffs = diff_lines(a, b, mlist)
    csv_rows = cfg.adjustments()
    return {"window": [lo, hi], "csv_rows": len(csv_rows), "csv_importable": sum(1 for r in csv_rows if ar.importable(r)), "csv_engine_rows": sum(1 for r in csv_rows if ar.is_engine_row(r)),
            "line_differences": diffs, "identical": not diffs,
            "note": "Identical means every Management P&L line total agrees month by month under the CSV source and under the app source (app rows plus the engine-evaluated legacy rows): the cut-over changes no number."}


def _lines(g, lo, hi) -> dict:
    ctx = msvc.run(g, lo, hi)
    return {x["key"]: x for x in ctx["lines"] if x["kind"] != "pct"}
