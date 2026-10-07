"""Expense lines with PSF, the store heat map, peer comparison, the exception engine and data quality (definitions and thresholds in review.py)."""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date
from decimal import Decimal

from . import repository as repo
from .review import (HIGHER_IS_BETTER, MONTH_FLOOR, PEER_MIN, PSF_GROUPS, RULES, Review, comparable_months, eligible, median, peer_group, peer_keys, peer_stats, percentile, q4,
                     size_band, store_metrics)

ZERO = Decimal(0)
SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2}


def _f(x) -> float | None:
    return None if x is None else float(x)


# ───────────── expense lines: rupees, % of sales, last year, basis points, PSF, trend ─────────────


def psf_over_sites(rv: Review, sites: list[str], months: list[date], amount_of) -> tuple[Decimal | None, int]:
    """PSF over the stores that HAVE an area for every month: numerator and denominator both limited to them. -> (rupees per sq ft per month, stores used)."""
    num, den, used = ZERO, ZERO, 0
    for s in sites:
        a = rv.area(s, months)
        if a is None or a == 0:
            continue
        num += amount_of(s)
        den += a
        used += 1
    return (None if den == 0 else num / den), used


def expense_lines(rv: Review, pick) -> dict:
    months, ly_months = comparable_months(rv)
    if not months:
        return {"months": [], "lines": [], "note": "No complete month in the period."}
    sites = [c for c in rv.sc.stores if pick(c)]
    tot = repo.finish(repo.aggregate(rv.sc.data, pick, months[0], months[-1]))
    ly_tot = repo.finish(repo.aggregate(rv.sc.data, pick, ly_months[0], ly_months[-1])) if ly_months else None
    lines = []
    for g in rv.opex_groups:
        cost = -sum((rv.group_amount(s, months, g) for s in {c for (c, m) in rv.gm if m in months and pick(c)}), ZERO)
        ly_cost = None if not ly_months else -sum((rv.group_amount(s, ly_months, g) for s in {c for (c, m) in rv.gm if m in ly_months and pick(c)}), ZERO)
        pct_ = repo.pct(cost, tot["revenue"])
        ly_pct = None if ly_cost is None or not ly_tot or not ly_tot["revenue"] else repo.pct(ly_cost, ly_tot["revenue"])
        psf, used = psf_over_sites(rv, sites, months, lambda s, g=g: -rv.group_amount(s, months, g))
        lpsf = None
        if ly_months:
            lpsf, _ = psf_over_sites(rv, sites, ly_months, lambda s, g=g: -rv.group_amount(s, ly_months, g))
        trend = []
        for m in months:
            rev_m = repo.aggregate(rv.sc.data, pick, m, m)["revenue"]
            c_m = -sum((rv.gm.get((c, m), {}).get(g, ZERO) for c in {c for (c, mm) in rv.gm if mm == m and pick(c)}), ZERO)
            trend.append({"month": m.strftime("%Y-%m"), "cost": c_m, "pct_of_sales": repo.pct(c_m, rev_m)})
        lines.append({"group": g, "label": g.split("-", 1)[-1], "cost": cost, "pct_of_sales": pct_, "ly_cost": ly_cost, "ly_pct_of_sales": ly_pct, "bps": None if pct_ is None or ly_pct is None else q4((pct_ - ly_pct) * 100),
                      "psf": q4(psf), "ly_psf": q4(lpsf), "psf_stores": used, "trend": trend})
    lines.sort(key=lambda r: -r["cost"])
    return {"months": [m.strftime("%Y-%m") for m in months], "ly_months": None if not ly_months else [m.strftime("%Y-%m") for m in ly_months], "revenue": tot["revenue"], "ly_revenue": None if not ly_tot else ly_tot["revenue"],
            "stores": len(sites), "stores_with_area": sum(1 for s in sites if rv.area(s, months)), "lines": lines,
            "psf_note": "₹ per sq ft per month = cost / effective area (area x active days / calendar days), over the stores that have an area."}


