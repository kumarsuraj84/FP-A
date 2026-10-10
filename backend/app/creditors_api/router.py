"""HTTP surface of the Creditors API (read-only). Money is serialised as exact decimal text; the UI never receives a float for a rupee value.

  /api/v1/creditors/health | current | candidates
  /api/v1/creditors/runs/{run_id}                      status: run, states, data_state, control tallies
  /api/v1/creditors/runs/{run_id}/summary | document-age | due-status | ledgers | controls
  /api/v1/creditors/runs/{run_id}/vendors              masked: vendor_ref only
  /api/v1/creditors/runs/{run_id}/vendors/{ref}        masked vendor profile
  /api/v1/creditors/runs/{run_id}/vendors/{ref}/items  masked open items
  /api/v1/creditors/runs/{run_id}/finance/vendors ...  the same with vendor name and codes; needs the Finance bearer token
"""
from __future__ import annotations

import hmac
import os
import json
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from . import repository as repo

router = APIRouter(prefix="/api/v1/creditors")
STATE_LABEL = {"live": "Live", "verified_candidate": "Verified candidate (not published)", "superseded": "Superseded", "withdrawn": "Withdrawn"}
HEADER_KEYS = ("extraction_run_id", "as_of_date", "recon_state", "publication_state", "data_state", "data_state_label", "contract_version", "rules_version")


def ok(data) -> Response:
    # Decimal and date become text, so no rupee value ever passes through a float
    return Response(content=json.dumps(data, default=str), media_type="application/json")


def finance_gate(request: Request) -> None:
    """Finance routes (party names, narration, document codes). Two ways in, session first:
      1. a signed-in named user (the HttpOnly session cookie): the way forward, and every read is attributed to a person;
      2. the shared bearer token the dev proxy injects: TRANSITIONAL. FPA_ALLOW_PROXY_TOKEN=0 switches it off (then only a session works).
    Which path served each request is counted (GET /api/v1/auth/admin/read-paths) so the token can be retired when nothing uses it any more."""
    from ..auth import service as authsvc
    actor = None
    if request.cookies.get("fpa_session"):
        try:
            actor = authsvc.resolve(request.cookies.get("fpa_session"))
        except Exception:  # noqa: BLE001  the app database being down must not lock the token path out, and must not be mistaken for a valid session
            actor = None
    if actor is not None:
        authsvc.note_read_path("session")
        return
    if os.environ.get("FPA_ALLOW_PROXY_TOKEN", "1") == "0":
        authsvc.note_read_path("refused")
        raise HTTPException(401, "Sign in required")
    token = request.app.state.settings.finance_token
    if not token:
        raise HTTPException(503, "Finance access is not configured on this server")
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:].encode(), token.encode()):
        authsvc.note_read_path("refused")
        raise HTTPException(401, "Finance authorization required")
    authsvc.note_read_path("proxy_token")


def database(request: Request):
    db = request.app.state.db
    if db is None:
        raise HTTPException(503, "The creditors database is not configured on this server")
    return db


@contextmanager
def open_run(request: Request, run_id: str, finance: bool = False):
    """Resolve the run (verified candidate or live), pick the relation and role by access and publication state, and open the read-only session."""
    db = database(request)
    with db.session("candidate") as c:
        run = repo.get_run(c, run_id)
    if run is None:
        raise HTTPException(404, "that run does not exist or has not been verified")
    src = repo.source_for(run, finance)
    with db.session(src.role) as conn:
        yield conn, src, run


def run_header(run: dict) -> dict:
    state = repo.data_state(run)
    return {"extraction_run_id": run["extraction_run_id"], "as_of_date": run["as_of_date"], "recon_state": run["recon_state"], "publication_state": run["publication_state"],
            "data_state": state, "data_state_label": STATE_LABEL[state], "contract_version": run["contract_version"], "rules_version": run["rules_version"]}


@router.get("/health")
def health():
    return ok({"status": "ok"})


@router.get("/current")
def current(request: Request):
    with database(request).session("candidate") as c:
        run = repo.current_run(c)
    if run is None:
        raise HTTPException(404, "no verified creditor run is available yet")
    return ok(run_header(run))


@router.get("/candidates")
def candidates(request: Request):
    with database(request).session("candidate") as c:
        return ok({"runs": [run_header(r) for r in repo.list_candidates(c)]})


@router.get("/runs/{run_id}")
def status(request: Request, run_id: str):
    with open_run(request, run_id) as (conn, src, run):
        return ok({**run_header(run), "expected_rows": run["expected_rows"], "expected_identity_rows": run["expected_identity_rows"], "controls": repo.control_tally(conn, src, run_id),
                   "scope": {"ledgers": 4, "open_items_only": True, "debit_balances_netted_into_credit": False}})


