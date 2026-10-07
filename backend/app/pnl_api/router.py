"""HTTP surface of the store P&L actuals API (read-only). Money is exact decimal text; the data state is decided here, never by the UI.

  /api/v1/pnl/health | current | runs
  /api/v1/pnl/runs/{run}                      status and control tallies
  /api/v1/pnl/runs/{run}/summary              company or filtered P&L for a period: totals, last year, lines by group, flags, reconciliation (company = stores + non-store)
  /api/v1/pnl/runs/{run}/trend                month by month, with last year and growth
  /api/v1/pnl/runs/{run}/stores               league table (paged, sortable, filterable): revenue, COGS, gross margin, opex, contribution, last year
  /api/v1/pnl/runs/{run}/stores/{site}        one store: monthly series and P&L lines
  /api/v1/pnl/runs/{run}/stores/{site}/groups/{group}/ledgers   the ledgers behind one group, by month (reconciles to the group)
  /api/v1/pnl/runs/{run}/hierarchy            filter options with store counts and revenue
  /api/v1/pnl/runs/{run}/reconciliation       books sales vs the COGS table, ledgers excluded for want of a finance group, sites without books sales
  /api/v1/pnl/runs/{run}/controls             control tallies

Common query parameters: from_month=YYYY-MM, to_month=YYYY-MM (default: this financial year to the as-of month), basis=all|posted, and the filters region, cluster, state, vintage, status.
Every list carries `parent`, `children_sum` and `reconciles`. Budget is always null (not available).
"""
from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Request

from ..creditors_api.router import ok
from . import repository as repo

router = APIRouter(prefix="/api/v1/pnl")
ZERO = Decimal(0)


def database(request: Request):
    db = request.app.state.db
    if db is None:
        raise HTTPException(503, "The P&L database is not configured on this server")
    return db


@contextmanager
def open_run(request: Request, run_id: str):
    with database(request).session("pnl") as conn:
        run = repo.serving_run(conn, run_id)
        if run is None:
            raise HTTPException(404, "that run does not exist or has not been verified")
        yield conn, run


def header(run: dict) -> dict:
    state = repo.data_state(run)
    return {"run_id": run["run_id"], "as_of_date": run["as_of_date"], "cogs_last_bill_date": run["cogs_last_bill_date"], "recon_state": run["recon_state"], "publication_state": run["publication_state"],
            "data_state": state, "data_state_label": repo.STATE_LABEL[state], "contract_version": run["contract_version"], "source_updated_at": run["extract_finished_at"],
            "budget": None, "budget_note": repo.BUDGET_NOTE}


class Scope:
    """Everything a P&L request is about: the run, the period, the basis and the site filters, resolved once."""

    def __init__(self, conn, run: dict, from_month: str | None, to_month: str | None, basis: str, region: str | None, cluster: str | None, state: str | None, vintage: str | None, status: str | None):
        if basis not in ("all", "posted"):
            raise HTTPException(422, "basis must be all or posted")
        lo, hi = repo.default_period(run)
        try:
            lo = repo.month_start(from_month) if from_month else lo
            hi = repo.month_start(to_month) if to_month else hi
        except (ValueError, TypeError):
            raise HTTPException(422, "months are written YYYY-MM") from None
        if lo > hi:
            raise HTTPException(422, "from_month is after to_month")
        self.run, self.conn, self.lo, self.hi, self.basis = run, conn, lo, hi, basis
        self.filters = {"region": region, "cluster": cluster, "state": state, "vintage": vintage, "status": status}
        self.sites = repo.sites(conn, run["run_id"])
        self.stores = repo.store_set(conn, run["run_id"])
        self.data = repo.site_months(conn, run["run_id"], basis)
        self.first_month = min((m for _, m in self.data), default=lo)
        self.filtered = any(self.filters.values())

    def in_scope(self, code: str) -> bool:
        return repo.matches(self.sites.get(code), self.filters)

    def store_in_scope(self, code: str) -> bool:
        return code in self.stores and self.in_scope(code)

    def echo(self) -> dict:
        a = self.run["as_of_date"]
        return {"from_month": self.lo.strftime("%Y-%m"), "to_month": self.hi.strftime("%Y-%m"), "basis": self.basis,
                "basis_label": "Posted entries only" if self.basis == "posted" else "All entries, including unposted (provisional)", "filters": {k: v for k, v in self.filters.items() if v},
                "partial_last_month": self.hi.year == a.year and self.hi.month == a.month and a.day < 28}


