"""
P&L actuals: mart = API reconciliation gate.

    cd backend && python -m app.pnl_api.reconcile run_20261007_003            # compare only
    cd backend && python -m app.pnl_api.reconcile run_20261007_003 --record   # also record the results as API-layer controls and ask the database to mark the run api_verified

Everything the P&L API serves for a run is read back through the API and compared, exactly and with zero tolerance, against the mart read with differently shaped SQL (grouped in
PostgreSQL, where the API aggregates in Python): the company P&L on both bases, every month of the trend, every store of the league table (and every filter option's stores), a
sample of stores down to the ledgers behind each group, the hierarchy, the reconciliation view, and the statements the API makes about itself (budget is null, the data state, every
`reconciles` flag true). With --record the results are written through pnl.record_control as the verifier and pnl.api_verify_run moves the run to api_verified (still unpublished).
A single difference blocks it.
"""
from __future__ import annotations

import random
import sys
from datetime import date
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal(0)


@dataclass
class Check:
    control: str
    dimension: str
    mart: Decimal
    api: Decimal

    @property
    def ok(self) -> bool:
        return self.mart == self.api


def D(x) -> Decimal:
    return Decimal(str(x)) if x is not None else ZERO


def mart_figures(db, run_id: str, basis: str, lo: str, hi: str) -> dict:
    """The mart, grouped by PostgreSQL: per site, per section, per month."""
    cond = "AND release_status = 'Posted'" if basis == "posted" else ""
    lo_d = date(int(lo[:4]), int(lo[5:7]), 1) if lo >= "0001" else date(1, 1, 1)
    hi_d = date(int(hi[:4]), int(hi[5:7]), 1) if hi <= "9998" else date(9999, 12, 1)
    with db.session("pnl_verifier") as c:
        g = c.execute(f"SELECT site_code, month, section, sum(credit - debit) AS net FROM pnl.v_gl_site_month WHERE run_id = %s {cond} GROUP BY 1, 2, 3", (run_id,)).fetchall()
        k = c.execute("SELECT site_code, month, sum(cogs_v) AS cogs FROM pnl.v_cogs_site_month WHERE run_id = %s GROUP BY 1, 2", (run_id,)).fetchall()
        sites = {r["site_code"]: r for r in c.execute("SELECT * FROM pnl.v_site WHERE run_id = %s", (run_id,)).fetchall()}
        stores = {r["site_code"] for r in c.execute("SELECT DISTINCT site_code FROM pnl.v_gl_site_month WHERE run_id = %s AND ledger_name = 'Sales - POS'", (run_id,)).fetchall()}
        run = c.execute("SELECT publication_state, as_of_date FROM pnl.v_serving_run WHERE run_id = %s", (run_id,)).fetchone()
        tie = c.execute("SELECT count(*) AS n, count(*) FILTER (WHERE tied) AS tied, coalesce(sum(difference), 0) AS diff FROM pnl.v_sales_tieout WHERE run_id = %s AND month BETWEEN %s AND %s", (run_id, lo_d, hi_d)).fetchone()
        unm = c.execute(f"SELECT count(DISTINCT glcode) AS n, coalesce(sum(credit - debit), 0) AS net FROM pnl.v_gl_site_month WHERE run_id = %s AND section = 'UNMAPPED' AND month BETWEEN %s AND %s {cond}", (run_id, lo_d, hi_d)).fetchone()
    return {"gl": g, "cogs": k, "sites": sites, "stores": stores, "run": run, "tie": tie, "unmapped": unm}


