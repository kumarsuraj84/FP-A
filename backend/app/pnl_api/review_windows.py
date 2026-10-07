"""Window figures, the day-aligned comparison and the P&L pivot (see review.py for the definitions)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from . import repository as repo
from .review import Review, q4

ZERO = Decimal(0)


# ───────────── window figures: this year and the day-aligned last year ─────────────


def _sum_sites(rv: Review, pick, months: list[date]) -> dict:
    t = repo.blank()
    for (site, mon), a in rv.sc.data.items():
        if mon in months and pick(site):
            repo.add(t, a)
    return t


def window(rv: Review, pick, months: list[date]) -> dict:
    """Totals for a list of months of THIS year (a partial as-of month is simply whatever the books hold to the as-of date: days 1..N)."""
    return repo.finish(_sum_sites(rv, pick, months))


def ly_window(rv: Review, pick, months: list[date]) -> dict | None:
    """The same window one year earlier. A complete month is last year's complete month; the partial as-of month is last year's days 1..N (the aligned window). None when last year is not there."""
    t = repo.blank()
    for m in months:
        lm = repo.add_months(m, -12)
        if m == rv.as_of_month and rv.partial:
            if rv.aligned is None:
                return None
            for site, a in rv.aligned["sites"].items():
                if pick(site):
                    repo.add(t, a)
        else:
            if lm < rv.first_month:
                return None
            for (site, mon), a in rv.sc.data.items():
                if mon == lm and pick(site):
                    repo.add(t, a)
    return repo.finish(t)


def _bps(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None else q4((a - b) * 100)


def _mm(t: dict) -> dict:
    return {k: t[k] for k in ("revenue", "cogs", "cogs_books", "gross_margin", "gross_margin_pct", "opex", "opex_pct", "contribution", "contribution_pct", "other_income", "finance_cost")}


def compare_windows(rv: Review, pick) -> list[dict]:
    """MTD, QTD and YTD: this year against last year, day aligned. Percent measures compare in basis points, amounts in percent."""
    defs = [("mtd", "Month to date", [rv.as_of_month]), ("qtd", "Quarter to date", repo.months_between(rv.quarter_start(), rv.as_of_month)), ("ytd", "Year to date", repo.months_between(rv.fy_start(), rv.as_of_month))]
    out = []
    for wid, label, months in defs:
        ty, ly = window(rv, pick, months), ly_window(rv, pick, months)
        row = {"id": wid, "label": label, "from_month": months[0].strftime("%Y-%m"), "to_month": months[-1].strftime("%Y-%m"), "day_aligned": bool(rv.partial), "ty": _mm(ty), "ly": None if ly is None else _mm(ly), "growth": None}
        if ly is not None:
            row["growth"] = {"revenue_pct": repo.pct(ty["revenue"] - ly["revenue"], ly["revenue"]), "gross_margin_pct": repo.pct(ty["gross_margin"] - ly["gross_margin"], abs(ly["gross_margin"])),
                             "contribution_pct": repo.pct(ty["contribution"] - ly["contribution"], abs(ly["contribution"])),
                             "gm_bps": _bps(ty["gross_margin_pct"], ly["gross_margin_pct"]), "opex_bps": _bps(ty["opex_pct"], ly["opex_pct"]), "contribution_bps": _bps(ty["contribution_pct"], ly["contribution_pct"])}
        out.append(row)
    return out


# ───────────── the pivot ─────────────


def group_effect(rv: Review, pick, group: str, months: list[date]) -> Decimal:
    t = ZERO
    for (site, mon), g in rv.gm.items():
        if mon in months and pick(site) and group in g:
            t += g[group]
    return t


def ly_group_effect(rv: Review, pick, group: str, months: list[date]) -> Decimal | None:
    t = ZERO
    for m in months:
        lm = repo.add_months(m, -12)
        if m == rv.as_of_month and rv.partial:
            if rv.aligned is None:
                return None
            t += sum((v for (site, g), v in rv.aligned["groups"].items() if g == group and pick(site)), ZERO)
        else:
            if lm < rv.first_month:
                return None
            for (site, mon), g in rv.gm.items():
                if mon == lm and pick(site) and group in g:
                    t += g[group]
    return t


def pivot_columns(rv: Review) -> list[dict]:
    fy = rv.fy_start()
    months = repo.months_between(fy, rv.as_of_month)
    cols = [{"id": m.strftime("%Y-%m"), "label": m.strftime("%b %y"), "kind": "month", "months": [m], "partial": (m == rv.as_of_month and rv.partial)} for m in months]
    q = 0
    while True:
        qs = repo.add_months(fy, 3 * q)
        if qs > rv.as_of_month:
            break
        qe = repo.add_months(qs, 2)
        current = qs <= rv.as_of_month <= qe
        ms = repo.months_between(qs, min(qe, rv.as_of_month))
        cols.append({"id": "qtd" if current else f"q{q + 1}", "label": f"Q{q + 1} to date" if current else f"Q{q + 1}", "kind": "quarter", "months": ms, "partial": current and (rv.partial or rv.as_of_month < qe)})
        q += 1
    cols.append({"id": "ytd", "label": "YTD", "kind": "ytd", "months": months, "partial": bool(rv.partial)})
    return cols


def pivot(rv: Review, pick, company: bool) -> dict:
    cols = pivot_columns(rv)
    ytd = next(c for c in cols if c["id"] == "ytd")
    groups = rv.opex_groups
    other = sorted(g for g, s in rv.section_of.items() if s in ("COGS_BOOKS", "OTHER_INCOME", "FINANCE_COST"))

    def values(months: list[date], ly: bool) -> dict:
        if ly:
            t = ly_window(rv, pick, months)
            if t is None:
                return {}
            gv = {g: ly_group_effect(rv, pick, g, months) for g in groups + other}
        else:
            t = window(rv, pick, months)
            gv = {g: group_effect(rv, pick, g, months) for g in groups + other}
        v = {"revenue": t["revenue"], "cogs": -t["cogs"], "cogs_books": t["cogs_books"], "gross_margin": t["gross_margin"], "store_opex": t["opex"], "contribution": t["contribution"],
             "other_income": t["other_income"], "finance_cost": t["finance_cost"]}
        v.update({"g:" + g: gv[g] for g in groups + other})
        return v

    cells = {c["id"]: values(c["months"], False) for c in cols}
    ly = values(ytd["months"], True)
    contribution_label = "Contribution, all sites (before other income and finance cost)" if company else "Store contribution (before other income, finance cost and head office)"
    defs = [("revenue", "Net sales (ex-GST)", "line", 0), ("cogs", "COGS (COGS table)", "line", 0), ("cogs_books", "Other COGS items (books)", "line", 0), ("gross_margin", "Gross margin", "subtotal", 0)]
    defs += [("g:" + g, g.split("-", 1)[-1], "group", 1) for g in groups]
    defs += [("store_opex", "Store operating expenses", "subtotal", 0), ("contribution", contribution_label, "subtotal", 0), ("other_income", "Other income", "memo", 0), ("finance_cost", "Finance cost", "memo", 0)]
    rows = []
    for rid, label, kind, level in defs:
        r = {"id": rid, "label": label, "kind": kind, "level": level, "group": rid[2:] if rid.startswith("g:") else None, "cells": {c["id"]: cells[c["id"]].get(rid) for c in cols}, "ly_ytd": ly.get(rid) if ly else None}
        cur, last = r["cells"]["ytd"], r["ly_ytd"]
        r["variance"] = None if last is None or cur is None else cur - last
        r["variance_pct"] = None if last is None or cur is None or not last else repo.pct(cur - last, abs(last))
        rows.append(r)
    return {"columns": [{"id": c["id"], "label": c["label"], "kind": c["kind"], "partial": c["partial"], "from_month": c["months"][0].strftime("%Y-%m"), "to_month": c["months"][-1].strftime("%Y-%m")} for c in cols],
            "rows": rows, "ly_ytd_available": bool(ly), "ly_ytd_note": "Last year's YTD is day aligned: complete months, plus days 1 to N of the same month." if rv.partial else "Last year's same months."}


def pivot_ledgers(rv: Review, pick, group: str) -> dict:
    """The ledgers behind one group, by month (the financial year to the as-of month), with last year's YTD (the aligned window for the partial month)."""
    conn, run_id = rv.sc.conn, rv.run["run_id"]
    cond = "AND release_status = 'Posted'" if rv.sc.basis == "posted" else ""
    months = repo.months_between(rv.fy_start(), rv.as_of_month)
    lym = [repo.add_months(m, -12) for m in months if not (m == rv.as_of_month and rv.partial)]
    rows = conn.execute(f"SELECT site_code, month, glcode, ledger_name, sum(credit - debit) AS net FROM pnl.v_gl_site_month WHERE run_id = %s AND group_label = %s {cond} AND month = ANY(%s) GROUP BY 1, 2, 3, 4",
                        (run_id, group, months + lym)).fetchall()
    led: dict[str, dict] = {}
    for r in rows:
        if not pick(r["site_code"]):
            continue
        d = led.setdefault(r["glcode"], {"glcode": r["glcode"], "ledger_name": r["ledger_name"], "cells": defaultdict(lambda: ZERO), "ly_ytd": ZERO})
        if r["month"] in months:
            d["cells"][r["month"].strftime("%Y-%m")] += r["net"]
            d["cells"]["ytd"] += r["net"]
        else:
            d["ly_ytd"] += r["net"]
    if rv.partial and rv.aligned is not None:
        for (site, g, key), v in rv.aligned["ledgers"].items():
            if g == group and pick(site):
                code, name = key.split("|", 1)
                d = led.setdefault(code, {"glcode": code, "ledger_name": name, "cells": defaultdict(lambda: ZERO), "ly_ytd": ZERO})
                d["ly_ytd"] += v
    out = sorted(({"glcode": d["glcode"], "ledger_name": d["ledger_name"], "cells": dict(d["cells"]), "ly_ytd": d["ly_ytd"]} for d in led.values()), key=lambda d: (d["cells"].get("ytd", ZERO), d["ledger_name"]))
    return {"group": group, "ledgers": out}