def scope(request: Request, conn, run, from_month, to_month, basis, region, cluster, state, vintage, status) -> Scope:
    return Scope(conn, run, from_month, to_month, basis, region, cluster, state, vintage, status)


def money_keys(t: dict) -> dict:
    return {k: t[k] for k in ("revenue", "cogs", "cogs_books", "gross_margin", "gross_margin_pct", "opex", "opex_pct", "contribution", "contribution_pct", "other_income", "finance_cost")}


def flags(sc: Scope, extra_cogs_only: list[dict] | None = None) -> dict:
    run = sc.run
    prov = repo.provisional_months(sc.data, sc.lo, sc.hi)
    out = {
        "provisional_months": [m.strftime("%Y-%m") for m in prov],
        "cogs_through": run["cogs_last_bill_date"], "books_through": run["as_of_date"],
        "cogs_lags_books": run["cogs_last_bill_date"] < run["as_of_date"],
        "partial_last_month": sc.echo()["partial_last_month"],
        "cogs_has_no_posting_status": "COGS comes from the COGS table, which has no posted / unposted split: it is the same in both bases.",
        "contribution_definition": "Gross margin + store operating expenses. Before other income, finance cost and any head-office allocation.",
    }
    if extra_cogs_only is not None:
        out["sites_with_cogs_sales_but_no_books_sales"] = len(extra_cogs_only)
    return out


@router.get("/health")
def health():
    return ok({"status": "ok"})


@router.get("/current")
def current(request: Request):
    with database(request).session("pnl") as conn:
        run = repo.serving_run(conn)
    if run is None:
        raise HTTPException(404, "no verified P&L run is available yet")
    return ok(header(run))


@router.get("/runs")
def runs(request: Request):
    with database(request).session("pnl") as conn:
        return ok({"runs": [header(r) for r in repo.list_runs(conn)]})


@router.get("/runs/{run_id}")
def status(request: Request, run_id: str):
    with open_run(request, run_id) as (conn, run):
        return ok({**header(run), "expected_gl_rows": run["expected_gl_rows"], "expected_cogs_rows": run["expected_cogs_rows"], "expected_sites": run["expected_sites"], "controls": repo.controls(conn, run_id)})


def common(from_month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"), to_month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"), basis: str = "all", region: str | None = None,
           cluster: str | None = None, state: str | None = None, vintage: str | None = None, status: str | None = None) -> dict:
    return dict(from_month=from_month, to_month=to_month, basis=basis, region=region, cluster=cluster, state=state, vintage=vintage, status=status)


from fastapi import Depends  # noqa: E402


@router.get("/runs/{run_id}/summary")
def summary(request: Request, run_id: str, q: dict = Depends(common)):
    with open_run(request, run_id) as (conn, run):
        sc = scope(request, conn, run, **q)
        in_scope_store = sc.store_in_scope
        # the company is every site; a filtered view is the stores that match the filters (non-store costs belong to the company, not to a region)
        company = repo.period_totals(sc.data, (lambda c: True) if not sc.filtered else sc.store_in_scope, sc.lo, sc.hi)
        stores = repo.period_totals(sc.data, in_scope_store, sc.lo, sc.hi)
        non_store = repo.period_totals(sc.data, lambda c: c not in sc.stores, sc.lo, sc.hi)
        ly_period = repo.last_year(sc.lo, sc.hi, sc.first_month)
        ly = repo.period_totals(sc.data, (lambda c: True) if not sc.filtered else sc.store_in_scope, *ly_period) if ly_period else None
        codes = None if not sc.filtered else {c for c in {s for s, _ in sc.data} if sc.store_in_scope(c)}
        lines = repo.pl_lines(conn, run_id, sc.basis, sc.lo, sc.hi, codes)
        unm = repo.unmapped_ledgers(conn, run_id, sc.basis, sc.lo, sc.hi, 0)
        cogs_only = repo.cogs_only_sites(conn, run_id)
        body = {**header(run), "scope": sc.echo(), "stores_in_scope": sum(1 for c in sc.stores if sc.store_in_scope(c)), "totals": money_keys(company), "last_year": None if ly is None else {**money_keys(ly), "period": {"from_month": ly_period[0].strftime("%Y-%m"), "to_month": ly_period[1].strftime("%Y-%m")}},
                "growth": None if ly is None else {"revenue_pct": repo.pct(company["revenue"] - ly["revenue"], ly["revenue"]), "gross_margin_pct": repo.pct(company["gross_margin"] - ly["gross_margin"], ly["gross_margin"]),
                                                  "contribution_pct": repo.pct(company["contribution"] - ly["contribution"], abs(ly["contribution"]))},
                "lines": lines, "below_contribution": {"other_income": company["other_income"], "finance_cost": company["finance_cost"], "after_below_the_line": company["contribution"] + company["other_income"] + company["finance_cost"]},
                "excluded_unmapped": {"ledgers": unm["count"], "net": unm["net"], "gross_abs": unm["gross_abs"], "note": "Ledgers the finance mapping does not know (mainly purchases and stock transfers, which reach the P&L through COGS). Never in a total; listed on the reconciliation view."},
                "flags": flags(sc, cogs_only)}
        if not sc.filtered:
            body["reconciliation"] = {"parent": {"revenue": company["revenue"], "contribution": company["contribution"]}, "children_sum": {"revenue": stores["revenue"] + non_store["revenue"], "contribution": stores["contribution"] + non_store["contribution"]},
                                      "stores": money_keys(stores), "non_store": money_keys(non_store),
                                      "reconciles": (company["revenue"], company["contribution"]) == (stores["revenue"] + non_store["revenue"], stores["contribution"] + non_store["contribution"])}
        return ok(body)


