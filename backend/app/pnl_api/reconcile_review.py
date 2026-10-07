"""
Mart = API checks for the P&L REVIEW layer (pivot, MTD/QTD/YTD, expense lines and PSF, heat map, exceptions, data quality).

Everything the review endpoints serve is read back through the API and compared, exactly and with zero tolerance, against figures re-derived from the mart rows with plain, separately
written arithmetic (SQL-grouped rows summed here; none of the API's own functions is reused). A run loaded before the review foundation (no effective-area rows) is checked for the
original measures only, and the gate says so.
"""
from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import date
from decimal import Decimal

ZERO = Decimal(0)


def D(x) -> Decimal:
    return Decimal(str(x)) if x is not None else ZERO


def add_months(d: date, n: int) -> date:
    k = d.year * 12 + d.month - 1 + n
    return date(k // 12, k % 12 + 1, 1)


def months_between(lo: date, hi: date) -> list[date]:
    out, d = [], lo
    while d <= hi:
        out.append(d)
        d = add_months(d, 1)
    return out


def mart_rows(db, run_id: str, basis: str = "all") -> dict:
    cond = "AND release_status = 'Posted'" if basis == "posted" else ""
    with db.session("pnl_verifier") as c:
        run = c.execute("SELECT * FROM pnl.v_serving_run WHERE run_id = %s", (run_id,)).fetchone()
        gl = c.execute(f"SELECT site_code, month, section, group_label, glcode, sum(credit - debit) AS net FROM pnl.v_gl_site_month WHERE run_id = %s AND section <> 'UNMAPPED' {cond} GROUP BY 1, 2, 3, 4, 5", (run_id,)).fetchall()
        cogs = c.execute("SELECT site_code, month, cogs_v, sl_v - tax_amt AS sales, cogs_early, sl_v_early - tax_early AS sales_early FROM pnl.v_cogs_site_month WHERE run_id = %s", (run_id,)).fetchall()
        eff = c.execute("SELECT site_code, month, effective_area FROM pnl.v_store_month_effective_area WHERE run_id = %s", (run_id,)).fetchall()
        aligned = c.execute(f"SELECT site_code, section, group_label, sum(credit - debit) AS net FROM pnl.v_gl_aligned WHERE run_id = %s AND section <> 'UNMAPPED' {cond} GROUP BY 1, 2, 3", (run_id,)).fetchall()
        sites = {r["site_code"]: r for r in c.execute("SELECT * FROM pnl.v_site WHERE run_id = %s", (run_id,)).fetchall()}
        stores = {r["site_code"] for r in c.execute("SELECT DISTINCT site_code FROM pnl.v_gl_site_month WHERE run_id = %s AND ledger_name = 'Sales - POS'", (run_id,)).fetchall()}
    return {"run": run, "gl": gl, "cogs": cogs, "eff": {(r["site_code"], r["month"]): r["effective_area"] for r in eff}, "aligned": aligned, "sites": sites, "stores": stores}


class Figures:
    """Independent re-derivation: per (site, month) every line, plus the aligned window of last year."""

    def __init__(self, m: dict):
        self.m = m
        self.sec = defaultdict(lambda: defaultdict(lambda: ZERO))          # (site, month) -> section -> net
        self.grp = defaultdict(lambda: defaultdict(lambda: ZERO))          # (site, month) -> group -> net
        for r in m["gl"]:
            self.sec[(r["site_code"], r["month"])][r["section"]] += r["net"]
            self.grp[(r["site_code"], r["month"])][r["group_label"]] += r["net"]
        self.cogs = {(r["site_code"], r["month"]): r for r in m["cogs"]}
        self.al_sec = defaultdict(lambda: defaultdict(lambda: ZERO))
        self.al_grp = defaultdict(lambda: defaultdict(lambda: ZERO))
        for r in m["aligned"]:
            self.al_sec[r["site_code"]][r["section"]] += r["net"]
            self.al_grp[r["site_code"]][r["group_label"]] += r["net"]
        run = m["run"]
        self.as_of = run["as_of_date"]
        self.as_of_month = date(self.as_of.year, self.as_of.month, 1)
        self.partial = self.as_of.day < monthrange(self.as_of.year, self.as_of.month)[1]
        self.ly_month = run.get("ly_aligned_month")

    def line(self, sites, months, ly=False):
        t = {"revenue": ZERO, "cogs": ZERO, "cogs_books": ZERO, "opex": ZERO}
        for m in months:
            lm = add_months(m, -12)
            aligned = ly and m == self.as_of_month and self.partial
            for s in sites:
                if aligned:
                    sec = self.al_sec.get(s)
                    cg = self.cogs.get((s, self.ly_month))
                    cogs_amt = cg["cogs_early"] if cg else ZERO
                else:
                    key = (s, lm if ly else m)
                    sec = self.sec.get(key)
                    cg = self.cogs.get(key)
                    cogs_amt = cg["cogs_v"] if cg else ZERO
                if sec:
                    t["revenue"] += sec.get("REVENUE", ZERO)
                    t["cogs_books"] += sec.get("COGS_BOOKS", ZERO)
                    t["opex"] += sec.get("STORE_OPEX", ZERO)
                t["cogs"] += cogs_amt
        t["gm"] = t["revenue"] - t["cogs"] + t["cogs_books"]
        t["contribution"] = t["gm"] + t["opex"]
        return t

    def group(self, sites, months, g, ly=False):
        t = ZERO
        for m in months:
            lm = add_months(m, -12)
            for s in sites:
                if ly and m == self.as_of_month and self.partial:
                    t += self.al_grp.get(s, {}).get(g, ZERO)
                else:
                    t += self.grp.get((s, lm if ly else m), {}).get(g, ZERO)
        return t


def reconcile_review(client, db, run_id: str, add) -> None:
    base = f"/api/v1/pnl/runs/{run_id}"
    m = mart_rows(db, run_id)
    run = m["run"]
    has_foundation = bool(m["eff"]) and run.get("ly_aligned_month") is not None
    add("PNL-R0", "the run carries the review foundation (effective area, aligned window)", 1 if has_foundation else 0, 1 if has_foundation else 0)
    if not has_foundation:
        return
    F = Figures(m)
    first_month = min(r["month"] for r in m["gl"])

    def ly_ok(months):
        """Last year is available for a window when every last-year month it needs is in the mart (the as-of month through the aligned window)."""
        return all(add_months(mm, -12) >= first_month for mm in months if not (mm == F.as_of_month and F.partial)) and (not (F.as_of_month in months and F.partial) or bool(m["aligned"]))

    stores = sorted(m["stores"])
    fy = date(F.as_of.year if F.as_of.month >= 4 else F.as_of.year - 1, 4, 1)
    ytd = months_between(fy, F.as_of_month)
    qs = date(F.as_of.year, ((F.as_of.month - 1) // 3) * 3 + 1, 1)
    qtd = months_between(qs, F.as_of_month)
    complete = months_between(fy, add_months(F.as_of_month, -1) if F.partial else F.as_of_month)

    # R1: MTD / QTD / YTD, this year and the day-aligned last year
    c = client.get(base + "/comparison", params={"mode": "stores"}).json()
    wins = {w["id"]: w for w in c["windows"]}
    for wid, months in (("mtd", [F.as_of_month]), ("qtd", qtd), ("ytd", ytd)):
        ty, ly = F.line(stores, months), F.line(stores, months, ly=True)
        w = wins[wid]
        add("PNL-R1", f"{wid} last year is present exactly when the mart holds it", int(ly_ok(months)), int(w["ly"] is not None))
        for key, mine in (("revenue", "revenue"), ("cogs", "cogs"), ("gross_margin", "gm"), ("opex", "opex"), ("contribution", "contribution")):
            add("PNL-R1", f"{wid} this year {key}", ty[mine], w["ty"][key])
            if w["ly"] is not None:
                add("PNL-R1", f"{wid} last year (day aligned) {key}", ly[mine], w["ly"][key])
    add("PNL-R1", "windows are flagged day aligned when the as-of month is partial", int(F.partial) * 3, sum(1 for w in c["windows"] if w["day_aligned"]))

    # R2: the pivot, every cell of the revenue and contribution rows, every group's YTD, last-year YTD
    p = client.get(base + "/pivot", params={"mode": "stores"}).json()
    rows = {r["id"]: r for r in p["rows"]}
    for mm in ytd:
        t = F.line(stores, [mm])
        add("PNL-R2", f"pivot revenue {mm:%Y-%m}", t["revenue"], rows["revenue"]["cells"][mm.strftime("%Y-%m")])
        add("PNL-R2", f"pivot contribution {mm:%Y-%m}", t["contribution"], rows["contribution"]["cells"][mm.strftime("%Y-%m")])
    t, tl = F.line(stores, ytd), F.line(stores, ytd, ly=True)
    add("PNL-R2", "last-year YTD is present exactly when the mart holds it", int(ly_ok(ytd)), int(p["ly_ytd_available"]))
    for rid, mine in (("revenue", "revenue"), ("gross_margin", "gm"), ("store_opex", "opex"), ("contribution", "contribution")):
        add("PNL-R2", f"pivot YTD {rid}", t[mine], rows[rid]["cells"]["ytd"])
        if p["ly_ytd_available"]:
            add("PNL-R2", f"pivot last-year YTD {rid}", tl[mine], rows[rid]["ly_ytd"])
    add("PNL-R2", "pivot YTD COGS", -t["cogs"], rows["cogs"]["cells"]["ytd"])
    groups = sorted(g for g in {r["group_label"] for r in m["gl"] if r["section"] == "STORE_OPEX"})
    for g in groups:
        add("PNL-R2", f"pivot YTD {g}", F.group(stores, ytd, g), rows["g:" + g]["cells"]["ytd"])
        if p["ly_ytd_available"]:
            add("PNL-R2", f"pivot last-year YTD {g}", F.group(stores, ytd, g, ly=True), rows["g:" + g]["ly_ytd"])
    for r in p["rows"]:
        if r["cells"]["ytd"] is not None and r["ly_ytd"] is not None:
            add("PNL-R2", f"variance = YTD - last-year YTD ({r['id']})", D(r["cells"]["ytd"]) - D(r["ly_ytd"]), r["variance"])
    for g in groups[:3]:
        led = client.get(base + "/pivot", params={"mode": "stores", "group": g}).json()["ledgers"]
        add("PNL-R2", f"ledgers of {g} add up to the group's YTD", F.group(stores, ytd, g), sum((D(x["cells"].get("ytd")) for x in led), ZERO))

    # R3: expense lines: cost, share of sales and PSF over the complete months
    e = client.get(base + "/expenses").json()
    rev = F.line(stores, complete)["revenue"]
    area_sites = [s for s in stores if all(m["eff"].get((s, mm)) is not None for mm in complete) and sum((m["eff"][(s, mm)] for mm in complete), ZERO) > 0]   # a store with no area is left out of both sides
    for ln in e["lines"]:
        g = ln["group"]
        add("PNL-R3", f"expense cost {g}", -F.group(stores, complete, g), ln["cost"])
        den = sum((m["eff"][(s, mm)] for s in area_sites for mm in complete), ZERO)
        num = -sum((F.group([s], complete, g) for s in area_sites), ZERO)
        if den:
            add("PNL-R3", f"expense PSF {g} (4 d.p.)", (num / den).quantize(Decimal("0.0001")), D(ln["psf"]).quantize(Decimal("0.0001")))
        add("PNL-R3", f"expense share of sales {g} (4 d.p.)", (-F.group(stores, complete, g) * 100 / rev).quantize(Decimal("0.0001")), D(ln["pct_of_sales"]).quantize(Decimal("0.0001")))

    # R4: the heat map: one row per store with figures, contribution % and sales PSF re-derived
    h = client.get(base + "/heatmap", params={"limit": 500}).json()
    api = {r["site_code"]: r for r in h["stores"]}
    mine_sites = [s for s in stores if any(F.line([s], [mm])[k] != 0 for mm in complete for k in ("revenue", "cogs", "opex"))]
    add("PNL-R4", "stores in the heat map", len(mine_sites), len(api))
    add("PNL-R4", "stores missing or extra", 0, len(set(mine_sites) ^ set(api)))
    bad_pct = bad_psf = 0
    for s in mine_sites:
        t = F.line([s], complete)
        if t["revenue"] and api[s]["contribution_pct"] is not None:
            bad_pct += int((t["contribution"] * 100 / t["revenue"]).quantize(Decimal("0.0001")) != D(api[s]["contribution_pct"]).quantize(Decimal("0.0001")))
        areas = [m["eff"].get((s, mm)) for mm in complete]
        if all(a is not None for a in areas) and sum(areas, ZERO) > 0:
            bad_psf += int((t["revenue"] / sum(areas, ZERO)).quantize(Decimal("0.0001")) != D(api[s]["sales_psf"]).quantize(Decimal("0.0001")))
        else:
            bad_psf += int(api[s]["sales_psf"] is not None)
    add("PNL-R4", "stores whose contribution % differs from the mart", 0, bad_pct)
    add("PNL-R4", "stores whose sales PSF differs from the mart (none is given when an area is missing)", 0, bad_psf)

    # R5: every listed exception quotes the mart's own figure
    xe = client.get(base + "/exceptions/expenses", params={"limit": 1000}).json()
    bad = 0
    for x in xe["exceptions"]:
        mm = date(int(x["month"][:4]), int(x["month"][5:7]), 1)
        bad += int(-F.group([x["site_code"]], [mm], x["group"]) != D(x["current"]))
    add("PNL-R5", f"expense exceptions ({len(xe['exceptions'])}) whose current figure differs from the mart", 0, bad)
    add("PNL-R5", "expense exception count = list length", xe["total"], len(xe["exceptions"]))
    xr = client.get(base + "/exceptions/revenue", params={"limit": 1000}).json()
    badr = 0
    for x in xr["exceptions"]:
        mm = date(int(x["month"][:4]), int(x["month"][5:7]), 1)
        badr += int(F.line([x["site_code"]], [mm])["revenue"] != D(x["revenue"]))
    add("PNL-R5", f"revenue exceptions ({len(xr['exceptions'])}) whose revenue differs from the mart", 0, badr)
    add("PNL-R5", "every exception names the rule that fired", len(xe["exceptions"]) + len(xr["exceptions"]), sum(1 for x in xe["exceptions"] + xr["exceptions"] if x["flags"] and x["why"]))

    # R6: data quality counts
    q = client.get(base + "/quality").json()
    no_area = [s for s in stores if not (m["sites"].get(s) or {}).get("area")]
    add("PNL-R6", "stores without an area", len(no_area), q["stores_without_area"]["count"])
    add("PNL-R6", "stores in the quality report", len(stores), q["stores"])
