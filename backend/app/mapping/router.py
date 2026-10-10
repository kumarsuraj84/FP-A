"""Mapping Governance API.  /api/v1/mapping/*

  GET  /               rules (domain, status, search) with counts, the source the engine uses now (FPA_MAPPING_SOURCE) and the group list
  POST /               propose a rule (a new version supersedes the one in force)     GET /{id}   one + versions + events     GET /{id}/preview   P&L impact
  POST /preview        impact of an unsaved proposal (nothing is written)
  POST /{id}/submit | approve | activate | reject | withdraw | void | retire | comment
  GET  /validate       the app mapping against the legacy CSV (keys and Management P&L lines)        POST /import   one-time baseline (administrator)
Reads need a signed-in user; writes need a session, the X-FPA-Request header and a role; the database enforces maker-checker and the lifecycle."""
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
from .. import cutover as cut
from . import service as svc

router = APIRouter(prefix="/api/v1/mapping")


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


class CommentBody(BaseModel):
    comment: str | None = None


@router.get("/validate")
def validate(request: Request, from_month: str | None = None, to_month: str | None = None, actor: Actor = Depends(current_actor)):
    gold = database(request)
    with app_connection() as conn:
        return ok(guard(lambda: svc.validate(conn, gold, from_month, to_month)))


@router.post("/import")
def import_baseline(actor: Actor = Depends(writer)):
    with app_connection() as conn:
        return ok(guard(lambda: svc.import_baseline(conn, actor)))


@router.post("/cutover")
def cutover(body: Body, request: Request, actor: Actor = Depends(writer)):
    p = body.model_dump()
    gold = database(request)

    def go():
        with app_connection() as conn:
            v = svc.validate(conn, gold, None, None)
            return cut.record(conn, actor, "MAPPING", str(p.get("first_month", "")), str(p.get("comment", "")), v)
    return ok(guard(go))


@router.post("/preview")
def preview_new(body: Body, request: Request, actor: Actor = Depends(current_actor)):
    gold = database(request)
    return ok(guard(lambda: svc.preview_payload(gold, body.model_dump())))


@router.get("")
def listing(domain: str | None = None, status: str | None = None, search: str | None = None, limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0), actor: Actor = Depends(current_actor)):
    with app_connection() as conn:
        return ok(guard(lambda: svc.listing(conn, domain, status, search, limit, offset)))


@router.post("")
def create(body: Body, actor: Actor = Depends(writer)):
    with app_connection() as conn:
        return ok(guard(lambda: svc.create(conn, actor, body.model_dump())))


@router.get("/{mapping_id}")
def one(mapping_id: str, actor: Actor = Depends(current_actor)):
    with app_connection() as conn:
        return ok(guard(lambda: {**svc.view(svc.fetch(conn, mapping_id)), **svc.history(conn, mapping_id)}))


@router.get("/{mapping_id}/preview")
def preview_saved(mapping_id: str, request: Request, actor: Actor = Depends(current_actor)):
    gold = database(request)
    with app_connection() as conn:
        return ok(guard(lambda: svc.preview_saved(conn, gold, mapping_id)))


@router.post("/{mapping_id}/comment")
def comment(mapping_id: str, body: CommentBody, actor: Actor = Depends(writer)):
    with app_connection() as conn:
        return ok(guard(lambda: svc.comment(conn, actor, mapping_id, body.comment or "")))


@router.post("/{mapping_id}/{action}")
def action(mapping_id: str, action: str, body: CommentBody, actor: Actor = Depends(writer)):
    with app_connection() as conn:
        return ok(guard(lambda: svc.act(conn, actor, mapping_id, action, body.comment)))