@router.get("/runs/{run_id}/trend")
def trend(request: Request, run_id: str, q: dict = Depends(common)):
    with open_run(request, run_id) as (conn, run):
        sc = scope(request, conn, run, **q)
        pick = (lambda c: True) if not sc.filtered else sc.store_in_scope
        months = repo.months_between(sc.lo, sc.hi)
        prov = set(repo.provisional_months(sc.data, sc.lo, sc.hi))
        series, running = [], repo.blank()
        for m in months:
            t = repo.period_totals(sc.data, pick, m, m)
            lym = repo.add_months(m, -12)
            ly = repo.period_totals(sc.data, pick, lym, lym) if lym >= sc.first_month else None
            row = {"month": m.strftime("%Y-%m"), **money_keys(t), "provisional": m in prov, "partial": m == sc.hi and sc.echo()["partial_last_month"],
                   "last_year": None if ly is None else {"month": lym.strftime("%Y-%m"), **money_keys(ly)},
                   "growth_revenue_pct": None if ly is None else repo.pct(t["revenue"] - ly["revenue"], ly["revenue"])}
            series.append(row)
            repo.add(running, repo.aggregate(sc.data, pick, m, m))
        total = repo.finish(running)
        parent = repo.period_totals(sc.data, pick, sc.lo, sc.hi)
        return ok({**header(run), "scope": sc.echo(), "months": series, "parent": {"revenue": parent["revenue"], "contribution": parent["contribution"]},
                   "children_sum": {"revenue": total["revenue"], "contribution": total["contribution"]}, "reconciles": (parent["revenue"], parent["contribution"]) == (total["revenue"], total["contribution"]),
                   "flags": flags(sc)})


SORTS = {"revenue": "revenue", "gross_margin": "gross_margin", "gross_margin_pct": "gross_margin_pct", "contribution": "contribution", "contribution_pct": "contribution_pct", "opex": "opex",
         "growth": "growth_pct", "name": "store_name", "cogs": "cogs"}


