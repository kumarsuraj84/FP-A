"""The P&L REVIEW layer: measures and exception rules computed from the verified mart (never from the frontend).

Definitions, in one place:
  Sign         every P&L line is a PROFIT EFFECT (credit less debit): revenue is positive, a cost is negative. "Cost" below means -effect.
  PSF          rupees per square foot PER MONTH = sum of the amount / sum of the monthly EFFECTIVE AREA over the same stores and months. Effective Area = Actual Area x Active Days in Month
               / Calendar Days in Month (the mart's store_month_effective_area, derived at load and re-derived in SQL). A store with no area has no PSF; it is never given an average one.
  Comparable   growth and last-year measures use COMPLETE months only; a partial current month is compared only through the day-aligned window (days 1..N of both years).
  Peers        stores of the same region and vintage (same / new store); if fewer than PEER_MIN of them qualify, the same state, then the whole network, and the response says which.
  Exceptions   REVIEW HEURISTICS, not accounting: the thresholds are listed in RULES, returned with every response, and a flag always says why it fired. They surface what a reviewer
               should open; they never change a number.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from . import repository as repo

ZERO = Decimal(0)
OPEX = "STORE_OPEX"
PAYROLL, RENT, POWER = "02-Employee Cost", "01-Rent", "03-Power and Fuel Expenses"
PSF_GROUPS = {"payroll_psf": PAYROLL, "rent_psf": RENT, "power_psf": POWER}
PEER_MIN = 5
SALES_FLOOR = Decimal(1e7)             # a store needs ₹1 Cr of net sales in the window to be a peer / to be ranked on a percentage
MONTH_FLOOR = Decimal(1e6)             # ₹10 lakh of net sales in the month to be a peer for a monthly exception
SIZE_BANDS = [(0, 7000, "under 7,000 sq ft"), (7000, 9000, "7,000 to 9,000"), (9000, 11000, "9,000 to 11,000"), (11000, 10**9, "11,000 and over")]

RULES = {
    "baseline": "the average of the 3 complete months before the month reviewed",
    "sudden_increase": "cost at least 30% above baseline and at least ₹25,000 above it",
    "sudden_decrease": "baseline at least ₹25,000 and cost at least 50% below it (a fall can mean a missing posting, a late invoice, a wrong cost centre or a missing accrual)",
    "share_of_sales": "cost as a share of sales at least 40% above the store's own median of the prior 6 months, and at least 0.5 percentage points above it",
    "peer": "cost as a share of sales at least 2.0 times the peer median and at least 0.3 percentage points above it",
    "psf": "cost per sq ft at least 1.5 times the peer median",
    "trend_break": "stable for 5 months (variation under 15%), then a move of at least 3 standard deviations (25% when it was perfectly flat)",
    "sales_drop": "sales at least 25% below the average of the prior 3 complete months",
    "sales_psf_drop": "sales per sq ft at least 15% below the same month last year",
    "growth_margin_fall": "sales growth of at least 15% while gross margin fell at least 150 bps against last year",
    "growth_no_profit": "sales growth of at least 10% while contribution in rupees did not grow",
    "cost_deterioration": "sales growing while store opex rose at least 200 bps of sales against last year",
    "new_store_ramp": "opened within 12 months and sales per sq ft below 70% of the median of new stores in the region",
    "same_store_peer": "same store whose growth is at least 15 points below the peer median",
    "severity": "Critical: two or more flags and an impact of ₹5 lakh or more, or an impact of ₹10 lakh or more. High: an impact of ₹1 lakh or more, or two or more flags. Medium: the rest.",
    "peers": f"same region and vintage; fewer than {PEER_MIN} qualifying stores falls back to the same state, then the whole network",
}


def q4(x: Decimal | float | None) -> Decimal | None:
    return None if x is None else Decimal(str(x)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def median(xs: list[float]) -> float | None:
    return statistics.median(xs) if xs else None


def percentile(xs: list[float], p: float) -> float | None:
    """Linear interpolation between order statistics (the usual 'inclusive' definition)."""
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


# ───────────── data access ─────────────


def effective_areas(conn, run_id: str) -> dict[tuple[str, date], Decimal | None]:
    return {(r["site_code"], r["month"]): r["effective_area"] for r in conn.execute("SELECT site_code, month, effective_area FROM pnl.v_store_month_effective_area WHERE run_id = %s", (run_id,)).fetchall()}


def group_months(conn, run_id: str, basis: str) -> tuple[dict[tuple[str, date], dict[str, Decimal]], dict[str, str]]:
    """{(site, month): {group_label: profit effect}}, and {group_label: section}. UNMAPPED ledgers are never in it."""
    cond = "AND release_status = 'Posted'" if basis == "posted" else ""
    out: dict[tuple[str, date], dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    sec: dict[str, str] = {}
    for r in conn.execute(f"SELECT site_code, month, section, group_label, sum(credit - debit) AS net FROM pnl.v_gl_site_month WHERE run_id = %s AND section <> 'UNMAPPED' {cond} GROUP BY 1, 2, 3, 4", (run_id,)).fetchall():
        out[(r["site_code"], r["month"])][r["group_label"]] += r["net"]
        sec[r["group_label"]] = r["section"]
    return out, sec


def aligned_ly(conn, run: dict, basis: str) -> dict | None:
    """Last year's day-aligned window (days 1..N of last year's as-of month): per site the totals, per site and group the amounts, and COGS from the early part. None if the run has none."""
    if run.get("ly_aligned_month") is None:
        return None
    cond = "AND release_status = 'Posted'" if basis == "posted" else ""
    sites: dict[str, dict] = defaultdict(repo.blank)
    groups: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
    ledgers: dict[tuple[str, str, str], Decimal] = defaultdict(lambda: ZERO)
    keymap = {"REVENUE": "revenue", "COGS_BOOKS": "cogs_books", "STORE_OPEX": "opex", "OTHER_INCOME": "other_income", "FINANCE_COST": "finance_cost", "UNMAPPED": "unmapped"}
    for r in conn.execute(f"SELECT site_code, section, group_label, glcode, ledger_name, sum(credit - debit) AS net FROM pnl.v_gl_aligned WHERE run_id = %s {cond} GROUP BY 1, 2, 3, 4, 5", (run["run_id"],)).fetchall():
        sites[r["site_code"]][keymap[r["section"]]] += r["net"]
        if r["group_label"] is not None:
            groups[(r["site_code"], r["group_label"])] += r["net"]
            ledgers[(r["site_code"], r["group_label"], r["glcode"] + "|" + r["ledger_name"])] += r["net"]
    for r in conn.execute("SELECT site_code, sum(cogs_early) AS cogs, sum(sl_v_early - tax_early) AS ts FROM pnl.v_cogs_site_month WHERE run_id = %s AND month = %s GROUP BY 1", (run["run_id"], run["ly_aligned_month"])).fetchall():
        sites[r["site_code"]]["cogs"] += r["cogs"]
        sites[r["site_code"]]["table_sales"] += r["ts"]
    return {"month": run["ly_aligned_month"], "days": run["aligned_days"], "sites": dict(sites), "groups": dict(groups), "ledgers": dict(ledgers)}


# ───────────── the review context ─────────────


class Review:
    """What every review endpoint needs, built once per request from the Scope: months, store set, effective areas, group-level amounts, the aligned window."""

    def __init__(self, sc):
        self.sc = sc
        run = sc.run
        self.run = run
        self.as_of: date = run["as_of_date"]
        self.as_of_month = date(self.as_of.year, self.as_of.month, 1)
        from calendar import monthrange

        self.partial = self.as_of.day < monthrange(self.as_of.year, self.as_of.month)[1]      # the as-of month is not finished: it holds days 1..N only
        self.eff = effective_areas(sc.conn, run["run_id"])
        self.gm, self.section_of = group_months(sc.conn, run["run_id"], sc.basis)
        self.aligned = aligned_ly(sc.conn, run, sc.basis)
        self.first_month = sc.first_month
        self.complete_hi = repo.add_months(self.as_of_month, -1) if self.partial else self.as_of_month
        self.opex_groups = sorted(g for g, s in self.section_of.items() if s == OPEX)

    # months and windows
    def fy_start(self) -> date:
        return date(self.as_of.year if self.as_of.month >= 4 else self.as_of.year - 1, 4, 1)

    def quarter_start(self, m: date | None = None) -> date:
        m = m or self.as_of_month
        return date(m.year, ((m.month - 1) // 3) * 3 + 1, 1)

    def stores_in(self) -> set[str]:
        return {c for c in self.sc.stores if self.sc.in_scope(c)}

    # amounts
    def group_amount(self, site: str, months: list[date], group: str) -> Decimal:
        return sum((self.gm.get((site, m), {}).get(group, ZERO) for m in months), ZERO)

    def area(self, site: str, months: list[date]) -> Decimal | None:
        parts = [self.eff.get((site, m)) for m in months]
        if not parts or any(p is None for p in parts):
            return None
        return sum(parts, ZERO)

    def psf(self, amount: Decimal, site_months: list[tuple[str, date]]) -> Decimal | None:
        """Rupees per sq ft per month for a set of (site, month): amount / sum of effective areas. None if any of them has no area (an average is never invented)."""
        total = ZERO
        for k in site_months:
            e = self.eff.get(k)
            if e is None:
                return None
            total += e
        return None if total == 0 else amount / total


# ───────────── per-store metrics over a window ─────────────


def store_metrics(rv: Review, site: str, months: list[date], ly_months: list[date] | None) -> dict:
    sc = rv.sc
    cur = repo.finish(repo.aggregate(sc.data, lambda c: c == site, months[0], months[-1])) if months else repo.finish(repo.blank())
    out = {"revenue": cur["revenue"], "cogs": cur["cogs"], "gross_margin": cur["gross_margin"], "gross_margin_pct": cur["gross_margin_pct"], "opex": cur["opex"], "opex_pct": cur["opex_pct"],
           "contribution": cur["contribution"], "contribution_pct": cur["contribution_pct"]}
    sm = [(site, m) for m in months]
    out["sales_psf"] = rv.psf(cur["revenue"], sm)
    for k, g in PSF_GROUPS.items():
        out[k] = rv.psf(-rv.group_amount(site, months, g), sm)
    if ly_months:
        ly = repo.finish(repo.aggregate(sc.data, lambda c: c == site, ly_months[0], ly_months[-1]))
        lsm = [(site, m) for m in ly_months]
        out.update({"ly_revenue": ly["revenue"], "ly_gross_margin_pct": ly["gross_margin_pct"], "ly_opex_pct": ly["opex_pct"], "ly_contribution": ly["contribution"], "ly_contribution_pct": ly["contribution_pct"],
                    "ly_sales_psf": rv.psf(ly["revenue"], lsm)})
        for k, g in PSF_GROUPS.items():
            out["ly_" + k] = rv.psf(-rv.group_amount(site, ly_months, g), lsm)
        out["growth_pct"] = repo.pct(cur["revenue"] - ly["revenue"], ly["revenue"]) if ly["revenue"] else None
    else:
        out.update({k: None for k in ("ly_revenue", "ly_gross_margin_pct", "ly_opex_pct", "ly_contribution", "ly_contribution_pct", "ly_sales_psf", "growth_pct", "ly_payroll_psf", "ly_rent_psf", "ly_power_psf")})
    for key, a, b in (("gm_bps", "gross_margin_pct", "ly_gross_margin_pct"), ("opex_bps", "opex_pct", "ly_opex_pct"), ("contribution_bps", "contribution_pct", "ly_contribution_pct")):
        out[key] = None if out[a] is None or out[b] is None else (out[a] - out[b]) * 100          # percentage points x 100 = basis points
    return out


def comparable_months(rv: Review) -> tuple[list[date], list[date] | None]:
    lo, hi = rv.sc.lo, min(rv.sc.hi, rv.complete_hi)
    if hi < lo:
        return [], None
    months = repo.months_between(lo, hi)
    ly = repo.last_year(lo, hi, rv.first_month)
    return months, (repo.months_between(*ly) if ly else None)


# ───────────── peers ─────────────

#: metric -> True when a higher value is better (the top quartile is then the 75th percentile, otherwise the 25th)
HIGHER_IS_BETTER = {"growth_pct": True, "gross_margin_pct": True, "contribution_pct": True, "opex_pct": False, "sales_psf": True, "payroll_psf": False, "rent_psf": False, "power_psf": False}


def size_band(area: Decimal | None) -> str | None:
    if area is None or area <= 0:
        return None
    for lo, hi, label in SIZE_BANDS:
        if lo <= area < hi:
            return label
    return None


def peer_keys(site: dict | None) -> dict[str, str | None]:
    s = site or {}
    return {"region": s.get("region_type"), "state": s.get("state"), "cluster": s.get("cluster_type"), "vintage": s.get("store_current_status"), "size_band": size_band(s.get("area")), "network": "all"}


def eligible(m: dict) -> bool:
    return m["revenue"] >= SALES_FLOOR


def peer_group(rv: Review, site: str, metrics: dict[str, dict], dims: tuple[str, ...]) -> tuple[list[str], str]:
    """The peers of a store: the stores sharing every dimension in `dims`; widening (region+vintage -> state -> network) until at least PEER_MIN qualify."""
    mine = peer_keys(rv.sc.sites.get(site))
    chain = [dims, ("state",), ("network",)] if dims != ("network",) else [dims]
    for ds in chain:
        if any(mine.get(d) in (None, "-") for d in ds if d != "network"):
            continue
        peers = [c for c, m in metrics.items() if c != site and eligible(m) and all(peer_keys(rv.sc.sites.get(c)).get(d) == mine.get(d) for d in ds)]
        if len(peers) >= PEER_MIN:
            return peers, " + ".join(ds) if ds != ("network",) else "whole network"
    return [c for c, m in metrics.items() if c != site and eligible(m)], "whole network"


def peer_stats(metrics: dict[str, dict], peers: list[str], key: str) -> dict:
    vals = [float(metrics[c][key]) for c in peers if metrics[c].get(key) is not None]
    if not vals:
        return {"n": 0, "median": None, "top_quartile": None, "bottom_quartile": None}
    hi = HIGHER_IS_BETTER[key]
    return {"n": len(vals), "median": q4(median(vals)), "top_quartile": q4(percentile(vals, 0.75 if hi else 0.25)), "bottom_quartile": q4(percentile(vals, 0.25 if hi else 0.75))}
