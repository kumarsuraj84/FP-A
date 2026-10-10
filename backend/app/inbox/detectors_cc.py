"""Creditors and cash detectors for the Exception Inbox. Thresholds live in detectors.THRESHOLDS (one visible, versioned set, UNCALIBRATED). Evidence carries aggregates and the hashed
vendor reference, never a vendor name; the related-party register is excluded from creditors exactly as on the Creditors page."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

D = Decimal


def clamp(x) -> float:
    return float(max(D(0), min(D(100), D(x))))


def _cr(x) -> D:
    return (D(x or 0) / D(10_000_000)).quantize(D("0.0001"))


def creditors(g, th: dict) -> list[dict]:
    from ..gold import creditors as gc
    rows = g.execute(f"""SELECT vendor_ref, sum(CASE WHEN drcr = 'Cr' THEN -pending ELSE 0 END) AS cr_open, sum(CASE WHEN drcr = 'Dr' THEN pending ELSE 0 END) AS dr_open,
                                sum(CASE WHEN drcr = 'Cr' AND due_status = 'PAST_DUE_OR_DUE_TODAY' THEN -pending ELSE 0 END) AS overdue,
                                sum(CASE WHEN drcr = 'Cr' AND document_age_bucket IN ('D181_365', 'D365_PLUS') THEN -pending ELSE 0 END) AS old_cr, max(as_of_date) AS as_of
                         FROM {gc.items(False, 'main')} GROUP BY vendor_ref""").fetchall()
    if not rows:
        return []
    total_cr = sum((D(r["cr_open"] or 0) for r in rows), D(0))
    overdue = sum((D(r["overdue"] or 0) for r in rows), D(0))
    old = sum((D(r["old_cr"] or 0) for r in rows), D(0))
    as_of = max(r["as_of"] for r in rows)
    period = date(as_of.year, as_of.month, 1)
    out = []
    if total_cr > 0:
        share = overdue / total_cr * 100
        if share >= th["creditors_overdue_share"]["pct"]:
            out.append({"exception_type": "CREDITORS_OVERDUE_SHARE", "domain": "CREDITORS", "entity": "SUBCO", "metric_id": "overdue_share", "period": period, "subject_key": "all",
                        "title": f"{share:.0f}% of the credit payable is overdue", "severity": clamp(share), "materiality": clamp(_cr(overdue) / 5), "recency": 100, "actionability": 60, "escalated": False,
                        "evidence": {"overdue_cr": str(_cr(overdue)), "payable_cr": str(_cr(total_cr)), "overdue_pct": f"{share:.1f}", "as_of": as_of.isoformat()}, "drill_link": "/creditors"})
        oshare = old / total_cr * 100
        if oshare >= th["creditors_old_payable"]["pct"]:
            out.append({"exception_type": "CREDITORS_OLD_PAYABLE", "domain": "CREDITORS", "entity": "SUBCO", "metric_id": "old_payable", "period": period, "subject_key": "all",
                        "title": f"{oshare:.0f}% of the credit payable is older than 180 days", "severity": clamp(oshare * 2), "materiality": clamp(_cr(old) / 3), "recency": 100, "actionability": 70, "escalated": False,
                        "evidence": {"older_than_180_days_cr": str(_cr(old)), "payable_cr": str(_cr(total_cr)), "pct": f"{oshare:.1f}", "as_of": as_of.isoformat()}, "drill_link": "/creditors"})
    if overdue > 0:
        cfg = th["creditors_vendor_concentration"]
        for r in sorted(rows, key=lambda r: -(r["overdue"] or 0))[: cfg["max_cases"]]:
            sh = D(r["overdue"] or 0) / overdue * 100
            if sh >= cfg["pct"] and _cr(r["overdue"]) >= cfg["min_cr"]:
                out.append({"exception_type": "CREDITORS_VENDOR_CONCENTRATION", "domain": "CREDITORS", "entity": "SUBCO", "metric_id": "vendor_overdue_share", "period": period, "subject_key": r["vendor_ref"],
                            "title": f"One vendor holds {sh:.0f}% of the overdue payable", "severity": clamp(sh * 3), "materiality": clamp(_cr(r["overdue"]) / 2), "recency": 100, "actionability": 80, "escalated": False,
                            "evidence": {"vendor_ref": r["vendor_ref"], "overdue_cr": str(_cr(r["overdue"])), "share_of_overdue_pct": f"{sh:.1f}", "as_of": as_of.isoformat()}, "drill_link": "/creditors"})
    cfg = th["creditors_debit_balance"]
    debits = sorted(((r, D(r["dr_open"] or 0) - D(r["cr_open"] or 0)) for r in rows), key=lambda x: -x[1])
    for r, net in debits[: cfg["max_cases"]]:
        if _cr(net) >= cfg["min_cr"]:
            out.append({"exception_type": "CREDITORS_DEBIT_BALANCE", "domain": "CREDITORS", "entity": "SUBCO", "metric_id": "vendor_debit_balance", "period": period, "subject_key": r["vendor_ref"],
                        "title": "A vendor has debits above its credits (advance or overpayment)", "severity": 50, "materiality": clamp(_cr(net) * 10), "recency": 100, "actionability": 85, "escalated": False,
                        "evidence": {"vendor_ref": r["vendor_ref"], "net_debit_cr": str(_cr(net)), "as_of": as_of.isoformat()}, "drill_link": "/creditors"})
    return out


def cash(g, th: dict) -> list[dict]:
    out = []
    rows = g.execute("SELECT site_code, cumulative_balance, unposted_net, as_of_date FROM gold_fpa.cash_drawer_store WHERE site_kind = 'STORE'").fetchall()
    if rows:
        as_of = max(r["as_of_date"] for r in rows)
        period = date(as_of.year, as_of.month, 1)
        age = (date.today() - as_of).days
        if age > th["cash_stale_days"]["days"]:
            out.append({"exception_type": "CASH_DATA_STALE", "domain": "CASH", "entity": "SUBCO", "metric_id": "till_cash_freshness", "period": period, "subject_key": "till", "title": f"The till cash data is {age} days old",
                        "severity": clamp(40 + age * 10), "materiality": 40, "recency": 100, "actionability": 70, "escalated": False, "evidence": {"as_of": as_of.isoformat(), "age_days": age}, "drill_link": "/cash"})
        cfg = th["cash_store_balance"]
        flagged = sorted(((r, _cr(r["cumulative_balance"])) for r in rows if _cr(r["cumulative_balance"]) >= cfg["high_cr"] or _cr(r["cumulative_balance"]) < 0), key=lambda x: -abs(x[1]))
        for r, bal in flagged[: cfg["max_cases"]]:
            neg = bal < 0
            out.append({"exception_type": "CASH_STORE_BALANCE", "domain": "CASH", "entity": "SUBCO", "site_code": str(r["site_code"]), "metric_id": "till_balance", "period": period, "subject_key": str(r["site_code"]),
                        "title": "A store till balance is negative" if neg else "A store holds a high till balance", "severity": 70 if neg else 45, "materiality": clamp(abs(bal) * 150), "recency": 100, "actionability": 80,
                        "escalated": False, "evidence": {"site_code": r["site_code"], "balance_cr": str(bal), "unposted_cr": str(_cr(r["unposted_net"])), "as_of": r["as_of_date"].isoformat()}, "drill_link": "/cash"})
    try:
        bank = g.execute("SELECT prior_year_closing FROM gold_fpa.bank_ledger_book WHERE has_movement").fetchall()
        untied = [b for b in bank if b["prior_year_closing"] is None]
        if untied:
            out.append({"exception_type": "BANK_UNTIED_OPENING", "domain": "CASH", "entity": "SUBCO", "metric_id": "bank_opening_tie", "period": None, "subject_key": "bank_book",
                        "title": f"{len(untied)} bank ledger(s) with movement have no tied opening balance", "severity": 55, "materiality": 50, "recency": 80, "actionability": 70, "escalated": False,
                        "evidence": {"ledgers_without_tied_opening": len(untied)}, "drill_link": "/cash"})
    except Exception:  # noqa: BLE001  the bank book may not be loaded on this install
        pass
    return out