@router.get("/runs/{run_id}/stores")
def stores(request: Request, run_id: str, q: dict = Depends(common), sort: str = "contribution", order: str = "desc", limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
           min_revenue: Decimal | None = None):
    if sort not in SORTS:
        raise HTTPException(422, f"sort must be one of {sorted(SORTS)}")
    with open_run(request, run_id) as (conn, run):
        sc = scope(request, conn, run, **q)
        ly_period = repo.last_year(sc.lo, sc.hi, sc.first_month)
        rows = []
        per_site = {}
        for (code, mon), a in sc.data.items():
            if code in sc.stores and sc.store_in_scope(code) and sc.lo <= mon <= sc.hi:
                repo.add(per_site.setdefault(code, repo.blank()), a)
        per_ly = {}
        if ly_period:
            for (code, mon), a in sc.data.items():
                if code in per_site and ly_period[0] <= mon <= ly_period[1]:
                    repo.add(per_ly.setdefault(code, repo.blank()), a)
        for code, a in per_site.items():
            t = repo.finish(a)
            if min_revenue is not None and t["revenue"] < min_revenue:
                continue
            s = sc.sites.get(code) or {}
            l = repo.finish(per_ly[code]) if code in per_ly else None
            rows.append({"site_code": code, "store_name": s.get("store_name"), "region": s.get("region_type"), "cluster": s.get("cluster_type"), "state": s.get("state"), "vintage": s.get("store_current_status"),
                         "status": s.get("store_status"), **money_keys(t), "last_year_revenue": None if l is None else l["revenue"], "last_year_contribution": None if l is None else l["contribution"],
                         "growth_pct": None if l is None or not l["revenue"] else repo.pct(t["revenue"] - l["revenue"], l["revenue"]), "sales_in_table_not_in_books": bool(t["table_sales"] and not t["revenue"])})
        key = SORTS[sort]
        rows.sort(key=lambda r: ((r[key] is None), r[key] if r[key] is not None else 0) if key != "store_name" else (r[key] or ""), reverse=(order != "asc"))
        if order != "asc" and key != "store_name":                      # reverse put the missing values first: move them last
            rows.sort(key=lambda r: r[key] is None)
        for i, r in enumerate(rows, start=1):
            r["rank"] = i
        total = repo.finish(sum_up(rows, per_site))
        parent = repo.period_totals(sc.data, sc.store_in_scope, sc.lo, sc.hi)
        page = rows[offset: offset + limit]
        return ok({**header(run), "scope": sc.echo(), "stores_total": len(rows), "returned": len(page), "limit": limit, "offset": offset, "sort": sort, "order": order, "stores": page,
                   "parent": {"revenue": parent["revenue"], "contribution": parent["contribution"]}, "children_sum": {"revenue": total["revenue"], "contribution": total["contribution"]},
                   "reconciles": (parent["revenue"], parent["contribution"]) == (total["revenue"], total["contribution"]) or min_revenue is not None, "flags": flags(sc)})


def sum_up(rows: list[dict], per_site: dict) -> dict:
    t = repo.blank()
    for r in rows:
        repo.add(t, per_site[r["site_code"]])
    return t


@router.get("/runs/{run_id}/stores/{site}")
def store(request: Request, run_id: str, site: str, q: dict = Depends(common)):
    with open_run(request, run_id) as (conn, run):
        sc = scope(request, conn, run, **{**q, "region": None, "cluster": None, "state": None, "vintage": None, "status": None})
        known = {c for c, _ in sc.data}
        if site not in known:
            raise HTTPException(404, "unknown site")
        months = repo.months_between(sc.lo, sc.hi)
        series = []
        acc = repo.blank()
        for m in months:
            a = sc.data.get((site, m), repo.blank())
            repo.add(acc, a)
            series.append({"month": m.strftime("%Y-%m"), **money_keys(repo.finish(a))})
        t = repo.period_totals(sc.data, lambda c: c == site, sc.lo, sc.hi)
        ly_period = repo.last_year(sc.lo, sc.hi, sc.first_month)
        ly = repo.period_totals(sc.data, lambda c: c == site, *ly_period) if ly_period else None
        lines = repo.pl_lines(conn, run_id, sc.basis, sc.lo, sc.hi, {site})
        s = sc.sites.get(site) or {}
        line_total = sum((r["amount"] for r in lines if r["section"] != "REVENUE"), ZERO)
        return ok({**header(run), "scope": sc.echo(), "site": {"site_code": site, "store_name": s.get("store_name"), "region": s.get("region_type"), "cluster": s.get("cluster_type"), "state": s.get("state"),
                                                              "vintage": s.get("store_current_status"), "status": s.get("store_status"), "opening_date": s.get("opening_date"), "last_bill_date": s.get("last_bill_date"),
                                                              "is_store": site in sc.stores}, "totals": money_keys(t),
                   "last_year": None if ly is None else {**money_keys(ly), "period": {"from_month": ly_period[0].strftime("%Y-%m"), "to_month": ly_period[1].strftime("%Y-%m")}},
                   "months": series, "lines": lines, "parent": {"revenue": t["revenue"], "contribution": t["contribution"]},
                   "children_sum": {"revenue": sum((r["revenue"] for r in series), ZERO), "contribution": sum((r["contribution"] for r in series), ZERO)},
                   "reconciles": (t["revenue"], t["contribution"]) == (sum((r["revenue"] for r in series), ZERO), sum((r["contribution"] for r in series), ZERO)) and
                   (t["revenue"] == sum((r["amount"] for r in lines if r["section"] == "REVENUE"), ZERO)) and (t["cogs_books"] + t["opex"] + t["other_income"] + t["finance_cost"] == line_total),
                   "flags": flags(sc)})


