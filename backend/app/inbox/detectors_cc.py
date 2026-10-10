"""Creditors and cash detectors for the Exception Inbox. Thresholds live in detectors.THRESHOLDS (one visible, versioned set, UNCALIBRATED). Evidence carries aggregates and the hashed
vendor reference, never a vendor name; the related-party register is excluded from creditors exactly as on the Creditors page.

The finance tables hold only today's position, so trend detectors use the platform's own metric snapshots (migration 012: one row per metric, subject and day, aggregates only). Until a
second day has been recorded the trend detectors say nothing; the point-in-time detectors work from the first run. Wording follows Finance: a debit balance is 'classification pending',
the cause is never inferred; a bank opening that is not tied is a CONTROLS exception and escalates whatever the rupees."""
from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal

D = Decimal


def clamp(x) -> float:
    return float(max(D(0), min(D(100), D(x))))


def _cr(x) -> D:
    return (D(x or 0) / D(10_000_000)).quantize(D("0.0001"))


# --------------------------------------------------------------------------- snapshots

def record(app, domain: str, metric: str, subject: str, as_of: date, value: dict) -> None:
    if app is None:
        return
    app.execute("INSERT INTO metric_snapshot (domain, metric, subject_key, as_of, value) VALUES (%s, %s, %s, %s, %s::jsonb) ON CONFLICT (domain, metric, subject_key, as_of) DO NOTHING",
                (domain, metric, subject, as_of, json.dumps(value, default=str)))


def previous(app, domain: str, metric: str, subject: str, before: date) -> dict | None:
    """The latest snapshot of an EARLIER day: today's own record is never its own comparison."""
    if app is None:
        return None
    r = app.execute("SELECT as_of, value FROM metric_snapshot WHERE domain = %s AND metric = %s AND subject_key = %s AND as_of < %s ORDER BY as_of DESC LIMIT 1", (domain, metric, subject, before)).fetchone()
    return {"as_of": r["as_of"], **r["value"]} if r else None


def recent(app, domain: str, metric: str, subject: str, upto: date, n: int) -> list[dict]:
    """The last n snapshots up to and including `upto`, newest first."""
    if app is None:
        return []
    return [{"as_of": r["as_of"], **r["value"]} for r in app.execute("SELECT as_of, value FROM metric_snapshot WHERE domain = %s AND metric = %s AND subject_key = %s AND as_of <= %s ORDER BY as_of DESC LIMIT %s",
                                                                       (domain, metric, subject, upto, n)).fetchall()]


def case(typ, domain, title, severity, materiality, actionability, evidence, link, *, entity="SUBCO", metric, subject, period=None, site=None, escalated=False, recency=100) -> dict:
    c = {"exception_type": typ, "domain": domain, "entity": entity, "metric_id": metric, "period": period, "subject_key": subject, "title": title, "severity": clamp(severity), "materiality": clamp(materiality),
         "recency": recency, "actionability": actionability, "escalated": escalated, "evidence": evidence, "drill_link": link}
    if site is not None:
        c["site_code"] = site
    return c


# --------------------------------------------------------------------------- creditors

