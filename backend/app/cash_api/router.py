"""HTTP surface of the Cash API (read-only). Money is exact decimal text; the data state is decided here, never by the UI.

  /api/v1/cash/health | current | runs
  /api/v1/cash/runs/{run}                 status and control tallies
  /api/v1/cash/runs/{run}/summary         till cash, bank ledger-book review card, creditor obligations, the unavailable list
  /api/v1/cash/runs/{run}/store-till      stores (paged, sortable)
  /api/v1/cash/runs/{run}/bank-ledgers    ledger-book rows of one source (site_register | gl_register | prior_year_closing)
  /api/v1/cash/runs/{run}/controls        control tallies
"""
from __future__ import annotations

from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Query, Request

from ..creditors_api.router import ok
from . import repository as repo

router = APIRouter(prefix="/api/v1/cash")
STATE_LABEL = {"live": "Live", "verified_candidate": "Verified candidate (not published)", "superseded": "Superseded", "withdrawn": "Withdrawn"}


def database(request: Request):
    db = request.app.state.db
    if db is None:
        raise HTTPException(503, "The cash database is not configured on this server")
    return db


@contextmanager
def open_run(request: Request, run_id: str):
    db = database(request)
    with db.session("cash") as conn:
        run = repo.serving_run(conn, run_id)
        if run is None:
            raise HTTPException(404, "that run does not exist or has not been verified")
        yield conn, run


def header(run: dict) -> dict:
    state = repo.data_state(run)
    return {"run_id": run["run_id"], "as_of_date": run["as_of_date"], "till_balance_date": run["till_balance_date"], "recon_state": run["recon_state"], "publication_state": run["publication_state"],
            "data_state": state, "data_state_label": STATE_LABEL[state], "contract_version": run["contract_version"], "source_updated_at": run["extract_finished_at"]}


@router.get("/health")
def health():
    return ok({"status": "ok"})


@router.get("/current")
def current(request: Request):
    with database(request).session("cash") as conn:
        run = repo.serving_run(conn)
    if run is None:
        raise HTTPException(404, "no verified cash run is available yet")
    return ok(header(run))


@router.get("/runs")
def runs(request: Request):
    with database(request).session("cash") as conn:
        return ok({"runs": [header(r) for r in repo.list_runs(conn)]})


@router.get("/runs/{run_id}")
def status(request: Request, run_id: str):
    with open_run(request, run_id) as (conn, run):
        return ok({**header(run), "expected_store_rows": run["expected_store_rows"], "expected_bank_rows": run["expected_bank_rows"], "controls": repo.controls(conn, run_id)})


@router.get("/runs/{run_id}/summary")
def summary(request: Request, run_id: str):
    with open_run(request, run_id) as (conn, run):
        body = {**header(run), "till": repo.till(conn, run_id), "bank_review": repo.bank_review(conn, run_id)}
    body["creditors"] = repo.creditor_obligations(database(request))
    body["unavailable"] = repo.UNAVAILABLE
    return ok(body)


@router.get("/runs/{run_id}/store-till")
def store_till(request: Request, run_id: str, sort: str = "balance", order: str = "desc", limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    with open_run(request, run_id) as (conn, run):
        return ok({**header(run), **repo.store_rows(conn, run_id, sort, order != "asc", limit, offset)})


@router.get("/runs/{run_id}/bank-ledgers")
def bank_ledgers(request: Request, run_id: str, source: str = "site_register"):
    if source not in ("site_register", "gl_register", "prior_year_closing"):
        raise HTTPException(422, "source must be site_register, gl_register or prior_year_closing")
    with open_run(request, run_id) as (conn, run):
        return ok({**header(run), "status": repo.BANK_STATUS, "source": source, "ledgers": repo.bank_rows(conn, run_id, source)})


@router.get("/runs/{run_id}/controls")
def controls(request: Request, run_id: str):
    with open_run(request, run_id) as (conn, run):
        return ok({**header(run), **repo.controls(conn, run_id)})
