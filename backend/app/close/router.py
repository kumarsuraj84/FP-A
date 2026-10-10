"""Month-end close API.  /api/v1/close/*

  GET  /readiness?entity=SUBCO|HOLDCO&month=2026-09     the checklist, blockers, outcome, period status
  GET  /periods?from_month=&to_month=                  status of each month for both entities       GET /history?entity=&month=   period events
  POST /signoff {entity, month, check_key, decision, comment}      sign off a manual item, or override an item with attention points (never a blocker)
  POST /period/{soft-close|management-close|final-close|reopen} {entity, month, reason}
Reads need a signed-in user; writes need a session, the X-FPA-Request header and a role (the database enforces who may close, finally close and reopen)."""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal as D

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from ..adjustments.service import Problem
from ..appdb.conn import app_connection
from ..auth.router import current_actor, writer
from ..auth.service import Actor
from . import service as svc

router = APIRouter(prefix="/api/v1/close")


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


@router.get("/readiness")
def readiness(request: Request, entity: str, month: str, actor: Actor = Depends(current_actor)):
    gold = database(request)
    with app_connection() as app:
        return ok(guard(lambda: svc.readiness(app, gold, entity.upper(), month)))


@router.get("/periods")
def periods(from_month: str, to_month: str, actor: Actor = Depends(current_actor)):
    with app_connection() as app:
        return ok(guard(lambda: svc.periods(app, from_month, to_month)))


@router.get("/history")
def history(entity: str, month: str, actor: Actor = Depends(current_actor)):
    with app_connection() as app:
        return ok(guard(lambda: svc.period_history(app, entity.upper(), month)))


@router.post("/signoff")
def signoff(body: Body, request: Request, actor: Actor = Depends(writer)):
    p = body.model_dump()
    gold = database(request)
    with app_connection() as app:
        return ok(guard(lambda: svc.signoff(app, gold, actor, str(p.get("entity", "")).upper(), str(p.get("month", "")), str(p.get("check_key", "")), str(p.get("decision", "")), str(p.get("comment", "")))))


@router.post("/period/{action}")
def period(action: str, body: Body, request: Request, actor: Actor = Depends(writer)):
    p = body.model_dump()
    gold = database(request)
    with app_connection() as app:
        return ok(guard(lambda: svc.period_action(app, gold, actor, str(p.get("entity", "")).upper(), str(p.get("month", "")), action, str(p.get("reason", "")))))
