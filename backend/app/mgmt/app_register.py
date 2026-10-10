"""The governed adjustment register in the app database (fpa_app) as rows the management engine understands.

Source switch FPA_ADJ_SOURCE: csv (default, the spreadsheet register only, today's numbers), app (ACTIVE rows of fpa_app only), both. Moving Finance from the CSV
to the app register is a deliberate cut-over (import the CSV rows, then switch to app), never a silent double count: with 'both' the caller must know the two
registers are disjoint.

Engine rows are in Crore with a month 'YYYY-MM'. The database stores rupees in the engine's line sign (profit-effect sign), so the amount is only divided by 1e7.
Only ACTIVE adjustments (and ACTIVE ones with a reversal pending) count; a proposed one appears only in an impact preview, as status 'proposed' (provisional)."""
from __future__ import annotations

import os
from decimal import Decimal

from ..appdb.conn import app_connection

CR = Decimal(10_000_000)
KIND = {"PROVISION": "provision", "MANAGEMENT_JOURNAL": "manual_journal", "INCOME_ADJUSTMENT": "income_adjustment", "ONE_TIME": "one_time",
        "INTERCOMPANY_ELIMINATION": "elimination", "COGS_MANAGEMENT_CORRECTION": "provision"}


def source() -> str:
    v = os.environ.get("FPA_ADJ_SOURCE", "csv").lower()
    return v if v in ("csv", "app", "both") else "csv"


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
        rows = conn.execute("SELECT a.*, v.adjustment_id AS _v FROM v_adjustment_active v JOIN adjustment a USING (adjustment_id)").fetchall()
    return [engine_row(r) for r in rows]
