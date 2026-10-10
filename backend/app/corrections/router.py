"""Corrections API.  /api/v1/corrections/*  (named actions only; no amount field exists; no generic PATCH)

  POST /                 create (scope LINE | VOUCHER | BULK; line_keys or voucher; corrected_group and/or corrected_month; reason_code, reason_text, evidence_reference)
  GET  /                 list with counts by status       GET /{id}   one with its lines       GET /{id}/history       GET /{id}/preview   before / reclass / after
  POST /{id}/submit | approve | activate | reject | withdraw | void | request-reversal | approve-reversal | reject-reversal | reconfirm-source | comment
  POST /source-check     re-read every ACTIVE correction from the finance data (run after each refresh)
  GET  /groups           the Management P&L groups a line can be corrected to
"""
from __future__ import annotations

import json
from decimal import Decimal as D

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel

from ..adjustments.service import Problem
from ..appdb.conn import app_connection
from ..auth.router import current_actor, writer
from ..auth.service import Actor
from ..mgmt import config as cfg
from . import service as svc

router = APIRouter(prefix="/api/v1/corrections")


def ok(data) -> Response:
    return Response(content=json.dumps({"data": data}, default=lambda o: str(o) if isinstance(o, D) else (o.isoformat() if hasattr(o, "isoformat") else str(o))), media_type="application/json")


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


@router.get("/groups")
def groups(actor: Actor = Depends(current_actor)):
    return ok([{"group": g, "line": cfg.KEY_OF_GROUP[g]} for g in svc.P_L_GROUPS])


@router.get("/source-lines")
def source_lines(request: Request, entity: str, voucher: str, actor: Actor = Depends(current_actor)):
    gold = database(request)
    with app_connection() as conn:
        return ok(guard(lambda: svc.source_lines(conn, gold, entity, voucher)))


@router.post("/preview")
def preview_new(body: Body, request: Request, actor: Actor = Depends(writer)):
    gold = database(request)
    return ok(guard(lambda: svc.preview_payload(gold, body.model_dump())))


@router.post("/source-check")
def source_check(request: Request, actor: Actor = Depends(writer)):
    gold = database(request)
    with app_connection() as conn:
        return ok(guard(lambda: svc.source_check(conn, gold, actor)))


@router.get("")
def listing(status: str | None = None, entity: str | None = None, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), actor: Actor = Depends(current_actor)):
    with app_connection() as conn:
        return ok(guard(lambda: svc.listing(conn, status, entity, limit, offset)))


@router.post("")
def create(body: Body, request: Request, actor: Actor = Depends(writer)):
    gold = database(request)
    with app_connection() as conn:
        return ok(guard(lambda: svc.create(conn, gold, actor, body.model_dump())))


@router.get("/{request_id}")
def one(request_id: str, actor: Actor = Depends(current_actor)):
    with app_connection() as conn:
        return ok(guard(lambda: svc.view(conn, request_id)))


@router.get("/{request_id}/history")
def history(request_id: str, actor: Actor = Depends(current_actor)):
    with app_connection() as conn:
        return ok(guard(lambda: svc.history(conn, request_id)))


@router.get("/{request_id}/preview")
def preview(request_id: str, request: Request, actor: Actor = Depends(current_actor)):
    gold = database(request)
    with app_connection() as conn:
        return ok(guard(lambda: svc.preview(conn, gold, request_id)))


@router.post("/{request_id}/comment")
def comment(request_id: str, body: CommentBody, actor: Actor = Depends(writer)):
    def go():
        if len((body.comment or "").strip()) < 3:
            raise Problem("Write a comment.")
        with app_connection() as conn:
            svc.view(conn, request_id, with_lines=False)
            svc.event(conn, actor, request_id, "COMMENTED", "DRAFT", body.comment.strip())
            conn.commit()
            return svc.view(conn, request_id, with_lines=False)
    return ok(guard(go))


@router.post("/{request_id}/{action}")
def action(request_id: str, action: str, body: CommentBody, request: Request, actor: Actor = Depends(writer)):
    gold = database(request)
    with app_connection() as conn:
        return ok(guard(lambda: svc.act(conn, gold, actor, request_id, action, body.comment)))
