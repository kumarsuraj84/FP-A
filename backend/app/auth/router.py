"""Login, session and administrator-managed users.  /api/v1/auth/*

Session = opaque random token in an HttpOnly, SameSite=Strict cookie (Secure when FPA_COOKIE_SECURE=1); only its sha256 is stored. Every state-changing request must
also carry the header X-FPA-Request: 1, which a cross-site form cannot send (CSRF defence in depth on top of SameSite). Accounts are created by an administrator only."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from . import service as svc
from .service import Actor, AuthError

router = APIRouter(prefix="/api/v1/auth")
COOKIE = "fpa_session"
CSRF_HEADER = "x-fpa-request"


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def allowed_origins() -> set[str]:
    return {o.strip().rstrip("/") for o in os.environ.get("FPA_CRED_CORS", "http://localhost:5180,http://127.0.0.1:5180").split(",") if o.strip()}


def csrf(request: Request) -> None:
    """Custom header (a cross-site form cannot send it) plus the Origin of the request when the browser sends one (it always does on cross-site and on fetch POST)."""
    if request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(403, "Missing the X-FPA-Request header.")
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in allowed_origins():
        raise HTTPException(403, "This origin is not allowed to change data.")


def current_actor(request: Request) -> Actor:
    a = svc.resolve(request.cookies.get(COOKIE))
    if a is None:
        raise HTTPException(401, "Sign in required.")
    return a


def writer(request: Request) -> Actor:
    """A signed-in actor allowed to change data: CSRF header present and the temporary password already changed."""
    csrf(request)
    a = current_actor(request)
    if a.must_change_password:
        raise HTTPException(403, "Change your password first.")
    return a


def require_roles(*roles: str):
    def dep(a: Actor = Depends(writer)) -> Actor:
        if a.role not in roles:
            raise HTTPException(403, "Your role does not allow this action.")
        return a
    return dep


def _fail(e: AuthError):
    raise HTTPException(e.status, e.message)


class LoginBody(BaseModel):
    email: str
    password: str


class PasswordBody(BaseModel):
    current_password: str
    new_password: str


class NewUserBody(BaseModel):
    email: str
    display_name: str
    role: str


class RoleBody(BaseModel):
    role: str


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response):
    csrf(request)
    try:
        token, actor = svc.login(body.email, body.password, _ip(request))
    except AuthError as e:
        _fail(e)
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=os.environ.get("FPA_COOKIE_SECURE") == "1", max_age=svc.ABSOLUTE_HOURS * 3600, path="/")
    return {"data": actor.public()}


@router.post("/logout")
def logout(request: Request, response: Response, actor: Actor = Depends(current_actor)):
    csrf(request)
    svc.logout(actor, _ip(request))
    response.delete_cookie(COOKIE, path="/")
    return {"data": {"signed_out": True}}


@router.get("/me")
def me(actor: Actor = Depends(current_actor)):
    return {"data": actor.public()}


@router.post("/change-password")
def change_password(body: PasswordBody, request: Request, response: Response, actor: Actor = Depends(current_actor)):
    csrf(request)
    try:
        svc.change_password(actor, body.current_password, body.new_password, _ip(request))
    except AuthError as e:
        _fail(e)
    response.delete_cookie(COOKIE, path="/")      # every session was revoked: sign in again
    return {"data": {"changed": True}}


@router.get("/admin/users")
def users(actor: Actor = Depends(current_actor)):
    try:
        return {"data": svc.list_users(actor)}
    except AuthError as e:
        _fail(e)


@router.post("/admin/users")
def create_user(body: NewUserBody, request: Request, actor: Actor = Depends(writer)):
    try:
        return {"data": svc.create_user(actor, body.email, body.display_name, body.role, _ip(request))}
    except AuthError as e:
        _fail(e)


@router.post("/admin/users/{user_id}/role")
def set_role(user_id: str, body: RoleBody, request: Request, actor: Actor = Depends(writer)):
    try:
        svc.set_role(actor, user_id, body.role, _ip(request))
    except AuthError as e:
        _fail(e)
    return {"data": {"ok": True}}


@router.post("/admin/users/{user_id}/deactivate")
def deactivate(user_id: str, request: Request, actor: Actor = Depends(writer)):
    try:
        svc.set_active(actor, user_id, False, _ip(request))
    except AuthError as e:
        _fail(e)
    return {"data": {"ok": True}}


@router.post("/admin/users/{user_id}/activate")
def activate(user_id: str, request: Request, actor: Actor = Depends(writer)):
    try:
        svc.set_active(actor, user_id, True, _ip(request))
    except AuthError as e:
        _fail(e)
    return {"data": {"ok": True}}


@router.post("/admin/users/{user_id}/reset-password")
def reset_password(user_id: str, request: Request, actor: Actor = Depends(writer)):
    try:
        return {"data": svc.reset_password(actor, user_id, _ip(request))}
    except AuthError as e:
        _fail(e)


@router.post("/admin/users/{user_id}/unlock")
def unlock(user_id: str, request: Request, actor: Actor = Depends(writer)):
    try:
        svc.unlock(actor, user_id, _ip(request))
    except AuthError as e:
        _fail(e)
    return {"data": {"ok": True}}