def figures(m: dict, lo, hi, site_pred=lambda s: True) -> dict:
    t = defaultdict(lambda: ZERO)
    for r in m["gl"]:
        if lo <= str(r["month"])[:7] <= hi and site_pred(r["site_code"]):
            t[r["section"]] += D(r["net"])
    for r in m["cogs"]:
        if lo <= str(r["month"])[:7] <= hi and site_pred(r["site_code"]):
            t["COGS"] += D(r["cogs"])
    rev, cg, cb, ox = t["REVENUE"], t["COGS"], t["COGS_BOOKS"], t["STORE_OPEX"]
    return {"revenue": rev, "cogs": cg, "cogs_books": cb, "opex": ox, "other_income": t["OTHER_INCOME"], "finance_cost": t["FINANCE_COST"], "gross_margin": rev - cg + cb, "contribution": rev - cg + cb + ox}


def reconcile(client, db, run_id: str) -> list[Check]:
    base = f"/api/v1/pnl/runs/{run_id}"
    out: list[Check] = []
    add = lambda control, dim, m, a: out.append(Check(control, dim, D(m), D(a)))  # noqa: E731
    cur = client.get("/api/v1/pnl/current").json()
    as_of = str(cur["as_of_date"]) if cur["run_id"] == run_id else None

    api_rev: dict[str, Decimal] = {}
    for basis in ("all", "posted"):
        s = client.get(base + "/summary", params={"basis": basis}).json()
        lo, hi = s["scope"]["from_month"], s["scope"]["to_month"]
        m = mart_figures(db, run_id, basis, lo, hi)
        f = figures(m, lo, hi)
        for key in ("revenue", "cogs", "cogs_books", "opex", "other_income", "finance_cost", "gross_margin", "contribution"):
            add("PNL-C1", f"company {key} ({basis}, {lo} to {hi})", f[key], s["totals"][key])
        api_rev[basis] = D(s["totals"]["revenue"])
        add("PNL-C1", f"every reconciles flag in the summary is true ({basis})", 1, int(s.get("reconciliation", {}).get("reconciles") is True))
        add("PNL-C1", f"excluded unmapped ledgers ({basis})", m["unmapped"]["n"], s["excluded_unmapped"]["ledgers"])
        add("PNL-C1", f"excluded unmapped net ({basis})", m["unmapped"]["net"], s["excluded_unmapped"]["net"])
        line_sum = sum((D(x["amount"]) for x in s["lines"] if x["section"] == "REVENUE"), ZERO)
        add("PNL-C1", f"lines add up to revenue ({basis})", f["revenue"], line_sum)
        add("PNL-C1", f"lines add up to opex ({basis})", f["opex"], sum((D(x["amount"]) for x in s["lines"] if x["section"] == "STORE_OPEX"), ZERO))
        # trend
        tr = client.get(base + "/trend", params={"basis": basis}).json()
        y0, m0 = int(lo[:4]), int(lo[5:])
        y1, m1 = int(hi[:4]), int(hi[5:])
        add("PNL-C2", f"trend months listed ({basis})", (y1 - y0) * 12 + (m1 - m0) + 1, len(tr["months"]))
        bad = 0
        for row in tr["months"]:
            fm = figures(m, row["month"], row["month"])
            bad += int((D(row["revenue"]), D(row["cogs"]), D(row["opex"]), D(row["contribution"])) != (fm["revenue"], fm["cogs"], fm["opex"], fm["contribution"]))
        add("PNL-C2", f"months whose revenue / cogs / opex / contribution differ ({basis})", 0, bad)
        add("PNL-C2", f"trend reconciles to its period total ({basis})", 1, int(tr["reconciles"] is True))
        # stores
        rows, off = [], 0
        while True:
            page = client.get(base + "/stores", params={"basis": basis, "limit": 500, "offset": off}).json()
            rows += page["stores"]
            off += 500
            if page["returned"] < 500:
                break
        per = {c: figures(m, lo, hi, lambda s, c=c: s == c) for c in m["stores"]}
        per = {c: v for c, v in per.items() if any(v.values())}
        api = {r["site_code"]: r for r in rows}
        add("PNL-C3", f"stores listed ({basis})", len(per), len(rows))
        add("PNL-C3", f"stores missing or extra ({basis})", 0, len(set(per) ^ set(api)))
        add("PNL-C3", f"stores whose revenue / cogs / opex / contribution differ ({basis})", 0,
            sum(1 for c in per if c in api and (D(api[c]["revenue"]), D(api[c]["cogs"]), D(api[c]["opex"]), D(api[c]["contribution"])) != (per[c]["revenue"], per[c]["cogs"], per[c]["opex"], per[c]["contribution"])))
        add("PNL-C3", f"stores + non-store = company ({basis})", 1, int(page["reconciles"] is True))
        add("PNL-C3", f"store revenue rank is 1..n with no gaps ({basis})", len(rows), sum(1 for i, r in enumerate(rows, start=1) if r["rank"] == i))
        if basis == "all":
            order = [D(r["contribution"]) for r in rows]
            add("PNL-C3", "default order is contribution, highest first", 1, int(order == sorted(order, reverse=True)))
            # filters: every option's stores and revenue, from the mart joined to the site master
            h = client.get(base + "/hierarchy").json()["options"]
            for key, col in (("region", "region_type"), ("cluster", "cluster_type"), ("state", "state"), ("vintage", "store_current_status"), ("status", "store_status")):
                for opt in h[key]:
                    members = {c for c in m["stores"] if ((m["sites"].get(c) or {}).get(col) if m["sites"].get(c) else None) in ((opt["value"],) if opt["value"] != "(not in site master)" else (None,))}
                    rev = sum((per[c]["revenue"] for c in members if c in per), ZERO)
                    add("PNL-C4", f"{key}={opt['value']}: stores", len(members), opt["stores"])
                    add("PNL-C4", f"{key}={opt['value']}: revenue", rev, opt["revenue"])
            sel = h["region"][0]["value"] if h["region"] else None
            if sel and sel != "(not in site master)":
                fl = client.get(base + "/stores", params={"region": sel, "limit": 500}).json()
                members = {c for c in m["stores"] if (m["sites"].get(c) or {}).get("region_type") == sel}
                add("PNL-C4", f"region {sel}: league lists exactly its stores with revenue", len([c for c in members if c in per]), fl["stores_total"])
                add("PNL-C4", f"region {sel}: league reconciles to the filtered parent", 1, int(fl["reconciles"] is True))
            # store detail and ledgers, sampled
            rnd = random.Random(11)
            ranked = sorted(per, key=lambda c: per[c]["revenue"], reverse=True)
            sample = ranked[:6] + ranked[-3:] + rnd.sample(ranked, min(6, len(ranked)))
            bad = bad_lines = bad_ledgers = bad_flag = 0
            checked_groups = 0
            for code in dict.fromkeys(sample):
                d = client.get(base + f"/stores/{code}").json()
                f1 = per[code]
                bad += int((D(d["totals"]["revenue"]), D(d["totals"]["cogs"]), D(d["totals"]["opex"]), D(d["totals"]["contribution"])) != (f1["revenue"], f1["cogs"], f1["opex"], f1["contribution"]))
                bad_flag += int(d["reconciles"] is not True)
                for ln in [x for x in d["lines"] if x["section"] == "STORE_OPEX"][:3]:
                    r = client.get(base + f"/stores/{code}/groups/{ln['group_label']}/ledgers").json()
                    checked_groups += 1
                    bad_ledgers += int(r["reconciles"] is not True or D(r["parent"]["amount"]) != D(ln["amount"]))
            add("PNL-C5", f"sampled stores ({len(set(sample))}): totals that differ from the mart", 0, bad)
            add("PNL-C5", "sampled stores that do not reconcile (months, lines)", 0, bad_flag)
            add("PNL-C5", f"sampled groups ({checked_groups}): ledgers that do not add up to the group", 0, bad_ledgers)
            # reconciliation view
            rv = client.get(base + "/reconciliation").json()
            add("PNL-C6", "tie-out site-months", m["tie"]["n"], rv["sales_tieout"]["site_months"])
            add("PNL-C6", "tie-out tied", m["tie"]["tied"], rv["sales_tieout"]["tied"])
            add("PNL-C6", "tie-out difference (sum of months)", m["tie"]["diff"], sum((D(x["difference"]) for x in rv["sales_tieout"]["months"]), ZERO))
            add("PNL-C6", "excluded ledgers listed equal the excluded count", rv["excluded_unmapped"]["count"], len(rv["excluded_unmapped"]["ledgers"]) if rv["excluded_unmapped"]["count"] <= 60 else 60)
    with db.session("pnl_verifier") as c:
        unposted_rev = c.execute("SELECT coalesce(sum(credit - debit), 0) AS v FROM pnl.v_gl_site_month WHERE run_id = %s AND section = 'REVENUE' AND release_status = 'Unposted'", (run_id,)).fetchone()["v"]
    add("PNL-C7", "revenue (all entries) less revenue (posted only) = the unposted revenue in the mart", unposted_rev, api_rev["all"] - api_rev["posted"])
    s = client.get(base + "/summary").json()
    expect = {"unpublished": "verified_candidate", "live": "live"}.get(cur["publication_state"] if cur["run_id"] == run_id else s["publication_state"], s["publication_state"])
    add("PNL-STATE", "data_state stated by the API matches the run's publication state", 1, int(s["data_state"] == expect))
    add("PNL-STATE", "budget is null and says so", 1, int(s["budget"] is None and "not available" in s["budget_note"]))
    add("PNL-STATE", "contribution is defined as before other income, finance cost and allocation", 1, int("Before other income" in s["flags"]["contribution_definition"]))
    add("PNL-STATE", "the COGS lag against the books is stated", 1, int("cogs_lags_books" in s["flags"] and "cogs_through" in s["flags"]))
    from .reconcile_review import reconcile_review

    reconcile_review(client, db, run_id, add)
    return out