@router.get("/runs/{run_id}/summary")
def summary(request: Request, run_id: str):
    with open_run(request, run_id) as (conn, src, run):
        return ok({**run_header(run), **repo.summary(conn, src, run_id)})


@router.get("/runs/{run_id}/document-age")
def document_age(request: Request, run_id: str):
    with open_run(request, run_id) as (conn, src, run):
        return ok({**run_header(run), "buckets": repo.document_age(conn, src, run_id)})


@router.get("/runs/{run_id}/due-status")
def due_status(request: Request, run_id: str):
    with open_run(request, run_id) as (conn, src, run):
        return ok({**run_header(run), "states": repo.due_status(conn, src, run_id)})


@router.get("/runs/{run_id}/ledgers")
def ledgers(request: Request, run_id: str):
    with open_run(request, run_id) as (conn, src, run):
        return ok({**run_header(run), "ledgers": repo.ledgers(conn, src, run_id)})


@router.get("/runs/{run_id}/controls")
def controls(request: Request, run_id: str):
    with open_run(request, run_id) as (conn, src, run):
        return ok({**run_header(run), **repo.control_tally(conn, src, run_id), "failures": repo.failing_controls(conn, src, run_id)})


def _vendors(request, run_id, finance, ledger_code, party_class, q, sort, order, limit, offset, vendor_ref=None, cohort=None):
    if finance:
        finance_gate(request)
    with open_run(request, run_id, finance) as (conn, src, run):
        return {**run_header(run), **repo.vendors(conn, src, run_id, ledger_code=ledger_code, party_class=party_class, q=q, vendor_ref=vendor_ref, cohort=cohort, sort=sort, descending=(order != "asc"), limit=limit, offset=offset)}


def _cohort(value: str | None) -> str | None:
    if value and value not in repo.COHORTS:
        raise HTTPException(422, f"unknown cohort; use one of {sorted(repo.COHORTS)}")
    return value


def _profile(request, run_id, finance, vendor_ref):
    res = _vendors(request, run_id, finance, None, None, None, "credit_outstanding", "desc", 1, 0, vendor_ref)
    if not res["vendors"]:
        raise HTTPException(404, "unknown vendor")
    return {**{k: res[k] for k in HEADER_KEYS}, "vendor": res["vendors"][0]}


def _items(request, run_id, finance, vendor_ref, drcr, bucket, due, limit, offset):
    if finance:
        finance_gate(request)
    with open_run(request, run_id, finance) as (conn, src, run):
        res = repo.items(conn, src, run_id, vendor_ref, drcr=drcr, bucket=bucket, due=due, limit=limit, offset=offset)
        if res["total_items"] == 0 and not drcr and not bucket and not due:
            raise HTTPException(404, "unknown vendor")
        return {**run_header(run), "vendor_ref": vendor_ref, **res}


@router.get("/runs/{run_id}/vendors")
def vendor_list(request: Request, run_id: str, ledger_code: str | None = None, party_class: str | None = None, cohort: str | None = None, sort: str = "credit_outstanding", order: str = "desc",
                limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    return ok(_vendors(request, run_id, False, ledger_code, party_class, None, sort, order, limit, offset, None, _cohort(cohort)))


@router.get("/runs/{run_id}/vendors/{vendor_ref}")
def vendor_profile(request: Request, run_id: str, vendor_ref: str):
    return ok(_profile(request, run_id, False, vendor_ref))


@router.get("/runs/{run_id}/vendors/{vendor_ref}/items")
def vendor_items(request: Request, run_id: str, vendor_ref: str, drcr: str | None = None, bucket: str | None = None, due: str | None = None,
                 limit: int = Query(500, ge=1, le=2000), offset: int = Query(0, ge=0)):
    return ok(_items(request, run_id, False, vendor_ref, drcr, bucket, due, limit, offset))


@router.get("/runs/{run_id}/finance/vendors")
def finance_vendor_list(request: Request, run_id: str, ledger_code: str | None = None, party_class: str | None = None, q: str | None = None, cohort: str | None = None, sort: str = "credit_outstanding",
                        order: str = "desc", limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    return ok(_vendors(request, run_id, True, ledger_code, party_class, q, sort, order, limit, offset, None, _cohort(cohort)))


@router.get("/runs/{run_id}/finance/vendors/{vendor_ref}")
def finance_vendor_profile(request: Request, run_id: str, vendor_ref: str):
    return ok(_profile(request, run_id, True, vendor_ref))


@router.get("/runs/{run_id}/finance/vendors/{vendor_ref}/items")
def finance_vendor_items(request: Request, run_id: str, vendor_ref: str, drcr: str | None = None, bucket: str | None = None, due: str | None = None,
                         limit: int = Query(500, ge=1, le=2000), offset: int = Query(0, ge=0)):
    return ok(_items(request, run_id, True, vendor_ref, drcr, bucket, due, limit, offset))