# ───────────── the store heat map ─────────────

HEAT_COLUMNS = ["growth_pct", "gross_margin_pct", "opex_pct", "contribution_pct", "contribution", "sales_psf", "payroll_psf", "rent_psf", "power_psf", "ly_contribution_pct", "contribution_bps"]
HEAT_SORTS = {
    "worst_contribution_pct": ("contribution_pct", "asc"), "largest_decline_bps": ("contribution_bps", "asc"), "highest_opex_pct": ("opex_pct", "desc"), "worst_opex_deterioration": ("opex_bps", "desc"),
    "largest_loss": ("contribution", "asc"), "biggest_opportunity": ("opportunity", "desc"), "best_contribution_pct": ("contribution_pct", "desc"), "name": ("store_name", "asc"),
}


def all_store_metrics(rv: Review, pick) -> dict[str, dict]:
    months, ly_months = comparable_months(rv)
    out = {}
    for s in sorted(rv.sc.stores):
        if not pick(s) or not months:
            continue
        m = store_metrics(rv, s, months, ly_months)
        if m["revenue"] == 0 and m["cogs"] == 0 and m["opex"] == 0:
            continue
        out[s] = m
    return out


def opportunity(rv: Review, site: str, metrics: dict[str, dict]) -> tuple[Decimal | None, str]:
    """Rupees the store would earn if its contribution margin were its peers' median: (peer median % - store %) x its sales, only when positive. A pointer, not a forecast."""
    m = metrics[site]
    if m["contribution_pct"] is None or not eligible(m):
        return None, ""
    peers, basis = peer_group(rv, site, metrics, ("region", "vintage"))
    st = peer_stats(metrics, peers, "contribution_pct")
    if st["median"] is None:
        return None, basis
    gap = st["median"] - m["contribution_pct"]
    return (q4(gap / 100 * m["revenue"]) if gap > 0 else ZERO), basis


def heatmap(rv: Review, pick, sort: str, limit: int, offset: int, min_revenue: Decimal | None) -> dict:
    metrics = all_store_metrics(rv, pick)
    rows = []
    for s, m in metrics.items():
        if min_revenue is not None and m["revenue"] < min_revenue:
            continue
        site = rv.sc.sites.get(s) or {}
        opp, basis = opportunity(rv, s, metrics)
        rows.append({"site_code": s, "store_name": site.get("store_name"), "region": site.get("region_type"), "cluster": site.get("cluster_type"), "state": site.get("state"), "vintage": site.get("store_current_status"),
                     "area": site.get("area"), "opportunity": opp, "peer_basis": basis, **{k: m.get(k) for k in ("revenue", "gross_margin_pct", "opex_pct", "contribution", "contribution_pct", "growth_pct", "sales_psf", "payroll_psf", "rent_psf", "power_psf",
                                                                                                        "ly_contribution_pct", "contribution_bps", "gm_bps", "opex_bps", "ly_sales_psf", "ly_payroll_psf", "ly_rent_psf", "ly_power_psf")}})
    key, order = HEAT_SORTS[sort]
    rows.sort(key=lambda r: ((r[key] is None), (str(r[key] or "").lower() if key == "store_name" else (r[key] if r[key] is not None else 0))), reverse=(order == "desc"))
    if order == "desc":
        rows.sort(key=lambda r: r[key] is None)                    # missing values last in either direction
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    scales = {}
    for c in HEAT_COLUMNS:
        vals = [float(r[c]) for r in rows if r.get(c) is not None and eligible(metrics[r["site_code"]])]
        scales[c] = {"p10": q4(percentile(vals, 0.1)), "p50": q4(percentile(vals, 0.5)), "p90": q4(percentile(vals, 0.9)), "n": len(vals), "higher_is_better": HIGHER_IS_BETTER.get(c, c not in ("opex_pct",))} if vals else {"n": 0}
    return {"stores_total": len(rows), "returned": len(rows[offset: offset + limit]), "limit": limit, "offset": offset, "sort": sort, "stores": rows[offset: offset + limit], "scales": scales,
            "months": [m.strftime("%Y-%m") for m in comparable_months(rv)[0]], "note": "Colours are relative to the stores listed (10th to 90th percentile), never to a target. PSF is ₹ per sq ft per month; a store without an area has no PSF."}


