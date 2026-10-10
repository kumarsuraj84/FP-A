"""The governed adjustment register in the app database (fpa_app) as rows the management engine understands.

Source switch FPA_ADJ_SOURCE: csv (default, the spreadsheet register only, today's numbers), app, both.
  app  = the governed rows of fpa_app, PLUS the legacy rows that cannot be entered as an amount because the engine evaluates them against the books ('legacy engine rows': the HoldCo
         stop-gap while gold lacks Ventures, and the 'true_up' rows that replace what a ledger booked). Nothing else is read from the CSV.
  both = the spreadsheet register and the app register together; only for a short, deliberate overlap, because a row in both is counted twice.
Moving Finance from the CSV to the app register is a deliberate cut-over: import the importable CSV rows once (administrator), validate that the Management P&L is identical under both
sources, record the cut-over, then set FPA_ADJ_SOURCE=app. The CSV is then history, not a source.

Engine rows are in Crore with a month 'YYYY-MM'. The database stores rupees in the engine's line sign (profit-effect sign), so the amount is only divided by 1e7. ACTIVE adjustments (and
ACTIVE ones with a reversal pending) are confirmed; one still in REVIEW or APPROVED appears as a proposed (provisional) row, which the engine shows only when proposed adjustments are included."""
from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal

from ..appdb.conn import app_connection

CR = Decimal(10_000_000)
KIND = {"PROVISION": "provision", "MANAGEMENT_JOURNAL": "manual_journal", "INCOME_ADJUSTMENT": "income_adjustment", "ONE_TIME": "one_time",
        "INTERCOMPANY_ELIMINATION": "elimination", "COGS_MANAGEMENT_CORRECTION": "provision"}
TYPE_OF_KIND = {"provision": "PROVISION", "manual_journal": "MANAGEMENT_JOURNAL", "income_adjustment": "INCOME_ADJUSTMENT", "one_time": "ONE_TIME", "elimination": "INTERCOMPANY_ELIMINATION",
                "reclass": "MANAGEMENT_JOURNAL"}          # a legacy 'reclass' amount is an entered management movement, not a source-line correction
_force: ContextVar = ContextVar("adj_force_source", default=None)


def source() -> str:
    f = _force.get()
    if f in ("csv", "app", "both"):
        return f
    v = os.environ.get("FPA_ADJ_SOURCE", "csv").lower()
    return v if v in ("csv", "app", "both") else "csv"


@contextmanager
def forced(src: str):
    """Run a block under another source (validation only). Request-scoped, never global."""
    t = _force.set(src)
    try:
        yield
    finally:
        _force.reset(t)


def is_engine_row(r: dict) -> bool:
    """A legacy row the engine evaluates against the books, so it has no amount to enter: the HoldCo stop-gap and the true-up rows."""
    return r.get("kind") == "stopgap_entity" or str(r.get("rule", "")).startswith("true_up:")


def importable(r: dict) -> bool:
    return not is_engine_row(r) and r.get("kind") in TYPE_OF_KIND and bool(r.get("month")) and r.get("amount") is not None


def engine_row(a: dict, status: str = "confirmed") -> dict:
    """One adjustment (a dict with the table's columns) as an engine register row."""
    month = a["reporting_month"].strftime("%Y-%m") if hasattr(a["reporting_month"], "strftime") else str(a["reporting_month"])[:7]
    prov = bool((a.get("metric_snapshot") or {}).get("partial_month"))      # a rate on a partial-month basis stays provisional until the month completes
    ent = "SUBCO" if a["entity"] == "CONSOLIDATED" else a["entity"]
    return {"id": "ADJ-" + str(a["adjustment_id"])[:8].upper(), "month": month, "entity": ent, "location_type": a["location_type"], "mis_line": a["management_line"],
            "amount": Decimal(a["adjustment_amount_rupees"]) / CR, "kind": KIND[a["adjustment_type"]], "rule": a["basis_type"].lower(), "owner": str(a.get("owner_user_id") or ""),
            "status": "proposed" if (prov or status == "proposed") else "confirmed", "source": "fpa_app", "note": a.get("narrative", ""), "counterparty": "", "counterparty_entity": ""}


def active_rows() -> list[dict]:
    if source() == "csv":
        return []
    with app_connection() as conn:
        rows = conn.execute("SELECT * FROM adjustment WHERE status IN ('ACTIVE', 'REVERSAL_REQUESTED', 'REVIEW', 'APPROVED')").fetchall()
    return [engine_row(r, "confirmed" if r["status"] in ("ACTIVE", "REVERSAL_REQUESTED") else "proposed") for r in rows]