def record(db, run_id: str, checks: list[Check]) -> dict:
    with db.session("pnl_verifier", readonly=False) as c:
        seen: dict[tuple, int] = {}
        for ch in checks:
            dim = ch.dimension[:190]
            key = (ch.control, dim)
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 1:
                dim = f"{dim} #{seen[key]}"
            c.execute("SELECT pnl.record_control(%s,%s,%s,'mart',%s,'api',%s)", (run_id, ch.control, dim, ch.mart, ch.api))
        return c.execute("SELECT pnl.api_verify_run(%s) AS r", (run_id,)).fetchone()["r"]


def main(argv: list[str]) -> int:
    from fastapi.testclient import TestClient

    from ..creditors_api.config import ApiSettings
    from ..creditors_api.db import Db
    from ..creditors_api.main import create_app

    if len(argv) < 2:
        print(__doc__)
        return 2
    run_id = argv[1]
    settings = ApiSettings.load()
    if not settings.conninfo:
        print("No API database login: run tools/creditors_mart/install_api.py first.")
        return 2
    db = Db(settings.conninfo)
    checks = reconcile(TestClient(create_app(settings, db)), db, run_id)
    bad = [c for c in checks if not c.ok]
    by: dict = defaultdict(lambda: [0, 0])
    for c in checks:
        by[c.control][0] += 1
        by[c.control][1] += c.ok
    print(f"{run_id}: {len(checks)} checks, {len(checks) - len(bad)} identical, {len(bad)} different")
    for k, (n, good) in sorted(by.items()):
        print(f"  {k:10s} {good}/{n}")
    for c in bad[:20]:
        print(f"  DIFFERENT {c.control} {c.dimension}: mart {c.mart} vs api {c.api}")
    if "--record" in argv:
        if bad:
            print("NOT recorded: a single difference blocks the API-layer verification.")
            return 1
        print("Recorded; database answer:", record(db, run_id, checks))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
