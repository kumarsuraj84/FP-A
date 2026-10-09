"""HTTP surface of the entry-level drill API (read-only). Money is exact decimal text; the data state is decided here.

  /api/v1/entries/health | current | runs/{run}
  /api/v1/entries/runs/{run}/entry/{entry_ref}                 masked entry: header, ALL lines, linked bills, attachment status
  /api/v1/entries/runs/{run}/finance/entry/{entry_ref}         + entry number, preparer / releaser, narration, references, cheque fields (bearer token)
  /api/v1/entries/runs/{run}/bank/ledgers?cash_run=            bank ledger -> posted / unposted / opening, reconciled to the cash review card
  /api/v1/entries/runs/{run}/bank/ledgers/{code}/entries?status=posted|unposted|opening&cash_run=
  /api/v1/entries/runs/{run}/till/stores?cash_run=             stores, reconciled to Store Till Cash
  /api/v1/entries/runs/{run}/till/stores/{site}/days?cash_run=
  /api/v1/entries/runs/{run}/creditors/items/{item_ref}/link?creditors_run=
  /api/v1/entries/runs/{run}/creditors/links?creditors_run=    link counts by status and coverage

Every list carries `parent`, `children_sum` and `reconciles`. A drill that names a domain run other than the one the entries were built against is refused (409).
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date

from fastapi import APIRouter, HTTPException, Query, Request

from ..cash_api import repository as cash_repo
from ..creditors_api.router import finance_gate, ok
from . import repository as repo

router = APIRouter(prefix="/api/v1/entries")
STATE_LABEL = {"live": "Live", "verified_candidate": "Verified candidate (not published)", "superseded": "Superseded", "withdrawn": "Withdrawn"}


def database(request: Request):
    db = request.app.state.db
    if db is None:
        raise HTTPException(503, "The entry database is not configured on this server")
    return db


@contextmanager
def open_run(request: Request, run_id: str, finance: bool = False, cash_run: str | None = None, creditors_run: str | None = None):
    db = database(request)
    if finance:
        finance_gate(request)
    with db.session("entry_finance" if finance else "entry") as conn:
        run = repo.serving_run(conn, run_id)
        if run is None:
            raise HTTPException(404, "that entry run does not exist or has not been verified")
        try:
            repo.check_lineage(run, cash_run=cash_run, creditors_run=creditors_run)
        except repo.Lineage as e:
            raise HTTPException(409, str(e)) from None
        yield conn, run


def header(run: dict) -> dict:
    state = repo.data_state(run)
    return {"entry_run_id": run["entry_run_id"], "register_report_date": run["register_report_date"], "till_balance_date": run["till_balance_date"], "cash_run_id": run["cash_run_id"],
            "creditors_run_id": run["creditors_run_id"], "coverage_from": run["coverage_from"], "recon_state": run["recon_state"], "publication_state": run["publication_state"], "data_state": state,
            "data_state_label": STATE_LABEL[state], "source_updated_at": run["extract_finished_at"]}


def cash_parent(request: Request, cash_run: str):
    with database(request).session("cash") as c:
        run = cash_repo.serving_run(c, cash_run)
        if run is None:
            raise HTTPException(404, "that cash run does not exist or has not been verified")
        return run, cash_repo.bank_rows(c, cash_run, "site_register"), cash_repo.till(c, cash_run)


@router.get("/health")
def health():
    return ok({"status": "ok"})


@router.get("/current")
def current(request: Request):
    with database(request).session("entry") as conn:
        run = repo.serving_run(conn)
    if run is None:
        raise HTTPException(404, "no verified entry run is available yet")
    return ok(header(run))


@router.get("/runs/{run_id}")
def status(request: Request, run_id: str):
    with open_run(request, run_id) as (conn, run):
        return ok({**header(run), "controls": repo.controls(conn, run_id), "bridge": repo.link_summary(conn, run_id)})


def _entry(request: Request, run_id: str, ref: str, finance: bool, entity: str = "RETAIL"):
    if entity not in ("RETAIL", "VENTURES"):
        raise HTTPException(422, "entity must be RETAIL or VENTURES")
    with open_run(request, run_id, finance) as (conn, run):
        e = repo.entry(conn, run_id, ref, finance, entity)
        if e is None:
            raise HTTPException(404, "unknown entry")
        return ok({**header(run), "entry": e})


@router.get("/runs/{run_id}/entry/{entry_ref}")
def masked_entry(request: Request, run_id: str, entry_ref: str, entity: str = "RETAIL"):
    return _entry(request, run_id, entry_ref, False, entity)


@router.get("/runs/{run_id}/finance/entry/{entry_ref}")
def finance_entry(request: Request, run_id: str, entry_ref: str, entity: str = "RETAIL"):
    return _entry(request, run_id, entry_ref, True, entity)


# ───────────── bank ─────────────


@router.get("/runs/{run_id}/bank/ledgers")
def bank_ledgers(request: Request, run_id: str, cash_run: str):
    with open_run(request, run_id, cash_run=cash_run) as (conn, run):
        rows = repo.bank_ledgers(conn, run)
    _, parents, _ = cash_parent(request, cash_run)
    par = {p["ledger_code"]: p for p in parents if p["has_movement"]}
    out, ok_all = [], True
    for r in rows:
        p = par.get(r["ledger_code"])
        agree = bool(p) and (r["posted_dr"], r["posted_cr"], r["unposted_dr"], r["unposted_cr"], r["opening_dr"] - r["opening_cr"]) == (p["posted_dr"], p["posted_cr"], p["unposted_dr"], p["unposted_cr"], p["opening_balance"])
        ok_all &= agree
        out.append({**r, "parent": None if not p else {k: p[k] for k in ("posted_dr", "posted_cr", "unposted_dr", "unposted_cr", "opening_balance", "posted_closing", "including_unposted")}, "reconciles": agree})
    ok_all &= set(par) == {r["ledger_code"] for r in rows}
    return ok({**header(run), "status": repo.BANK_STATUS, "ledgers": out, "reconciles": ok_all})


@router.get("/runs/{run_id}/bank/ledgers/{ledger_code}/entries")
def bank_entries(request: Request, run_id: str, ledger_code: str, cash_run: str, status: str = "posted", limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    if status not in repo.FILTERS:
        raise HTTPException(422, "status must be posted, unposted or opening")
    with open_run(request, run_id, cash_run=cash_run) as (conn, run):
        res = repo.bank_entries(conn, run, ledger_code, status, limit, offset)
    _, parents, _ = cash_parent(request, cash_run)
    p = next((x for x in parents if x["ledger_code"] == ledger_code and x["has_movement"]), None)
    if p is None:
        raise HTTPException(404, "unknown bank ledger")
    parent = {"posted": (p["posted_dr"], p["posted_cr"]), "unposted": (p["unposted_dr"], p["unposted_cr"]), "opening": (None, None)}[status]
    if status == "opening":
        parent = (p["opening_balance"] if p["opening_balance"] > 0 else 0, -p["opening_balance"] if p["opening_balance"] < 0 else 0)
    t = res["total"]
    agree = (t["debit"], t["credit"]) == (parent[0], parent[1]) if status != "opening" else (t["debit"] - t["credit"]) == p["opening_balance"]
    return ok({**header(run), "ledger_code": ledger_code, "ledger_name": p["ledger_name"], "status": status, "bank_status": repo.BANK_STATUS, "parent": {"debit": parent[0], "credit": parent[1]},
               "children_sum": {"debit": t["debit"], "credit": t["credit"]}, "entry_count": t["entries"], "reconciles": agree, "returned": len(res["entries"]), "limit": limit, "offset": offset, "entries": res["entries"]})


# ───────────── till ─────────────


@router.get("/runs/{run_id}/till/stores")
def till_stores(request: Request, run_id: str, cash_run: str):
    with open_run(request, run_id, cash_run=cash_run) as (conn, run):
        rows = repo.till_stores(conn, run)
    _, _, till = cash_parent(request, cash_run)
    total = sum((r["balance"] for r in rows), repo.ZERO)
    per = {r["site_code"]: r["balance"] for r in rows}
    with database(request).session("cash") as c:
        card = {x["site_code"]: x["cumulative_balance"] for x in c.execute("SELECT site_code, cumulative_balance FROM cash.v_store_till WHERE run_id = %s", (cash_run,)).fetchall()}
    agree = total == till["store_till_cash"] and per == card
    return ok({**header(run), "label": "Store Till Cash", "note": "excludes bank balances", "balance_date": run["till_balance_date"], "parent": {"store_till_cash": till["store_till_cash"], "stores": till["stores"]},
               "children_sum": {"store_till_cash": total, "stores": len(rows)}, "reconciles": agree, "stores": rows})


@router.get("/runs/{run_id}/till/stores/{site}/days")
def till_days(request: Request, run_id: str, site: str, cash_run: str):
    with open_run(request, run_id, cash_run=cash_run) as (conn, run):
        days = repo.till_days(conn, run, site)
        top = repo.till_day_row(conn, run, site, run["till_balance_date"])
    if top is None:
        raise HTTPException(404, "unknown store")
    net = sum((d["debit"] - d["credit"] for d in days), repo.ZERO)
    return ok({**header(run), "site_code": site, "balance_date": run["till_balance_date"], "parent": {"balance": top["cumulative_balance"]}, "children_sum": {"balance": net},
               "reconciles": net == top["cumulative_balance"], "deepest_level": "till_day",
               "note": "The till drill ends at the store-day: individual POS cash lines are not part of the entry layer.", "days": days})


# ───────────── creditors ─────────────


@router.get("/runs/{run_id}/creditors/items/{item_ref}/link")
def creditor_link(request: Request, run_id: str, item_ref: str, creditors_run: str):
    with open_run(request, run_id, creditors_run=creditors_run) as (conn, run):
        k = repo.bill_link(conn, run_id, item_ref)
        if k is None:
            raise HTTPException(404, "unknown bill")
        return ok({**header(run), "link": k, "attachment": repo.NO_ATTACHMENT})


@router.get("/runs/{run_id}/creditors/links")
def creditor_links(request: Request, run_id: str, creditors_run: str):
    with open_run(request, run_id, creditors_run=creditors_run) as (conn, run):
        return ok({**header(run), **repo.link_summary(conn, run_id)})