def creditors(g, th: dict, app=None) -> list[dict]:
    from ..gold import creditors as gc
    rows = g.execute(f"""SELECT vendor_ref, sum(CASE WHEN drcr = 'Cr' THEN -pending ELSE 0 END) AS cr_open, sum(CASE WHEN drcr = 'Dr' THEN pending ELSE 0 END) AS dr_open,
                                sum(CASE WHEN drcr = 'Cr' AND due_status = 'PAST_DUE_OR_DUE_TODAY' THEN -pending ELSE 0 END) AS overdue,
                                sum(CASE WHEN drcr = 'Cr' AND document_age_bucket IN ('D181_365', 'D365_PLUS') THEN -pending ELSE 0 END) AS old_cr,
                                sum(CASE WHEN drcr = 'Cr' AND document_age_bucket IN ('D91_180', 'D181_365', 'D365_PLUS') THEN -pending ELSE 0 END) AS over90,
                                sum(CASE WHEN drcr = 'Cr' AND due_status = 'DUE_UNAVAILABLE' THEN -pending ELSE 0 END) AS due_unavail,
                                max(CASE WHEN drcr = 'Cr' THEN document_age_days END) AS oldest_days, max(as_of_date) AS as_of
                         FROM {gc.items(False, 'main')} GROUP BY vendor_ref""").fetchall()
    if not rows:
        return []
    S = lambda k: sum((D(r[k] or 0) for r in rows), D(0))  # noqa: E731
    total_cr, overdue, old, over90, unavail = S("cr_open"), S("overdue"), S("old_cr"), S("over90"), S("due_unavail")
    as_of = max(r["as_of"] for r in rows)
    period = date(as_of.year, as_of.month, 1)
    iso = as_of.isoformat()
    out = []
    if total_cr > 0:
        share = overdue / total_cr * 100
        if share >= th["creditors_overdue_share"]["pct"]:
            out.append(case("CREDITORS_OVERDUE_SHARE", "CREDITORS", f"{share:.0f}% of the credit payable is overdue", share, _cr(overdue) / 5, 60,
                            {"overdue_cr": str(_cr(overdue)), "payable_cr": str(_cr(total_cr)), "overdue_pct": f"{share:.1f}", "as_of": iso}, "/creditors", metric="overdue_share", subject="all", period=period))
        oshare = old / total_cr * 100
        if oshare >= th["creditors_old_payable"]["pct"]:
            out.append(case("CREDITORS_OLD_PAYABLE", "CREDITORS", f"{oshare:.0f}% of the credit payable is older than 180 days", oshare * 2, _cr(old) / 3, 70,
                            {"older_than_180_days_cr": str(_cr(old)), "payable_cr": str(_cr(total_cr)), "pct": f"{oshare:.1f}", "as_of": iso}, "/creditors", metric="old_payable", subject="all", period=period))
        ushare = unavail / total_cr * 100
        if ushare >= th["creditors_due_unavailable"]["pct"]:
            out.append(case("CREDITORS_DUE_UNAVAILABLE", "CREDITORS", f"{ushare:.0f}% of the credit payable has no due date to measure overdue against", ushare * 2, _cr(unavail) / 5, 75,
                            {"due_unavailable_cr": str(_cr(unavail)), "payable_cr": str(_cr(total_cr)), "pct": f"{ushare:.1f}", "as_of": iso}, "/creditors", metric="due_unavailable", subject="all", period=period))
    cfg = th["creditors_vendor_concentration"]
    if overdue > 0:
        for r in sorted(rows, key=lambda r: -(r["overdue"] or 0))[: cfg["max_cases"]]:
            sh = D(r["overdue"] or 0) / overdue * 100
            if sh >= cfg["pct"] and _cr(r["overdue"]) >= cfg["min_cr"]:
                out.append(case("CREDITORS_VENDOR_CONCENTRATION", "CREDITORS", f"One vendor holds {sh:.0f}% of the overdue payable", sh * 3, _cr(r["overdue"]) / 2, 80,
                                {"vendor_ref": r["vendor_ref"], "overdue_cr": str(_cr(r["overdue"])), "share_of_overdue_pct": f"{sh:.1f}", "as_of": iso}, "/creditors", metric="vendor_overdue_share", subject=r["vendor_ref"], period=period))
    cfg = th["creditors_debit_balance"]
    for r, net in sorted(((r, D(r["dr_open"] or 0) - D(r["cr_open"] or 0)) for r in rows), key=lambda x: -x[1])[: cfg["max_cases"]]:
        if _cr(net) >= cfg["min_cr"]:
            out.append(case("CREDITORS_DEBIT_BALANCE", "CREDITORS", "Creditor debit balance: classification pending", 50, _cr(net) * 10, 85,
                            {"vendor_ref": r["vendor_ref"], "net_debit_cr": str(_cr(net)), "as_of": iso, "note": "The cause is not inferred: Finance classifies it."}, "/creditors", metric="vendor_debit_balance", subject=r["vendor_ref"], period=period))
    cfg = th["creditors_oldest_bill"]
    for r in sorted(rows, key=lambda r: -(r["oldest_days"] or 0))[: cfg["max_cases"]]:
        if (r["oldest_days"] or 0) >= cfg["days"] and _cr(r["cr_open"]) >= cfg["min_cr"]:
            out.append(case("CREDITORS_OLDEST_BILL", "CREDITORS", f"A vendor with material exposure has an open bill {r['oldest_days']} days old", min(100, 40 + (r["oldest_days"] or 0) / 10), _cr(r["cr_open"]) / 2, 80,
                            {"vendor_ref": r["vendor_ref"], "oldest_open_bill_days": r["oldest_days"], "open_credit_cr": str(_cr(r["cr_open"])), "as_of": iso}, "/creditors", metric="oldest_open_bill", subject=r["vendor_ref"], period=period))
    # the exclusion rule must hold: nothing registered as a related party may sit in the main creditors
    try:
        from ..gold import related_gl as rgl
        pats = [n for n in rgl.load() if n["books_of_entity"] == "RETAIL" and n["counterparty_entity"] in ("HOLDCO", "SUBCO")]
        if pats:
            names = g.execute(f"SELECT DISTINCT vendor_name FROM {gc.items(True, 'main')}").fetchall()
            leak = [x for x in names if x["vendor_name"] and any(re.search(p["party_pattern"], x["vendor_name"], re.I) for p in pats)]
            if leak:
                out.append(case("CREDITORS_RELATED_PARTY_LEAK", "CONTROLS", f"{len(leak)} registered related party(ies) appear in the main creditors", 85, 60, 90, {"parties_in_main_scope": len(leak), "as_of": iso},
                                "/related-party", metric="related_party_exclusion", subject="main_scope", period=period, escalated=True))
    except Exception:  # noqa: BLE001  no register configured on this install
        pass
    # ---- trends from the platform's own snapshots (silent until a second day exists)
    record(app, "CREDITORS", "aggregate", "all", as_of, {"payable": str(total_cr), "overdue": str(overdue), "over90": str(over90), "old180": str(old), "due_unavailable": str(unavail)})
    for r in sorted(rows, key=lambda r: -(r["overdue"] or 0))[:20]:
        record(app, "CREDITORS", "vendor_overdue", r["vendor_ref"], as_of, {"overdue": str(D(r["overdue"] or 0)), "share": f"{(D(r['overdue'] or 0) / overdue * 100) if overdue else 0:.4f}"})
    prev = previous(app, "CREDITORS", "aggregate", "all", as_of)
    if prev:
        pt, po, p90 = D(prev["payable"]), D(prev["overdue"]), D(prev["over90"])
        cfg = th["creditors_ageing_migration"]
        d_share = (over90 / total_cr - p90 / pt) * 100 if total_cr > 0 and pt > 0 else D(0)
        d_amt = _cr(over90 - p90)
        if d_share >= cfg["pp"] and d_amt >= cfg["min_cr"]:
            out.append(case("CREDITORS_AGEING_MIGRATION", "CREDITORS", f"Payable older than 90 days rose {d_share:.1f} points since {prev['as_of'].isoformat()}", d_share * 15, d_amt / 2, 70,
                            {"over90_share_change_pp": f"{d_share:.2f}", "over90_change_cr": str(d_amt), "since": prev["as_of"].isoformat(), "as_of": iso, "note": "Compared with the previous snapshot; bills ageing naturally is part of the movement."},
                            "/creditors", metric="ageing_migration", subject="all", period=period))
        cfg = th["creditors_overdue_rising"]
        if po > 0 and overdue / po - 1 >= cfg["overdue_pct"] / 100 and pt > 0 and total_cr / pt - 1 <= cfg["payable_flat_pct"] / 100:
            out.append(case("CREDITORS_OVERDUE_RISING", "CREDITORS", "Overdue payable is rising while total payable is flat or falling", 65, _cr(overdue - po) / 2, 75,
                            {"overdue_change_cr": str(_cr(overdue - po)), "payable_change_cr": str(_cr(total_cr - pt)), "since": prev["as_of"].isoformat(), "as_of": iso}, "/creditors", metric="overdue_rising", subject="all", period=period))
        cfg = th["creditors_vendor_concentration"]
        for r in sorted(rows, key=lambda r: -(r["overdue"] or 0))[:20]:
            pv = previous(app, "CREDITORS", "vendor_overdue", r["vendor_ref"], as_of)
            if pv and overdue > 0:
                jump = (D(r["overdue"] or 0) / overdue * 100) - D(pv["share"])
                if jump >= cfg["jump_pp"] and _cr(r["overdue"]) >= cfg["min_cr"]:
                    out.append(case("CREDITORS_CONCENTRATION_RISING", "CREDITORS", f"One vendor's share of the overdue payable rose {jump:.1f} points", jump * 6, _cr(r["overdue"]) / 2, 75,
                                    {"vendor_ref": r["vendor_ref"], "share_change_pp": f"{jump:.2f}", "since": pv["as_of"].isoformat(), "as_of": iso}, "/creditors", metric="vendor_concentration_rising", subject=r["vendor_ref"], period=period))
    return out


