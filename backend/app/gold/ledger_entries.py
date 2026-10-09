"""Ledger -> vouchers list for the P&L drill (read-only, FPA_SOURCE=gold only).

  GET /api/v1/entries/runs/{run}/ledger-entries?site=&glcode=&from_month=YYYY-MM&to_month=YYYY-MM&from_date=&to_date=&basis=all|posted&limit=&offset=
  GET /api/v1/entries/runs/{run}/finance/ledger-entries   same, plus one narration per voucher (Finance bearer token)

One row per voucher (entcode) that has at least one cost-tag line on the ledger (glcode) at the store (tag_site_code, the same key the P&L uses) in the
month range. Amounts are only the matching lines (debit, credit, net = credit - debit, the P&L sign), so the sum of the rows equals the ledger line shown
in the P&L drill. Every list carries the parent figure, the children sum and `reconciles`. Uses the indexed columns entdt / glcode / tag_site_code / entcode.
Nothing here writes; the session is one read-only transaction. This module does not touch the other gold modules.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Request

from ..creditors_api.router import ok
from ..entry_api.router import header, open_run
from . import db as gold

router = APIRouter(prefix="/api/v1/entries")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
ZERO = Decimal(0)


def _month_start(m: str) -> date:
    return date(int(m[:4]), int(m[5:7]), 1)


def _next_month(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def _list(request: Request, run_id: str, finance: bool, site, glcode, from_month, to_month, basis, limit, offset, from_date=None, to_date=None):
    if not gold.enabled():
        raise HTTPException(501, "The ledger voucher list is available only on the gold source")
    if site is None and glcode is None:
        raise HTTPException(422, "give a site and/or a glcode")
    for m in (from_month, to_month):
        if m is not None and not MONTH.match(m):
            raise HTTPException(422, "months must be YYYY-MM")
    for d in (from_date, to_date):
        if d is not None:
            try:
                if not DAY.match(d):
                    raise ValueError
                date.fromisoformat(d)
            except ValueError:
                raise HTTPException(422, "dates must be YYYY-MM-DD") from None
    if basis not in ("all", "posted"):
        raise HTTPException(422, "basis must be all or posted")
    where, args = [], []
    if glcode is not None:
        where.append("glcode = %s"); args.append(glcode)
    if site is not None:
        where.append("tag_site_code = %s"); args.append(site)
    if from_month:
        where.append("entdt >= %s"); args.append(_month_start(from_month))
    if to_month:
        where.append("entdt < %s"); args.append(_next_month(_month_start(to_month)))
    if from_date:  # a single store-day (till drill) or any day range; combines with the month range
        where.append("entdt >= %s"); args.append(date.fromisoformat(from_date))
    if to_date:
        where.append("entdt <= %s"); args.append(date.fromisoformat(to_date))
    if basis == "posted":
        where.append("release_status = 'P'")
    cond = " AND ".join(where)
    narr = ", min(narration) AS narration" if finance else ""
    with open_run(request, run_id, finance) as (conn, run):
        rows = conn.execute(
            f"""WITH g AS (SELECT entcode, min(entdt) AS entry_date, string_agg(DISTINCT enttype, '/' ORDER BY enttype) AS entry_type_short,
                       string_agg(DISTINCT entry_type, ' / ' ORDER BY entry_type) AS entry_type_long,
                       CASE WHEN bool_and(release_status = 'P') THEN 'Posted' WHEN bool_and(release_status <> 'P') THEN 'Unposted' ELSE 'Mixed' END AS release_status,
                       count(*)::integer AS lines, sum(coalesce(damount, 0)) AS debit, sum(coalesce(camount, 0)) AS credit{narr}
                    FROM gold_fpa.voucher_lines WHERE {cond} GROUP BY entcode)
                SELECT g.*, g.credit - g.debit AS net, count(*) OVER () AS total_entries, sum(g.lines) OVER () AS total_lines,
                       sum(g.debit) OVER () AS total_debit, sum(g.credit) OVER () AS total_credit
                FROM g ORDER BY g.entry_date DESC, g.entcode LIMIT %s OFFSET %s""", (*args, limit, offset)).fetchall()
        if rows:
            t = rows[0]
            total = {"entries": t["total_entries"], "lines": int(t["total_lines"]), "debit": t["total_debit"], "credit": t["total_credit"], "net": t["total_credit"] - t["total_debit"]}
        else:  # offset past the end: totals still come from the aggregate
            a = conn.execute(f"SELECT count(DISTINCT entcode) AS e, count(*) AS l, coalesce(sum(coalesce(damount,0)),0) AS d, coalesce(sum(coalesce(camount,0)),0) AS c FROM gold_fpa.voucher_lines WHERE {cond}", tuple(args)).fetchone()
            total = {"entries": a["e"], "lines": a["l"], "debit": a["d"], "credit": a["c"], "net": a["c"] - a["d"]}
        name = None
        if glcode is not None:
            n = conn.execute("SELECT glname FROM gold_fpa.voucher_lines WHERE glcode = %s LIMIT 1", (glcode,)).fetchone()
            name = n["glname"] if n else None
        shown = [{**{k: v for k, v in r.items() if not k.startswith("total_") and k != "entcode"}, "entry_ref": r["entcode"]} for r in rows]
        # parent = the full ledger/site/period aggregate; children = every row of the list, so a complete list reconciles by construction
        returned_net = sum((r["net"] for r in shown), ZERO)
        complete = offset + len(shown) >= total["entries"]
        return ok({**header(run), "scope": {"site": site, "glcode": glcode, "ledger_name": name, "from_month": from_month, "to_month": to_month, "from_date": from_date, "to_date": to_date, "basis": basis},
                   "parent": {"net": total["net"], "debit": total["debit"], "credit": total["credit"], "lines": total["lines"]},
                   "children_sum": {"net": returned_net}, "reconciles": (returned_net == total["net"]) if (complete and offset == 0) else None,
                   "total": total, "returned": len(shown), "limit": limit, "offset": offset, "named": finance, "entries": shown})


@router.get("/runs/{run_id}/ledger-entries")
def ledger_entries(request: Request, run_id: str, site: int | None = Query(None, ge=0), glcode: int | None = Query(None, ge=0), from_month: str | None = None, to_month: str | None = None,
                   basis: str = "all", limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), from_date: str | None = None, to_date: str | None = None):
    return _list(request, run_id, False, site, glcode, from_month, to_month, basis, limit, offset, from_date, to_date)


@router.get("/runs/{run_id}/finance/ledger-entries")
def finance_ledger_entries(request: Request, run_id: str, site: int | None = Query(None, ge=0), glcode: int | None = Query(None, ge=0), from_month: str | None = None, to_month: str | None = None,
                           basis: str = "all", limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), from_date: str | None = None, to_date: str | None = None):
    return _list(request, run_id, True, site, glcode, from_month, to_month, basis, limit, offset, from_date, to_date)


def _line_detail(request: Request, run_id: str, ref: str, finance: bool):
    """Per-line columns the entry layer does not carry: finance group, the store the cost tag belongs to, and (Finance only) the party name.
    line_no is the same row_number() over (entcode order by cost_tag_key) as entry.v_entry_line, so the rows line up one to one."""
    if not gold.enabled():
        raise HTTPException(501, "Line detail is available only on the gold source")
    party = ", vendor_name, vendor_class" if finance else ""
    with open_run(request, run_id, finance) as (conn, run):
        rows = conn.execute(
            f"""SELECT (row_number() OVER (ORDER BY cost_tag_key))::integer AS line_no, fin_group, fin_major_group, tag_site_code AS site_code, store_name, site_kind, profit_effect{party}
                FROM gold_fpa.voucher_lines WHERE entcode = %s ORDER BY cost_tag_key""", (ref,)).fetchall()
        if not rows:
            raise HTTPException(404, "unknown entry")
        return ok({**header(run), "entry_ref": ref, "named": finance, "lines": rows})


@router.get("/runs/{run_id}/entry/{entry_ref}/line-detail")
def line_detail(request: Request, run_id: str, entry_ref: str):
    return _line_detail(request, run_id, entry_ref, False)


@router.get("/runs/{run_id}/finance/entry/{entry_ref}/line-detail")
def finance_line_detail(request: Request, run_id: str, entry_ref: str):
    return _line_detail(request, run_id, entry_ref, True)
