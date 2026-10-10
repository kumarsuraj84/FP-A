"""Exception Inbox API.  /api/v1/exceptions/*

  GET  /                       ranked list (default: top 20 open); filters status, domain, band, owner, search, mine=true      GET /{id}   one + lineage      GET /{id}/history
  POST /detect                 run the detectors and write candidates (manager, reviewer, controller, admin)
  POST /{id}/assign            {owner_user_id, due_date, next_action}     POST /{id}/due {due_date}     POST /{id}/next-action {text}     POST /{id}/comment {comment}
  POST /{id}/acknowledge | resolve | return | close {comment, closure_reason} | reopen
Workflow only: nothing here can change a reported number."""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal as D

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel

from ..adjustments.service import Problem
from ..appdb.conn import app_connection
from ..auth.router import current_actor, writer
from ..auth.service import Actor
from . import detectors
from . import service as svc

router = APIRouter(prefix="/api/v1/exceptions")


def ok(data) -> Response:
    def enc(o):
        return str(o) if isinstance(o, D) else (o.isoformat() if isinstance(o, (date, datetime)) else str(o))
    return Response(content=json.dumps({"data": data}, default=enc), media_type="application/json")


def database(request: Request):
    db = getattr(request.app.state, "db", None)
    return db if db is not None and hasattr(db, "rel") else None


def guard(fn):
    try:
        return fn()
    except Problem as e:
        raise HTTPException(e.status, e.message) from None


class Body(BaseModel):
    model_config = {"extra": "allow"}


@router.get("")
def listing(status: str | None = None, domain: str | None = None, band: str | None = None, owner: str | None = None, mine: bool = False, search: str | None = None,
            top: int | None = Query(20, ge=1, le=500), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), actor: Actor = Depends(current_actor)):
    with app_connection() as conn:
        return ok(guard(lambda: svc.listing(conn, status, domain, band, owner, actor.user_id if mine else None, search, top if not (status or search or domain or band or owner or mine) else None, limit, offset)))


@router.post("/detect")
def detect(request: Request, actor: Actor = Depends(writer)):
    def go():
        svc.need(actor, svc.ASSIGNERS, "run detection")
        gold = database(request)
        with app_connection() as conn:
            if gold is None:
                cands, errors = detectors.provision_gaps(conn) + detectors.stale_approvals(conn), ["management data unavailable: only the workflow detectors ran"]
            else:
                with gold.session("pnl") as g:
                    cands, errors = detectors.run_all(conn, g)
            res = svc.ingest(conn, cands)
            return {**res, "candidates": len(cands), "errors": errors}
    return ok(guard(go))


@router.get("/{case_id}")
def one(case_id: str, actor: Actor = Depends(current_actor)):
    with app_connection() as conn:
        return ok(guard(lambda: {**svc.case_view(svc.fetch(conn, case_id)), "lineage": svc.lineage(conn, case_id)}))


@router.get("/{case_id}/history")
def history(case_id: str, actor: Actor = Depends(current_actor)):
    with app_connection() as conn:
        return ok(guard(lambda: svc.history(conn, case_id)))


@router.post("/{case_id}/assign")
def assign(case_id: str, body: Body, actor: Actor = Depends(writer)):
    p = body.model_dump()
    with app_connection() as conn:
        return ok(guard(lambda: svc.assign(conn, actor, case_id, str(p.get("owner_user_id", "")), p.get("due_date"), p.get("next_action"))))


@router.post("/{case_id}/due")
def due(case_id: str, body: Body, actor: Actor = Depends(writer)):
    with app_connection() as conn:
        return ok(guard(lambda: svc.set_due(conn, actor, case_id, str(body.model_dump().get("due_date", "")))))


@router.post("/{case_id}/next-action")
def next_action(case_id: str, body: Body, actor: Actor = Depends(writer)):
    with app_connection() as conn:
        return ok(guard(lambda: svc.set_next_action(conn, actor, case_id, str(body.model_dump().get("text", "")))))


@router.post("/{case_id}/comment")
def comment(case_id: str, body: Body, actor: Actor = Depends(writer)):
    with app_connection() as conn:
        return ok(guard(lambda: svc.comment(conn, actor, case_id, str(body.model_dump().get("comment", "")))))


@router.post("/{case_id}/{action}")
def action(case_id: str, action: str, body: Body, actor: Actor = Depends(writer)):
    p = body.model_dump()
    with app_connection() as conn:
        return ok(guard(lambda: svc.act(conn, actor, case_id, action, p.get("comment"), p.get("closure_reason"))))