# ───────────── peer comparison ─────────────

PEER_METRICS = ["growth_pct", "gross_margin_pct", "contribution_pct", "opex_pct", "sales_psf", "payroll_psf", "rent_psf", "power_psf"]
PEER_DIMS = {"default": ("region", "vintage"), "state": ("state",), "region": ("region",), "cluster": ("cluster",), "vintage": ("vintage",), "size_band": ("size_band",), "network": ("network",)}


def position(value: float | None, st: dict, higher: bool) -> str | None:
    if value is None or st["median"] is None:
        return None
    top, bottom = float(st["top_quartile"]), float(st["bottom_quartile"])
    if (value >= top) if higher else (value <= top):
        return "top quartile"
    if (value <= bottom) if higher else (value >= bottom):
        return "bottom quartile"
    return "middle"


def peers_of(rv: Review, pick, site: str) -> dict:
    metrics = all_store_metrics(rv, lambda c: True)           # peers are taken from the whole network, whatever filters the page has
    if site not in metrics:
        return {}
    mine = metrics[site]
    keys = peer_keys(rv.sc.sites.get(site))
    out = {"site_code": site, "store": {k: mine.get(k) for k in PEER_METRICS}, "keys": keys, "groups": []}
    for name, dims in PEER_DIMS.items():
        peers, basis = peer_group(rv, site, metrics, dims)
        rows = []
        for k in PEER_METRICS:
            st = peer_stats(metrics, peers, k)
            v = _f(mine.get(k))
            rows.append({"metric": k, "store": mine.get(k), "peer_median": st["median"], "top_quartile": st["top_quartile"], "bottom_quartile": st["bottom_quartile"], "peers_with_value": st["n"],
                         "position": position(v, st, HIGHER_IS_BETTER[k]), "vs_median": None if v is None or st["median"] is None else q4(Decimal(str(v)) - st["median"])})
        out["groups"].append({"dimension": name, "basis": basis, "requested": " + ".join(dims), "peers": len(peers), "metrics": rows})
    return out


# ───────────── the exception engine ─────────────


def _series(rv: Review, site: str, group: str, months: list[date]) -> list[Decimal]:
    return [-rv.gm.get((site, m), {}).get(group, ZERO) for m in months]


def _rev(rv: Review, site: str, m: date) -> Decimal:
    a = rv.sc.data.get((site, m))
    return a["revenue"] if a else ZERO


def _lakh(x: Decimal | float) -> str:
    return f"₹{abs(float(x)) / 1e5:,.1f} L"


def _severity(flags: int, impact: float) -> str:
    if impact >= 1_000_000 or (flags >= 2 and impact >= 500_000):
        return "Critical"
    if impact >= 100_000 or flags >= 2:
        return "High"
    return "Medium"


def review_month(rv: Review) -> date | None:
    hi = min(rv.sc.hi, rv.complete_hi)
    return hi if hi >= repo.add_months(rv.first_month, 3) else None


