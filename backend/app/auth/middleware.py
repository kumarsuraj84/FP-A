"""Session-required mode for every data route (FPA_REQUIRE_SESSION=1). Off by default: reads keep working through the transitional proxy token. On, any /api/v1 request without a valid
signed-in session is refused with 401, except the sign-in endpoints themselves. A valid session is remembered for a few seconds so one page load (many parallel reads) costs one lookup."""
from __future__ import annotations

import os
import time

from starlette.responses import JSONResponse

from . import service as svc

EXEMPT = ("/api/v1/auth/login", "/api/v1/auth/me", "/api/v1/auth/logout", "/api/v1/auth/change-password")
TTL = 5.0
_ok: dict[str, float] = {}


def enabled() -> bool:
    return os.environ.get("FPA_REQUIRE_SESSION", "0") == "1"


class RequireSession:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not enabled():
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if not path.startswith("/api/v1/") or path in EXEMPT or scope.get("method") == "OPTIONS":
            return await self.app(scope, receive, send)
        cookie = ""
        for k, v in scope.get("headers", []):
            if k == b"cookie":
                for part in v.decode("latin-1").split(";"):
                    name, _, val = part.strip().partition("=")
                    if name == "fpa_session":
                        cookie = val
        key = svc.token_hash(cookie) if cookie else ""
        now = time.monotonic()
        if key and _ok.get(key, 0) > now:
            return await self.app(scope, receive, send)
        actor = None
        if cookie:
            try:
                actor = svc.resolve(cookie)
            except Exception:  # noqa: BLE001  an unreadable app database is not a valid session
                actor = None
        if actor is None:
            svc.note_read_path("refused")
            return await JSONResponse({"detail": "Sign in required."}, status_code=401)(scope, receive, send)
        _ok[key] = now + TTL
        if len(_ok) > 2000:
            _ok.clear()
        return await self.app(scope, receive, send)