# --------------------------------------------------------------------------- cash and bank

def cash(g, th: dict, app=None) -> list[dict]:
    out = []
    rows = g.execute("SELECT site_code, cumulative_balance, unposted_net, as_of_date FROM gold_fpa.cash_drawer_store WHERE site_kind = 'STORE'").fetchall()
    if rows:
        as_of = max(r["as_of_date"] for r in rows)
        period = date(as_of.year, as_of.month, 1)
        iso = as_of.isoformat()
        age = (date.today() - as_of).days
        if age > th["cash_stale_days"]["days"]:
            out.append(case("CASH_DATA_STALE", "CASH", f"The till cash data is {age} days old", 40 + age * 10, 40, 70, {"as_of": iso, "age_days": age}, "/cash", metric="till_cash_freshness", subject="till", period=period))
        cfg = th["cash_store_balance"]
        for r in rows:
            record(app, "CASH", "till", str(r["site_code"]), as_of, {"balance": str(D(r["cumulative_balance"] or 0)), "unposted": str(D(r["unposted_net"] or 0))})
        for r in sorted((r for r in rows if _cr(r["cumulative_balance"]) < 0), key=lambda r: r["cumulative_balance"])[: cfg["max_cases"]]:
            bal = _cr(r["cumulative_balance"])
            out.append(case("CASH_STORE_NEGATIVE", "CASH", "A store till balance is negative", 70, abs(bal) * 150, 80, {"site_code": r["site_code"], "balance_cr": str(bal), "as_of": iso}, "/cash",
                            metric="till_negative", subject=str(r["site_code"]), period=period, site=str(r["site_code"])))
        shown = 0
        for r in sorted((r for r in rows if _cr(r["cumulative_balance"]) >= cfg["high_cr"]), key=lambda r: -r["cumulative_balance"]):
            if shown >= cfg["max_cases"]:
                break
            bal = _cr(r["cumulative_balance"])
            hist = recent(app, "CASH", "till", str(r["site_code"]), as_of, cfg["consecutive_snapshots"])
            run = len(hist) >= cfg["consecutive_snapshots"] and all(_cr(h["balance"]) >= cfg["high_cr"] for h in hist)
            if run or bal >= cfg["high_cr"] * 3:
                out.append(case("CASH_STORE_HIGH", "CASH", "A store keeps a high till balance" if run else "A store holds a very high till balance", 45, bal * 150, 80,
                                {"site_code": r["site_code"], "balance_cr": str(bal), "consecutive_snapshots_high": len(hist) if run else 1, "as_of": iso}, "/cash", metric="till_high", subject=str(r["site_code"]), period=period, site=str(r["site_code"])))
                shown += 1
        cfg = th["cash_unposted_gap"]
        for r in sorted(rows, key=lambda r: -abs(r["unposted_net"] or 0))[: cfg["max_cases"]]:
            if _cr(abs(r["unposted_net"] or 0)) >= cfg["min_cr"]:
                out.append(case("CASH_UNPOSTED_GAP", "CASH", "A store has a large gap between posted and unposted till movement", 50, _cr(abs(r["unposted_net"])) * 200, 80,
                                {"site_code": r["site_code"], "unposted_cr": str(_cr(r["unposted_net"])), "as_of": iso}, "/cash", metric="till_unposted_gap", subject=str(r["site_code"]), period=period, site=str(r["site_code"])))
        cfg = th["cash_unchanged"]
        try:
            active = {x["site_code"] for x in g.execute("SELECT site_code FROM gold_fpa.sales_site_day WHERE bill_date >= current_date - %s AND net_sales_ex_gst > 0 GROUP BY site_code", (cfg["days"],)).fetchall()}
        except Exception:  # noqa: BLE001
            active = set()
        for r in rows:
            if r["site_code"] in active:
                hist = recent(app, "CASH", "till", str(r["site_code"]), as_of, cfg["snapshots"])
                if len(hist) >= cfg["snapshots"] and len({h["balance"] for h in hist}) == 1 and abs(D(hist[0]["balance"])) > 0:
                    out.append(case("CASH_UNCHANGED_WHILE_ACTIVE", "CASH", "A store trades but its till balance has not moved", 55, 30, 80, {"site_code": r["site_code"], "snapshots_unchanged": len(hist), "as_of": iso}, "/cash",
                                    metric="till_unchanged", subject=str(r["site_code"]), period=period, site=str(r["site_code"])))
    try:
        bank = g.execute("SELECT ledger_name, prior_year_closing, has_movement, last_posted_date, posted_closing FROM gold_fpa.bank_ledger_book WHERE has_movement").fetchall()
        untied = [b for b in bank if b["prior_year_closing"] is None]
        if untied:
            out.append(case("BANK_UNTIED_OPENING", "CONTROLS", f"{len(untied)} bank ledger(s) with movement have no tied opening balance", 80, 60, 70, {"ledgers_without_tied_opening": len(untied)}, "/cash",
                            metric="bank_opening_tie", subject="bank_book", escalated=True, recency=80))
        cfg = th["bank_stale_days"]
        stale = [b for b in bank if b["last_posted_date"] and (date.today() - b["last_posted_date"]).days > cfg["days"]]
        if stale:
            out.append(case("BANK_STALE_LEDGER", "CASH", f"{len(stale)} active bank ledger(s) have had no posting for over {cfg['days']} days", 45, 30, 60, {"stale_ledgers": len(stale), "threshold_days": cfg["days"]}, "/cash",
                            metric="bank_stale", subject="bank_book"))
    except Exception:  # noqa: BLE001  the bank book may not be loaded on this install
        pass
    return out