def expense_exceptions(rv: Review, pick, limit: int = 200) -> dict:
    L = review_month(rv)
    if L is None:
        return {"month": None, "total": 0, "by_severity": {}, "exceptions": [], "rules": RULES, "note": "Not enough complete months of history to review."}
    base_m = [repo.add_months(L, -i) for i in (3, 2, 1)]
    hist6 = [repo.add_months(L, -i) for i in range(6, 0, -1) if repo.add_months(L, -i) >= rv.first_month]
    hist5 = [repo.add_months(L, -i) for i in range(5, 0, -1)]
    stores = [s for s in rv.sc.stores if pick(s)]
    metrics_L = {s: _rev(rv, s, L) for s in rv.sc.stores}
    prov = L in repo.provisional_months(rv.sc.data, L, L)
    out = []
    for g in rv.opex_groups:
        # peer medians of share of sales and PSF in the review month, per peer basis (region + vintage; fallback state; network)
        shares = {s: (-rv.gm.get((s, L), {}).get(g, ZERO)) / metrics_L[s] for s in rv.sc.stores if metrics_L[s] >= MONTH_FLOOR}
        psfs = {s: (-rv.gm.get((s, L), {}).get(g, ZERO)) / rv.eff[(s, L)] for s in rv.sc.stores if metrics_L[s] >= MONTH_FLOOR and rv.eff.get((s, L))}
        for s in stores:
            cur = -rv.gm.get((s, L), {}).get(g, ZERO)
            base_vals = _series(rv, s, g, base_m)
            base = sum(base_vals, ZERO) / 3
            if cur < 25_000 and base < 25_000:
                continue
            rev = metrics_L[s]
            flags: list[str] = []
            why: list[str] = []
            if base > 0 and cur >= base * Decimal("1.3") and cur - base >= 25_000:
                flags.append("SUDDEN_INCREASE")
                why.append(f"{_lakh(cur)} against a 3-month average of {_lakh(base)} ({float((cur - base) / base) * 100:+.0f}%)")
            if base >= 25_000 and cur <= base * Decimal("0.5"):
                flags.append("SUDDEN_DECREASE")
                why.append(f"{_lakh(cur)} against a 3-month average of {_lakh(base)} ({float((cur - base) / base) * 100:+.0f}%): check for a missing posting, late invoice, wrong cost centre or missing accrual")
            pct_cur = float(cur / rev) * 100 if rev >= MONTH_FLOOR else None
            hist = [float(-rv.gm.get((s, m), {}).get(g, ZERO) / _rev(rv, s, m)) * 100 for m in hist6 if _rev(rv, s, m) >= MONTH_FLOOR]
            if pct_cur is not None and len(hist) >= 3:
                med = statistics.median(hist)
                if med > 0 and pct_cur >= med * 1.4 and pct_cur - med >= 0.5:
                    flags.append("SHARE_OF_SALES")
                    why.append(f"{pct_cur:.1f}% of sales against its usual {med:.1f}%")
            peers, peer_basis = _peers_L(rv, s, metrics_L)
            ps = [shares[c] for c in peers if c in shares]
            peer_med = float(statistics.median(ps)) * 100 if len(ps) >= 3 else None
            if pct_cur is not None and peer_med is not None and peer_med > 0 and pct_cur >= 2.0 * peer_med and pct_cur - peer_med >= 0.3:
                flags.append("PEER")
                why.append(f"{pct_cur / peer_med:.1f} times the peer median share of sales ({peer_med:.1f}%, {peer_basis})")
            psf_cur = float(cur / rv.eff[(s, L)]) if rv.eff.get((s, L)) else None
            pp = [psfs[c] for c in peers if c in psfs]
            psf_med = float(statistics.median(pp)) if len(pp) >= 3 else None
            if psf_cur is not None and psf_med and psf_med > 0 and psf_cur >= 1.5 * psf_med:
                flags.append("PSF")
                why.append(f"₹{psf_cur:,.1f} per sq ft against a peer median of ₹{psf_med:,.1f}")
            h5 = [float(x) for x in _series(rv, s, g, hist5)]
            if all(m >= rv.first_month for m in hist5) and len(h5) == 5 and statistics.mean(h5) > 0:
                mean5, sd5 = statistics.mean(h5), statistics.pstdev(h5)
                move = abs(float(cur) - mean5)
                if sd5 / mean5 < 0.15 and move >= 25_000 and ((sd5 > 0 and move >= 3 * sd5) or (sd5 == 0 and move >= 0.25 * mean5)):
                    flags.append("TREND_BREAK")
                    why.append(f"steady near {_lakh(mean5)} for five months, then {_lakh(cur)}")
            if not flags:
                continue
            impact = abs(float(cur - base))
            site = rv.sc.sites.get(s) or {}
            out.append({"severity": _severity(len(flags), impact), "site_code": s, "store_name": site.get("store_name"), "region": site.get("region_type"), "state": site.get("state"), "group": g, "label": g.split("-", 1)[-1],
                        "month": L.strftime("%Y-%m"), "current": cur, "expected": q4(base), "variance": q4(cur - base), "variance_pct": None if base == 0 else repo.pct(cur - base, base), "pct_of_sales": None if pct_cur is None else q4(Decimal(str(pct_cur))),
                        "psf": None if psf_cur is None else q4(Decimal(str(psf_cur))), "peer_pct_of_sales": None if peer_med is None else q4(Decimal(str(peer_med))), "peer_psf": None if psf_med is None else q4(Decimal(str(psf_med))),
                        "flags": flags, "why": "; ".join(why), "impact": q4(Decimal(str(impact))), "provisional_month": prov})
    out.sort(key=lambda r: (SEVERITY_ORDER[r["severity"]], -float(r["impact"])))
    counts = defaultdict(int)
    for r in out:
        counts[r["severity"]] += 1
    return {"month": L.strftime("%Y-%m"), "total": len(out), "by_severity": dict(counts), "exceptions": out[:limit], "rules": RULES, "provisional_month": prov,
            "drill": "exception -> store -> expense group -> ledger -> month (the entry layer will extend it to the voucher)"}


