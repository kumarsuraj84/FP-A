"""Identity tests against the real app database. The service opens its own connections and commits, so the tests swap in ONE connection whose commit is a no-op and
roll it back at the end: no user, session or audit row is left behind. Skipped without fpa_app."""
from __future__ import annotations

import psycopg
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from app.appdb.conn import app_connection
from app.auth import router as auth_router
from app.creditors_api.router import finance_gate
from app.auth import service as svc

try:
    _c = app_connection()
    _c.close()
    HAVE_DB = True
except Exception:  # noqa: BLE001
    HAVE_DB = False

pytestmark = pytest.mark.skipif(not HAVE_DB, reason="fpa_app not reachable")
H = {"X-FPA-Request": "1"}
PW = "Correct-Horse-Battery-9"


class Shared:
    """One real connection that ignores commit and close, so everything stays in one transaction."""

    def __init__(self):
        self.c = app_connection()

    def execute(self, *a, **k):
        return self.c.execute(*a, **k)

    def commit(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture()
def shared(monkeypatch):
    s = Shared()
    monkeypatch.setattr(svc, "app_connection", lambda: s)
    try:
        yield s
    finally:
        s.c.rollback()
        s.c.close()


@pytest.fixture()
def client(shared):
    app = FastAPI()
    app.include_router(auth_router.router)
    return TestClient(app)


def make_admin(shared, email="admin@example.test"):
    shared.execute("UPDATE app_user SET role = 'viewer' WHERE role = 'admin'")      # inside this rolled-back transaction only: a real administrator may exist now
    svc.bootstrap_admin(email, "Admin", PW)
    return email


def test_bootstrap_has_no_default_and_only_one_admin(shared):
    shared.execute("UPDATE app_user SET role = 'viewer' WHERE role = 'admin'")
    with pytest.raises(svc.AuthError):
        svc.bootstrap_admin("a@example.test", "A", "short")
    make_admin(shared)
    with pytest.raises(svc.AuthError) as e:
        svc.bootstrap_admin("b@example.test", "B", PW)
    assert e.value.status == 409


def test_login_sets_httponly_strict_cookie_and_me_works(shared, client):
    make_admin(shared)
    r = client.post("/api/v1/auth/login", json={"email": "ADMIN@example.test", "password": PW}, headers=H)
    assert r.status_code == 200 and r.json()["data"]["role"] == "admin"
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=strict" in sc
    assert client.get("/api/v1/auth/me").json()["data"]["email"] == "admin@example.test"


def test_login_without_csrf_header_is_refused(shared, client):
    make_admin(shared)
    assert client.post("/api/v1/auth/login", json={"email": "admin@example.test", "password": PW}).status_code == 403


def test_wrong_password_is_generic_and_locks_after_five(shared, client):
    make_admin(shared)
    msgs = set()
    for _ in range(4):
        r = client.post("/api/v1/auth/login", json={"email": "admin@example.test", "password": "wrong"}, headers=H)
        msgs.add(r.json()["detail"])
    r = client.post("/api/v1/auth/login", json={"email": "nobody@example.test", "password": "wrong"}, headers=H)
    msgs.add(r.json()["detail"])
    assert msgs == {svc.GENERIC}
    r = client.post("/api/v1/auth/login", json={"email": "admin@example.test", "password": "wrong"}, headers=H)   # fifth failure locks
    r = client.post("/api/v1/auth/login", json={"email": "admin@example.test", "password": PW}, headers=H)
    assert r.status_code == 423
    actions = [x["action"] for x in shared.execute("SELECT action FROM audit_event WHERE actor_email = 'admin@example.test' ORDER BY event_id").fetchall()]
    assert "login_failed" in actions and "login_locked" in actions and "login_blocked" in actions


def test_admin_creates_user_who_must_change_the_temporary_password(shared, client):
    make_admin(shared)
    client.post("/api/v1/auth/login", json={"email": "admin@example.test", "password": PW}, headers=H)
    r = client.post("/api/v1/auth/admin/users", json={"email": "m@example.test", "display_name": "Manager", "role": "fpa_manager"}, headers=H)
    temp = r.json()["data"]["temporary_password"]
    c2 = TestClient(client.app)
    assert c2.post("/api/v1/auth/login", json={"email": "m@example.test", "password": temp}, headers=H).json()["data"]["must_change_password"] is True
    assert c2.post("/api/v1/auth/admin/users", json={"email": "x@example.test", "display_name": "X", "role": "viewer"}, headers=H).status_code == 403   # not an admin
    bad = c2.post("/api/v1/auth/change-password", json={"current_password": temp, "new_password": "short"}, headers=H)
    assert bad.status_code == 400
    ok = c2.post("/api/v1/auth/change-password", json={"current_password": temp, "new_password": "A-Much-Longer-Pass-77"}, headers=H)
    assert ok.status_code == 200
    assert c2.get("/api/v1/auth/me").status_code == 401                 # every session was revoked
    assert c2.post("/api/v1/auth/login", json={"email": "m@example.test", "password": "A-Much-Longer-Pass-77"}, headers=H).json()["data"]["must_change_password"] is False


def test_non_admin_cannot_manage_users_and_self_signup_does_not_exist(shared, client):
    make_admin(shared)
    assert client.post("/api/v1/auth/signup", json={}, headers=H).status_code in (404, 405)
    client.post("/api/v1/auth/login", json={"email": "admin@example.test", "password": PW}, headers=H)
    r = client.post("/api/v1/auth/admin/users", json={"email": "v@example.test", "display_name": "V", "role": "viewer"}, headers=H)
    temp = r.json()["data"]["temporary_password"]
    c2 = TestClient(client.app)
    c2.post("/api/v1/auth/login", json={"email": "v@example.test", "password": temp}, headers=H)
    assert c2.get("/api/v1/auth/admin/users").status_code == 403 or c2.get("/api/v1/auth/admin/users").status_code == 403


def test_deactivation_revokes_sessions_and_last_admin_is_protected(shared, client):
    make_admin(shared)
    client.post("/api/v1/auth/login", json={"email": "admin@example.test", "password": PW}, headers=H)
    aid = client.get("/api/v1/auth/me").json()["data"]["user_id"]
    assert client.post(f"/api/v1/auth/admin/users/{aid}/deactivate", headers=H).status_code == 409
    assert client.post(f"/api/v1/auth/admin/users/{aid}/role", json={"role": "viewer"}, headers=H).status_code == 409
    r = client.post("/api/v1/auth/admin/users", json={"email": "d@example.test", "display_name": "D", "role": "viewer"}, headers=H)
    uid, temp = r.json()["data"]["user_id"], r.json()["data"]["temporary_password"]
    c2 = TestClient(client.app)
    c2.post("/api/v1/auth/login", json={"email": "d@example.test", "password": temp}, headers=H)
    assert c2.get("/api/v1/auth/me").status_code == 200
    client.post(f"/api/v1/auth/admin/users/{uid}/deactivate", headers=H)
    assert c2.get("/api/v1/auth/me").status_code == 401


def test_logout_and_idle_expiry(shared, client):
    make_admin(shared)
    client.post("/api/v1/auth/login", json={"email": "admin@example.test", "password": PW}, headers=H)
    shared.execute("UPDATE app_session SET idle_expires_at = now() - interval '1 minute'")
    assert client.get("/api/v1/auth/me").status_code == 401
    client.post("/api/v1/auth/login", json={"email": "admin@example.test", "password": PW}, headers=H)
    assert client.post("/api/v1/auth/logout", headers=H).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_session_token_and_password_are_never_stored(shared, client):
    make_admin(shared)
    r = client.post("/api/v1/auth/login", json={"email": "admin@example.test", "password": PW}, headers=H)
    token = client.cookies.get("fpa_session")
    assert token and not shared.execute("SELECT 1 FROM app_session WHERE token_hash = %s", (token,)).fetchone()
    assert shared.execute("SELECT 1 FROM app_session WHERE token_hash = %s", (svc.token_hash(token),)).fetchone()
    assert not shared.execute("SELECT 1 FROM audit_event WHERE detail::text LIKE %s", (f"%{PW}%",)).fetchone()
    assert shared.execute("SELECT password_hash FROM app_user WHERE email = 'admin@example.test'").fetchone()["password_hash"].startswith("$argon2id$")


def test_foreign_origin_is_refused_on_writes(shared, client):
    make_admin(shared)
    r = client.post("/api/v1/auth/login", json={"email": "admin@example.test", "password": PW}, headers={**H, "Origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.post("/api/v1/auth/login", json={"email": "admin@example.test", "password": PW}, headers={**H, "Origin": "http://localhost:5180"})
    assert r.status_code == 200


def test_assignable_users_are_visible_to_any_signed_in_user_and_exclude_viewers(shared, client):
    make_admin(shared)
    client.post("/api/v1/auth/login", json={"email": "admin@example.test", "password": PW}, headers=H)
    client.post("/api/v1/auth/admin/users", json={"email": "v@example.test", "display_name": "V", "role": "viewer"}, headers=H)
    client.post("/api/v1/auth/admin/users", json={"email": "m@example.test", "display_name": "M", "role": "fpa_manager"}, headers=H)
    emails = {u["email"] for u in client.get("/api/v1/auth/assignable").json()["data"]}
    assert {"m@example.test", "admin@example.test"} <= emails and "v@example.test" not in emails
    assert TestClient(client.app).get("/api/v1/auth/assignable").status_code == 401


def _gate_app(client_app, token="tok-123"):
    from types import SimpleNamespace
    client_app.state.settings = SimpleNamespace(finance_token=token)

    def gate(request: Request) -> None:
        finance_gate(request)

    @client_app.get("/finance-only")
    def finance_only(_=Depends(gate)):
        return {"ok": True}
    return client_app


def test_finance_reads_accept_a_session_first_then_the_transitional_token_which_can_be_switched_off(shared, client, monkeypatch):
    make_admin(shared)
    app = _gate_app(client.app)
    anon = TestClient(app)
    before = dict(svc.READ_PATHS)
    assert anon.get("/finance-only").status_code == 401                                              # no session, no token
    assert anon.get("/finance-only", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert anon.get("/finance-only", headers={"Authorization": "Bearer tok-123"}).status_code == 200  # the transitional proxy token
    client.post("/api/v1/auth/login", json={"email": "admin@example.test", "password": PW}, headers=H)
    assert client.get("/finance-only").status_code == 200                                            # a named session
    monkeypatch.setenv("FPA_ALLOW_PROXY_TOKEN", "0")
    assert anon.get("/finance-only", headers={"Authorization": "Bearer tok-123"}).status_code == 401  # token retired
    assert client.get("/finance-only").status_code == 200                                            # the session still works
    after = svc.READ_PATHS
    assert after["proxy_token"] == before["proxy_token"] + 1 and after["session"] == before["session"] + 2 and after["refused"] >= before["refused"] + 3
    paths = client.get("/api/v1/auth/admin/read-paths").json()["data"]
    assert paths["proxy_token_allowed"] is False and paths["session"] >= 2
    assert "proxy_token" in paths["last_used"] and "session" in paths["last_used"] and "FPA_ALLOW_PROXY_TOKEN=1" in paths["rollback"]


def test_an_expired_session_is_not_a_way_in(shared, client, monkeypatch):
    make_admin(shared)
    app = _gate_app(client.app)
    client.post("/api/v1/auth/login", json={"email": "admin@example.test", "password": PW}, headers=H)
    monkeypatch.setenv("FPA_ALLOW_PROXY_TOKEN", "0")
    shared.execute("UPDATE app_session SET idle_expires_at = now() - interval '1 minute'")
    assert client.get("/finance-only").status_code == 401


def test_require_session_mode_refuses_every_data_route_without_a_session_and_lets_sign_in_through(shared, client, monkeypatch):
    from app.auth.middleware import RequireSession, _ok
    make_admin(shared)
    app = client.app

    @app.get("/api/v1/mgmt/anything")
    def data():
        return {"ok": True}
    wrapped = TestClient(RequireSession(app))
    monkeypatch.delenv("FPA_REQUIRE_SESSION", raising=False)
    assert wrapped.get("/api/v1/mgmt/anything").status_code == 200                              # off by default
    monkeypatch.setenv("FPA_REQUIRE_SESSION", "1")
    _ok.clear()
    assert wrapped.get("/api/v1/mgmt/anything").status_code == 401
    assert wrapped.post("/api/v1/auth/login", json={"email": "admin@example.test", "password": PW}, headers=H).status_code == 200      # sign-in itself is exempt
    assert wrapped.get("/api/v1/mgmt/anything").status_code == 200                              # the session cookie now opens the data route
    assert wrapped.get("/api/v1/auth/me").status_code == 200
    shared.execute("UPDATE app_session SET revoked_at = now()")
    _ok.clear()
    assert wrapped.get("/api/v1/mgmt/anything").status_code == 401
