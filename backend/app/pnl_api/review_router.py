"""The P&L review endpoints (read-only): pivot, MTD/QTD/YTD, expense lines with PSF, store heat map, peers, exceptions, data quality. Definitions and thresholds: review.py.

  /api/v1/pnl/runs/{run}/pivot?mode=stores|company[&group=<finance group>]   Excel-style: months, quarters, YTD, last-year YTD (day aligned), variance; ledgers of a group on request
  /api/v1/pnl/runs/{run}/comparison?mode=                                      MTD / QTD / YTD, this year against last year, day aligned
  /api/v1/pnl/runs/{run}/expenses                                              every expense line: ₹, % of sales, last year, bps, PSF, trend
  /api/v1/pnl/runs/{run}/heatmap?sort=&limit=&offset=&min_revenue=            every store with growth, margins, opex %, PSF and last year; sort modes for review
  /api/v1/pnl/runs/{run}/stores/{site}/peers                                   the store against its peers (region + vintage, state, region, cluster, vintage, size band, network)
  /api/v1/pnl/runs/{run}/exceptions/expenses | revenue                         flagged stores, with the rule that fired and why
  /api/v1/pnl/runs/{run}/quality                                               what is missing or doubtful in the inputs
Same query parameters as the rest of the P&L API (from_month, to_month, basis, region, cluster, state, vintage, status). Budget is not available and is never shown.
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..creditors_api.router import ok
from . import repository as repo
from . import review as rvw
from . import review_engine as eng
from . import review_windows as win
from .router import common, header, open_run, scope

router = APIRouter(prefix="/api/v1/pnl")


def review(request: Request, conn, run, q: dict):
    sc = scope(request, conn, run, **q)
    return rvw.Review(sc)


def picker(rv: rvw.Review, mode: str):
    """stores: the stores matching the filters (the store P&L). company: every site when nothing is filtered (the company P&L, head office and depots included)."""
    sc = rv.sc
    if mode not in ("stores", "company"):
        raise HTTPException(422, "mode must be stores or company")
    if mode == "company" and not sc.filtered:
        return (lambda c: True), True
    return sc.store_in_scope, False


@router.get("/runs/{run_id}/pivot")
def pivot(request: Request, run_id: str, q: dict = Depends(common), mode: str = "stores", group: str | None = None):
    with open_run(request, run_id) as (conn, run):
        rv = review(request, conn, run, q)
        pick, company = picker(rv, mode)
        if group:
            return ok({**header(run), "scope": rv.sc.echo(), "mode": mode, **win.pivot_ledgers(rv, pick, group)})
        body = win.pivot(rv, pick, company)
        return ok({**header(run), "scope": rv.sc.echo(), "mode": "company" if company else "stores", "stores": sum(1 for c in rv.sc.stores if pick(c)), **body,
                   "unmapped_note": "Ledgers without a finance group are Unmapped / Finance classification required: they are in no row or total."})


@router.get("/runs/{run_id}/comparison")
def comparison(request: Request, run_id: str, q: dict = Depends(common), mode: str = "stores"):
    with open_run(request, run_id) as (conn, run):
        rv = review(request, conn, run, q)
        pick, company = picker(rv, mode)
        return ok({**header(run), "scope": rv.sc.echo(), "mode": "company" if company else "stores", "as_of": run["as_of_date"], "partial_month": bool(rv.partial),
                   "aligned_days": run.get("aligned_days"), "windows": win.compare_windows(rv, pick),
                   "note": "Day aligned: the current month is compared with the same days of last year, never with a whole month. Percent measures compare in basis points."})


@router.get("/runs/{run_id}/expenses")
def expenses(request: Request, run_id: str, q: dict = Depends(common)):
    with open_run(request, run_id) as (conn, run):
        rv = review(request, conn, run, q)
        return ok({**header(run), "scope": rv.sc.echo(), **eng.expense_lines(rv, rv.sc.store_in_scope)})


@router.get("/runs/{run_id}/heatmap")
def heatmap(request: Request, run_id: str, q: dict = Depends(common), sort: str = "worst_contribution_pct", limit: int = Query(500, ge=1, le=500), offset: int = Query(0, ge=0), min_revenue_cr: Decimal | None = None):
    if sort not in eng.HEAT_SORTS:
        raise HTTPException(422, f"sort must be one of {sorted(eng.HEAT_SORTS)}")
    with open_run(request, run_id) as (conn, run):
        rv = review(request, conn, run, q)
        floor = None if min_revenue_cr is None else min_revenue_cr * Decimal(10_000_000)
        return ok({**header(run), "scope": rv.sc.echo(), "sorts": sorted(eng.HEAT_SORTS), **eng.heatmap(rv, rv.sc.store_in_scope, sort, limit, offset, floor)})


@router.get("/runs/{run_id}/stores/{site}/peers")
def peers(request: Request, run_id: str, site: str, q: dict = Depends(common)):
    with open_run(request, run_id) as (conn, run):
        rv = review(request, conn, run, {**q, "region": None, "cluster": None, "state": None, "vintage": None, "status": None})
        out = eng.peers_of(rv, lambda c: True, site)
        if not out:
            raise HTTPException(404, "that site has no comparable figures in this period")
        return ok({**header(run), "scope": rv.sc.echo(), **out, "rules": {"peers": rvw.RULES["peers"]}})


@router.get("/runs/{run_id}/exceptions/expenses")
def expense_exceptions(request: Request, run_id: str, q: dict = Depends(common), limit: int = Query(200, ge=1, le=1000)):
    with open_run(request, run_id) as (conn, run):
        rv = review(request, conn, run, q)
        return ok({**header(run), "scope": rv.sc.echo(), **eng.expense_exceptions(rv, rv.sc.store_in_scope, limit)})


@router.get("/runs/{run_id}/exceptions/revenue")
def revenue_exceptions(request: Request, run_id: str, q: dict = Depends(common), limit: int = Query(200, ge=1, le=1000)):
    with open_run(request, run_id) as (conn, run):
        rv = review(request, conn, run, q)
        return ok({**header(run), "scope": rv.sc.echo(), **eng.revenue_exceptions(rv, rv.sc.store_in_scope, limit)})


@router.get("/runs/{run_id}/quality")
def data_quality(request: Request, run_id: str, q: dict = Depends(common)):
    with open_run(request, run_id) as (conn, run):
        rv = review(request, conn, run, {**q, "region": None, "cluster": None, "state": None, "vintage": None, "status": None})
        return ok({**header(run), "scope": rv.sc.echo(), **eng.quality(rv, conn)})
