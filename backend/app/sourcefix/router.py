"""Source Fix Candidate API.  /api/v1/source-fixes/*  (advisory; never changes a mapping, a correction or finance data)

  GET  /                 ranked open candidates (status, issue filters), counts, versioned thresholds     GET /export   plain-text list for the extraction team
  POST /refresh          recompute from corrections and mapping versions; run the post-fix validation
  GET  /{id}  /{id}/history    POST /{id}/acknowledge | implemented {fix_date, comment} | dismiss {comment} | comment | owners {finance_owner, data_owner}"""
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
from . import service as svc

router = APIRouter(prefix="/api/v1/source-fixes")


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
def listing(status: str | None = None, issue: str | None = None, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), actor: Actor = Depends(current_actor)):
    with app_connection() as conn:
        return ok(guard(lambda: svc.listing(conn, status, issue, limit, offset)))


@router.get("/export")
def export(actor: Actor = Depends(current_actor)):
    with app_connection() as conn:
        return ok({"text": svc.export_text(conn)})


@router.post("/refresh")
def refresh(request: Request, actor: Actor = Depends(writer)):
    gold = database(request)
    with app_connection() as conn:
        return ok(guard(lambda: svc.refresh(conn, gold, actor)))


@router.get("/{cid}")
def one(cid: str, actor: Actor = Depends(current_actor)):
    with app_connection() as conn:
        return ok(guard(lambda: svc.view(svc.fetch(conn, cid))))


@router.get("/{cid}/history")
def history(cid: str, actor: Actor = Depends(current_actor)):
    with app_connection() as conn:
        return ok(guard(lambda: svc.history(conn, cid)))


@router.post("/{cid}/owners")
def owners(cid: str, body: Body, actor: Actor = Depends(writer)):
    p = body.model_dump()
    with app_connection() as conn:
        return ok(guard(lambda: svc.set_owners(conn, actor, cid, p.get("finance_owner"), p.get("data_owner"))))


@router.post("/{cid}/{action}")
def action(cid: str, action: str, body: Body, actor: Actor = Depends(writer)):
    p = body.model_dump()
    with app_connection() as conn:
        return ok(guard(lambda: svc.act(conn, actor, cid, action, p.get("comment"), p.get("fix_date"))))