@router.get("/runs/{run_id}/stores/{site}/groups/{group}/ledgers")
def group_ledgers(request: Request, run_id: str, site: str, group: str, q: dict = Depends(common)):
    with open_run(request, run_id) as (conn, run):
        sc = scope(request, conn, run, **{**q, "region": None, "cluster": None, "state": None, "vintage": None, "status": None})
        rows = repo.ledgers_of_group(conn, run_id, sc.basis, sc.lo, sc.hi, site, group)
        if not rows:
            raise HTTPException(404, "no ledger of that group at that site in the period")
        by: dict[str, dict] = {}
        for r in rows:
            d = by.setdefault(r["glcode"], {"glcode": r["glcode"], "ledger_name": r["ledger_name"], "amount": ZERO, "lines": 0, "months": []})
            d["amount"] += r["net"]
            d["lines"] += r["lines"]
            d["months"].append({"month": r["month"].strftime("%Y-%m"), "amount": r["net"]})
        ledgers = sorted(by.values(), key=lambda d: (d["amount"], d["ledger_name"]))
        group_total = next((x["amount"] for x in repo.pl_lines(conn, run_id, sc.basis, sc.lo, sc.hi, {site}) if x["group_label"] == group), ZERO)
        csum = sum((d["amount"] for d in ledgers), ZERO)
        return ok({**header(run), "scope": sc.echo(), "site_code": site, "group_label": group, "ledgers": ledgers, "parent": {"amount": group_total}, "children_sum": {"amount": csum}, "reconciles": group_total == csum})


@router.get("/runs/{run_id}/hierarchy")
def hierarchy(request: Request, run_id: str, q: dict = Depends(common)):
    with open_run(request, run_id) as (conn, run):
        sc = scope(request, conn, run, **{**q, "region": None, "cluster": None, "state": None, "vintage": None, "status": None})
        out: dict[str, dict] = {k: {} for k in repo.FILTER_FIELDS}
        for code in sc.stores:
            s = sc.sites.get(code)
            t = repo.period_totals(sc.data, lambda c, code=code: c == code, sc.lo, sc.hi)
            for k, col in repo.FILTER_FIELDS.items():
                v = (s or {}).get(col) if s else None
                v = v if v is not None else repo.NOT_IN_MASTER
                d = out[k].setdefault(v, {"value": v, "stores": 0, "revenue": ZERO, "contribution": ZERO})
                d["stores"] += 1
                d["revenue"] += t["revenue"]
                d["contribution"] += t["contribution"]
        return ok({**header(run), "scope": sc.echo(), "options": {k: sorted(v.values(), key=lambda d: (-d["revenue"], d["value"])) for k, v in out.items()}, "stores": len(sc.stores)})


@router.get("/runs/{run_id}/reconciliation")
def reconciliation(request: Request, run_id: str, q: dict = Depends(common)):
    with open_run(request, run_id) as (conn, run):
        sc = scope(request, conn, run, **{**q, "region": None, "cluster": None, "state": None, "vintage": None, "status": None})
        months = repo.tieout_by_month(conn, run_id, sc.lo, sc.hi)
        unm = repo.unmapped_ledgers(conn, run_id, sc.basis, sc.lo, sc.hi)
        cogs_only = repo.cogs_only_sites(conn, run_id)
        return ok({**header(run), "scope": sc.echo(), "tolerance_rupees": run["tolerance_rupees"],
                   "sales_tieout": {"basis": "books (ledger 'Sales - POS', ex-GST) against the COGS table's SL_V less TAXAMT", "months": months,
                                    "site_months": sum(m["site_months"] for m in months), "tied": sum(m["tied"] for m in months), "not_tied": sum(m["site_months"] - m["tied"] for m in months),
                                    "largest_gaps": repo.untied(conn, run_id, sc.lo, sc.hi)},
                   "excluded_unmapped": {"explanation": "Ledgers the finance mapping does not know. Excluded from every total and shown here; Finance needs to assign each to a group.", **unm},
                   "sites_without_books_sales": {"count": len(cogs_only), "sales_ex_gst": sum((r["sales_ex_gst"] for r in cogs_only), ZERO), "sites": cogs_only[:25]},
                   "flags": flags(sc, cogs_only)})


@router.get("/runs/{run_id}/controls")
def run_controls(request: Request, run_id: str):
    with open_run(request, run_id) as (conn, run):
        return ok({**header(run), **repo.controls(conn, run_id)})