def _peers_L(rv: Review, site: str, rev_L: dict[str, Decimal]) -> tuple[list[str], str]:
    """Peers for a monthly review: the same region and vintage, widening to the state and then the network, among stores with at least ₹10 lakh of sales in the month."""
    mine = peer_keys(rv.sc.sites.get(site))
    for dims, label in ((("region", "vintage"), "region + vintage"), (("state",), "state"), (("network",), "whole network")):
        if any(mine.get(d) in (None, "-") for d in dims if d != "network"):
            continue
        peers = [c for c in rev_L if c != site and rev_L[c] >= MONTH_FLOOR and all(peer_keys(rv.sc.sites.get(c)).get(d) == mine.get(d) for d in dims)]
        if len(peers) >= PEER_MIN:
            return peers, label
    return [c for c in rev_L if c != site and rev_L[c] >= MONTH_FLOOR], "whole network"


def revenue_exceptions(rv: Review, pick, limit: int = 200) -> dict:
    L = review_month(rv)
    if L is None:
        return {"month": None, "total": 0, "by_severity": {}, "exceptions": [], "rules": RULES, "note": "Not enough complete months of history to review."}
    LY = repo.add_months(L, -12)
    has_ly = LY >= rv.first_month
    base_m = [repo.add_months(L, -i) for i in (3, 2, 1)]
    stores = [s for s in rv.sc.stores if pick(s)]
    rev_L = {s: _rev(rv, s, L) for s in rv.sc.stores}
    fin = lambda s, m: repo.finish(rv.sc.data.get((s, m), repo.blank()))                      # noqa: E731
    psf_L = {s: rev_L[s] / rv.eff[(s, L)] for s in rv.sc.stores if rev_L[s] >= MONTH_FLOOR and rv.eff.get((s, L))}
    growth = {}
    for s in rv.sc.stores:
        ly = _rev(rv, s, LY) if has_ly else ZERO
        if has_ly and rev_L[s] >= MONTH_FLOOR and ly >= MONTH_FLOOR:
            growth[s] = float((rev_L[s] - ly) / ly) * 100
    prov = L in repo.provisional_months(rv.sc.data, L, L)
    out = []
    for s in stores:
        flags, why = [], []
        site = rv.sc.sites.get(s) or {}
        cur = fin(s, L)
        if cur["revenue"] <= 0 and rev_L[s] == 0:
            continue
        base = sum((_rev(rv, s, m) for m in base_m), ZERO) / 3
        impact = 0.0
        if base >= MONTH_FLOOR and rev_L[s] <= base * Decimal("0.75"):
            flags.append("SALES_DROP")
            why.append(f"sales {_lakh(rev_L[s])} against a 3-month average of {_lakh(base)} ({float((rev_L[s] - base) / base) * 100:+.0f}%)")
            impact = max(impact, float(base - rev_L[s]))
        ly = fin(s, LY) if has_ly else None
        eff_L, eff_LY = rv.eff.get((s, L)), rv.eff.get((s, LY))
        if ly and eff_L and eff_LY and rev_L[s] >= MONTH_FLOOR and ly["revenue"] >= MONTH_FLOOR:
            p_now, p_ly = float(rev_L[s] / eff_L), float(ly["revenue"] / eff_LY)
            if p_now <= p_ly * 0.85:
                flags.append("SALES_PSF_DROP")
                why.append(f"₹{p_now:,.0f} per sq ft against ₹{p_ly:,.0f} in the same month last year ({(p_now / p_ly - 1) * 100:+.0f}%)")
                impact = max(impact, (p_ly - p_now) * float(eff_L))
        g = growth.get(s)
        if ly and g is not None and cur["gross_margin_pct"] is not None and ly["gross_margin_pct"] is not None:
            gm_bps = float((cur["gross_margin_pct"] - ly["gross_margin_pct"]) * 100)
            if g >= 15 and gm_bps <= -150:
                flags.append("GROWTH_MARGIN_FALL")
                why.append(f"sales {g:+.0f}% but gross margin {gm_bps:+.0f} bps against last year")
                impact = max(impact, abs(gm_bps) / 10000 * float(rev_L[s]))
            if g >= 10 and cur["contribution"] <= ly["contribution"]:
                flags.append("GROWTH_NO_PROFIT")
                why.append(f"sales {g:+.0f}% but contribution {_lakh(cur['contribution'])} against {_lakh(ly['contribution'])} last year")
                impact = max(impact, float(ly["contribution"] - cur["contribution"]))
            if cur["opex_pct"] is not None and ly["opex_pct"] is not None and g > 0:
                ob = float((cur["opex_pct"] - ly["opex_pct"]) * 100)
                if ob >= 200:
                    flags.append("COST_DETERIORATION")
                    why.append(f"sales {g:+.0f}% while store opex rose {ob:+.0f} bps of sales")
                    impact = max(impact, ob / 10000 * float(rev_L[s]))
        peers, basis = _peers_L(rv, s, rev_L)
        op = site.get("opening_date")
        if op and op >= date(2005, 1, 1) and (L.year - op.year) * 12 + L.month - op.month <= 12 and s in psf_L:
            newp = [psf_L[c] for c in peers if c in psf_L and (rv.sc.sites.get(c) or {}).get("store_current_status") == "NEW STORE"]
            if len(newp) >= 3:
                med = float(statistics.median(newp))
                if float(psf_L[s]) < 0.7 * med:
                    flags.append("NEW_STORE_BELOW_RAMP")
                    why.append(f"new store at ₹{float(psf_L[s]):,.0f} sales per sq ft against ₹{med:,.0f} for new stores in {basis}")
                    impact = max(impact, (med - float(psf_L[s])) * float(rv.eff.get((s, L)) or 0))
        if site.get("store_current_status") == "SAME STORE" and g is not None:
            pg = [growth[c] for c in peers if c in growth and (rv.sc.sites.get(c) or {}).get("store_current_status") == "SAME STORE"]
            if len(pg) >= 3 and g <= statistics.median(pg) - 15:
                flags.append("SAME_STORE_BELOW_PEER")
                why.append(f"same-store sales {g:+.0f}% against a peer median of {statistics.median(pg):+.0f}% ({basis})")
                impact = max(impact, (statistics.median(pg) - g) / 100 * float(_rev(rv, s, LY)))
        if not flags:
            continue
        out.append({"severity": _severity(len(flags), impact), "site_code": s, "store_name": site.get("store_name"), "region": site.get("region_type"), "state": site.get("state"), "month": L.strftime("%Y-%m"),
                    "revenue": rev_L[s], "baseline_revenue": q4(base), "growth_pct": None if g is None else q4(Decimal(str(g))), "gross_margin_pct": cur["gross_margin_pct"], "contribution": cur["contribution"],
                    "sales_psf": None if s not in psf_L else q4(psf_L[s]), "flags": flags, "why": "; ".join(why), "impact": q4(Decimal(str(impact))), "provisional_month": prov})
    out.sort(key=lambda r: (SEVERITY_ORDER[r["severity"]], -float(r["impact"])))
    counts = defaultdict(int)
    for r in out:
        counts[r["severity"]] += 1
    return {"month": L.strftime("%Y-%m"), "total": len(out), "by_severity": dict(counts), "exceptions": out[:limit], "rules": RULES, "provisional_month": prov}


