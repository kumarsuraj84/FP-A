"""Adjustments and Provisions API.  /api/v1/adjustments/*  (named actions only; there is no generic PATCH after a draft is submitted)

Reads need a signed-in user; writes need a session, the X-FPA-Request header, an allowed Origin and a role (see service.MAKERS / CHECKERS). Money is exact Decimal
serialised as a JSON string in rupees, and as a number in crore in the *_cr fields.

  POST   /                       create a draft (FIXED, RATE or MANUAL)        PUT /{id}   edit a draft
  POST   /preview                impact preview of a not-yet-saved adjustment  GET /{id}/preview   preview of a saved one
  POST   /{id}/submit | approve | activate | reject | withdraw | request-reversal | approve-reversal | reject-reversal | comment
  GET    /                       list (month, status, entity, line)            GET /{id}   one          GET /{id}/history   events
  GET    /calendar               provision calendar                            GET /templates   list
  POST   /templates              create a recurring template                   POST /templates/{id}/approve | pause | resume | retire
  POST   /templates/generate/{month}   create the month's rows from the active templates
"""
from __future__ import annotations

import json
from decimal import Decimal as D

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel

from ..appdb.conn import app_connection
from ..auth.router import current_actor, writer
from ..auth.service import Actor
from .. import cutover as cut
from . import register_import as reg
from . import service as svc
from . import templates as tpl
from .service import Problem

router = APIRouter(prefix="/api/v1/adjustments")


def ok(data) -> Response:
    return Response(content=json.dumps({"data": data}, default=lambda o: str(o) if isinstance(o, D) else (o.isoformat() if hasattr(o, "isoformat") else str(o))), media_type="application/json")


def database(request: Request):
    """The gold_fpa reader, or None when the API runs without it: only RATE adjustments, impact previews and generation of rate templates need it."""
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


@router.get("/validate-register")
def validate_register(request: Request, from_month: str | None = None, to_month: str | None = None, actor: Actor = Depends(current_actor)):
    gold = database(request)
    return ok(guard(lambda: reg.validate_register(gold, from_month, to_month)))


@router.post("/import-register")
def import_register(actor: Actor = Depends(writer)):
    with app_connection() as conn:
        return ok(guard(lambda: reg.import_register(conn, actor)))


@router.post("/cutover")
def cutover(body: Body, request: Request, actor: Actor = Depends(writer)):
    p = body.model_dump()
    gold = database(request)

    def go():
        v = reg.validate_register(gold, None, None)
        with app_connection() as conn:
            return cut.record(conn, actor, "ADJUSTMENTS", str(p.get("first_month", "")), str(p.get("comment", "")), v)
    return ok(guard(go))


@router.get("/calendar")
def calendar(from_month: str, to_month: str, actor: Actor = Depends(current_actor)):
    with app_connection() as conn:
        return ok(guard(lambda: tpl.calendar(conn, from_month, to_month)))


@router.get("/templates")
def templates(actor: Actor = Depends(current_actor)):
    with app_connection() as conn:
        return ok(tpl.listing(conn))


@router.post("/templates")
def create_template(body: Body, actor: Actor = Depends(writer)):
    with app_connection() as conn:
        return ok(guard(lambda: tpl.create(conn, actor, body.model_dump())))


@router.post("/templates/generate/{month}")
def generate(month: str, request: Request, actor: Actor = Depends(writer)):
    gold = database(request)
    with app_connection() as conn:
        return ok(guard(lambda: tpl.generate(conn, gold, actor, month)))


@router.post("/templates/{template_id}/{action}")
def template_action(template_id: str, action: str, actor: Actor = Depends(writer)):
    with app_connection() as conn:
        return ok(guard(lambda: tpl.change_status(conn, actor, template_id, action)))


@router.post("/preview")
def preview_new(body: Body, request: Request, entity_view: str = Query("all", pattern="^(consolidated|subco|holdco|all)$"), actor: Actor = Depends(current_actor)):
    gold = database(request)
    with app_connection() as conn:
        return ok(guard(lambda: svc.preview(conn, gold, svc.validate_shape(body.model_dump()), entity_view)))


@router.get("")
def listing(month: str | None = None, status: str | None = None, entity: str | None = None, line: str | None = None, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
            actor: Actor = Depends(current_actor)):
    with app_connection() as conn:
        return ok(guard(lambda: svc.listing(conn, month, status, entity, line, limit, offset)))


@router.post("")
def create(body: Body, request: Request, actor: Actor = Depends(writer)):
    gold = database(request)
    with app_connection() as conn:
        return ok(guard(lambda: svc.create(conn, gold, actor, body.model_dump())))


@router.get("/{adjustment_id}")
def one(adjustment_id: str, actor: Actor = Depends(current_actor)):
    with app_connection() as conn:
        return ok(guard(lambda: svc.view(svc.fetch(conn, adjustment_id))))


@router.put("/{adjustment_id}")
def edit(adjustment_id: str, body: Body, request: Request, actor: Actor = Depends(writer)):
    gold = database(request)
    with app_connection() as conn:
        return ok(guard(lambda: svc.update_draft(conn, gold, actor, adjustment_id, body.model_dump())))


@router.get("/{adjustment_id}/history")
def history(adjustment_id: str, actor: Actor = Depends(current_actor)):
    with app_connection() as conn:
        return ok(guard(lambda: svc.history(conn, adjustment_id)))


@router.get("/{adjustment_id}/preview")
def preview_saved(adjustment_id: str, request: Request, entity_view: str = Query("all", pattern="^(consolidated|subco|holdco|all)$"), actor: Actor = Depends(current_actor)):
    gold = database(request)
    with app_connection() as conn:
        return ok(guard(lambda: svc.preview(conn, gold, adjustment_id, entity_view)))


@router.post("/{adjustment_id}/submit")
def submit(adjustment_id: str, request: Request, actor: Actor = Depends(writer)):
    gold = database(request)
    with app_connection() as conn:
        return ok(guard(lambda: svc.submit(conn, gold, actor, adjustment_id)))


@router.post("/{adjustment_id}/comment")
def comment(adjustment_id: str, body: CommentBody, actor: Actor = Depends(writer)):
    with app_connection() as conn:
        return ok(guard(lambda: svc.comment(conn, actor, adjustment_id, body.comment or "")))


@router.post("/{adjustment_id}/{action}")
def action(adjustment_id: str, action: str, body: CommentBody, actor: Actor = Depends(writer)):
    with app_connection() as conn:
        return ok(guard(lambda: svc.act(conn, actor, adjustment_id, action, body.comment)))