# ───────────── data quality ─────────────


def quality(rv: Review, conn) -> dict:
    run_id = rv.run["run_id"]
    sites = rv.sc.sites
    store_codes = rv.sc.stores
    no_area = [s for s in store_codes if not (sites.get(s) or {}).get("area")]
    placeholder = [s for s in store_codes if (sites.get(s) or {}).get("opening_date") is None or (sites.get(s) or {}).get("opening_date") < date(2005, 1, 1)]
    closed_unknown = conn.execute("SELECT s.site_code, s.store_name, s.store_status FROM pnl.v_site s WHERE s.run_id = %s AND s.store_status IN ('CLOSED', 'IN-ACTIVE') AND (s.last_bill_date IS NULL OR s.last_bill_date < DATE '2005-01-01') "
                                  "AND EXISTS (SELECT 1 FROM pnl.v_gl_site_month g WHERE g.run_id = s.run_id AND g.site_code = s.site_code AND g.ledger_name = 'Sales - POS') ORDER BY 1", (run_id,)).fetchall()
    reasons = conn.execute("SELECT reason, count(*) AS n FROM pnl.v_store_month_effective_area WHERE run_id = %s GROUP BY 1 ORDER BY 2 DESC", (run_id,)).fetchall()
    months = repo.months_between(rv.first_month, rv.complete_hi)
    cogs_pct = []
    for m in months:
        t = repo.finish(repo.aggregate(rv.sc.data, lambda c: True, m, m))
        cogs_pct.append({"month": m.strftime("%Y-%m"), "cogs_pct_of_sales": repo.pct(t["cogs"], t["revenue"])})
    vals = [float(r["cogs_pct_of_sales"]) for r in cogs_pct if r["cogs_pct_of_sales"] is not None]
    med = statistics.median(vals) if vals else None
    for r in cogs_pct:
        r["outlier"] = bool(med is not None and r["cogs_pct_of_sales"] is not None and float(r["cogs_pct_of_sales"]) >= med + 6)
    return {"stores": len(store_codes), "stores_without_area": {"count": len(no_area), "sites": [{"site_code": s, "store_name": (sites.get(s) or {}).get("store_name")} for s in sorted(no_area)[:50]],
                                                                    "effect": "no per-sq-ft measure for these stores; they are left out of every PSF average (never given an average area)"},
            "stores_with_placeholder_opening_date": {"count": len(placeholder), "effect": "treated as open for the whole window (reason OPENING_DATE_PLACEHOLDER); a store opened mid-month before the data window would be over-counted"},
            "closed_stores_without_a_closing_date": {"count": len(closed_unknown), "sites": [{"site_code": r["site_code"], "store_name": r["store_name"], "status": r["store_status"]} for r in closed_unknown[:50]],
                                                   "effect": "the last bill date is not a real date, so the store is treated as open every month (reason CLOSURE_DATE_UNKNOWN)"},
            "effective_area_reasons": reasons, "cogs_pct_by_month": cogs_pct, "cogs_typical_pct": None if med is None else q4(Decimal(str(med))),
            "area_units_note": "AREA in the site master has no comment: the figures (median about 8,150) read as square feet. Finance to confirm the unit."}
