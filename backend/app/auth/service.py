"""Identity on the app database: login, sessions, lockout, administrator-managed users. Every outcome is written to audit_event; passwords, hashes and raw
session tokens are never logged or audited. Policy (agreed with ChatGPT, step 1): lock for 15 minutes after 5 failures, session absolute expiry 10 hours and idle
expiry 45 minutes, a password change or deactivation revokes every session, an administrator reset sets must_change_password."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..appdb.conn import app_connection
from . import passwords as pw

MAX_FAILURES = 5
LOCK_MINUTES = 15
ABSOLUTE_HOURS = 10
IDLE_MINUTES = 45
ROLES = ("viewer", "fpa_manager", "finance_reviewer", "controller", "admin")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
GENERIC = "Invalid email or password."


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.message, self.status = message, status


@dataclass
class Actor:
    user_id: str
    email: str
    display_name: str
    role: str
    must_change_password: bool
    session_id: str | None = None

    def public(self) -> dict:
        return {"user_id": str(self.user_id), "email": self.email, "display_name": self.display_name, "role": self.role, "must_change_password": self.must_change_password}


READ_PATHS: dict[str, int] = {"session": 0, "proxy_token": 0, "refused": 0}


LAST_READ: dict[str, str] = {}


def note_read_path(path: str) -> None:
    """Counts how Finance reads were authorised since the API started, and when each path was last used, so the shared proxy token can be retired on evidence and the switch is
    safe to reverse (check that proxy_token was last used long ago before setting FPA_ALLOW_PROXY_TOKEN=0; to roll back set it to 1 and restart)."""
    READ_PATHS[path] = READ_PATHS.get(path, 0) + 1
    LAST_READ[path] = datetime.now(timezone.utc).isoformat()


def now() -> datetime:
    return datetime.now(timezone.utc)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def audit(conn, actor_email: str, action: str, object_type: str, object_id: str, detail: dict | None = None, actor_user_id=None, ip: str | None = None) -> None:
    conn.execute("INSERT INTO audit_event (actor_user_id, actor_email, action, object_type, object_id, detail, client_ip) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)",
                 (actor_user_id, actor_email, action, object_type, object_id, json.dumps(detail or {}, default=str), ip))


def login(email: str, password: str, ip: str | None = None) -> tuple[str, Actor]:
    """Returns (session token, actor). The token is shown once; only its hash is stored."""
    email = (email or "").strip().lower()
    with app_connection() as conn:
        u = conn.execute("SELECT * FROM app_user WHERE email = %s", (email,)).fetchone()
        if u is None:
            pw.verify_password(pw.DUMMY_HASH, password or "")
            audit(conn, email or "(blank)", "login_failed", "app_user", "(unknown)", {"reason": "unknown email"}, ip=ip)
            conn.commit()
            raise AuthError(GENERIC)
        if not u["active"]:
            pw.verify_password(pw.DUMMY_HASH, password or "")
            audit(conn, email, "login_failed", "app_user", str(u["user_id"]), {"reason": "inactive"}, u["user_id"], ip)
            conn.commit()
            raise AuthError(GENERIC)
        if u["locked_until"] and u["locked_until"] > now():
            audit(conn, email, "login_blocked", "app_user", str(u["user_id"]), {"reason": "locked"}, u["user_id"], ip)
            conn.commit()
            raise AuthError("This account is temporarily locked after repeated failures. Try again later or ask an administrator.", 423)
        if not pw.verify_password(u["password_hash"], password or ""):
            n = u["failed_attempts"] + 1
            lock = now() + timedelta(minutes=LOCK_MINUTES) if n >= MAX_FAILURES else None
            conn.execute("UPDATE app_user SET failed_attempts = %s, locked_until = %s, updated_at = now() WHERE user_id = %s", (0 if lock else n, lock, u["user_id"]))
            audit(conn, email, "login_locked" if lock else "login_failed", "app_user", str(u["user_id"]), {"failed_attempts": n}, u["user_id"], ip)
            conn.commit()
            raise AuthError(GENERIC)
        token = secrets.token_urlsafe(32)
        t = now()
        sid = conn.execute("INSERT INTO app_session (user_id, token_hash, expires_at, idle_expires_at, client_ip) VALUES (%s, %s, %s, %s, %s) RETURNING session_id",
                           (u["user_id"], token_hash(token), t + timedelta(hours=ABSOLUTE_HOURS), t + timedelta(minutes=IDLE_MINUTES), ip)).fetchone()["session_id"]
        new_hash = pw.hash_password(password) if pw.needs_rehash(u["password_hash"]) else u["password_hash"]
        conn.execute("UPDATE app_user SET failed_attempts = 0, locked_until = NULL, last_login_at = now(), password_hash = %s, updated_at = now() WHERE user_id = %s", (new_hash, u["user_id"]))
        audit(conn, email, "login_success", "app_user", str(u["user_id"]), {}, u["user_id"], ip)
        conn.commit()
        return token, Actor(str(u["user_id"]), u["email"], u["display_name"], u["role"], u["must_change_password"], str(sid))


def resolve(token: str | None) -> Actor | None:
    """The actor behind a session cookie, or None. Slides the idle expiry."""
    if not token:
        return None
    with app_connection() as conn:
        r = conn.execute("""SELECT s.session_id, s.expires_at, s.idle_expires_at, s.revoked_at, u.user_id, u.email, u.display_name, u.role, u.active, u.must_change_password
                            FROM app_session s JOIN app_user u USING (user_id) WHERE s.token_hash = %s""", (token_hash(token),)).fetchone()
        t = now()
        if r is None or r["revoked_at"] or not r["active"] or r["expires_at"] <= t or (r["idle_expires_at"] and r["idle_expires_at"] <= t):
            return None
        conn.execute("UPDATE app_session SET last_seen_at = %s, idle_expires_at = %s WHERE session_id = %s", (t, min(r["expires_at"], t + timedelta(minutes=IDLE_MINUTES)), r["session_id"]))
        conn.commit()
        return Actor(str(r["user_id"]), r["email"], r["display_name"], r["role"], r["must_change_password"], str(r["session_id"]))


def logout(actor: Actor, ip: str | None = None) -> None:
    with app_connection() as conn:
        conn.execute("UPDATE app_session SET revoked_at = now() WHERE session_id = %s AND revoked_at IS NULL", (actor.session_id,))
        audit(conn, actor.email, "logout", "app_session", str(actor.session_id), {}, actor.user_id, ip)
        conn.commit()


def _revoke_all(conn, user_id) -> int:
    return conn.execute("UPDATE app_session SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL", (user_id,)).rowcount


def change_password(actor: Actor, current: str, new: str, ip: str | None = None) -> None:
    with app_connection() as conn:
        u = conn.execute("SELECT * FROM app_user WHERE user_id = %s", (actor.user_id,)).fetchone()
        if not pw.verify_password(u["password_hash"], current or ""):
            audit(conn, actor.email, "password_change_failed", "app_user", actor.user_id, {}, actor.user_id, ip)
            conn.commit()
            raise AuthError("The current password is not correct.", 400)
        why = pw.check_policy(new or "", u["email"])
        if why:
            raise AuthError(why, 400)
        if pw.verify_password(u["password_hash"], new):
            raise AuthError("The new password must differ from the current one.", 400)
        conn.execute("UPDATE app_user SET password_hash = %s, must_change_password = false, password_changed_at = now(), updated_at = now() WHERE user_id = %s", (pw.hash_password(new), actor.user_id))
        n = _revoke_all(conn, actor.user_id)
        audit(conn, actor.email, "password_changed", "app_user", actor.user_id, {"sessions_revoked": n}, actor.user_id, ip)
        conn.commit()


def _need_admin(actor: Actor) -> None:
    if actor.role != "admin":
        raise AuthError("Only an administrator can manage users.", 403)


def create_user(actor: Actor, email: str, display_name: str, role: str, ip: str | None = None) -> dict:
    """Administrator only. Returns the temporary password once; the user must change it at first login."""
    _need_admin(actor)
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise AuthError("Enter a valid email address.", 400)
    if role not in ROLES:
        raise AuthError("Unknown role.", 400)
    if not (display_name or "").strip():
        raise AuthError("Enter the name of the person.", 400)
    temp = pw.temporary_password()
    with app_connection() as conn:
        if conn.execute("SELECT 1 FROM app_user WHERE email = %s", (email,)).fetchone():
            raise AuthError("A user with this email already exists.", 409)
        uid = conn.execute("INSERT INTO app_user (email, display_name, role, password_hash, must_change_password, created_by) VALUES (%s, %s, %s, %s, true, %s) RETURNING user_id",
                           (email, display_name.strip(), role, pw.hash_password(temp), actor.user_id)).fetchone()["user_id"]
        audit(conn, actor.email, "user_created", "app_user", str(uid), {"email": email, "role": role}, actor.user_id, ip)
        conn.commit()
    return {"user_id": str(uid), "email": email, "role": role, "temporary_password": temp}


def list_users(actor: Actor) -> list[dict]:
    _need_admin(actor)
    with app_connection() as conn:
        rows = conn.execute("SELECT user_id, email, display_name, role, active, must_change_password, locked_until, last_login_at, created_at FROM app_user ORDER BY email").fetchall()
    return [{**r, "user_id": str(r["user_id"])} for r in rows]


def assignable_users(actor: Actor) -> list[dict]:
    """Active users who can own an exception (anyone signed in may see this short list: name and email only)."""
    with app_connection() as conn:
        rows = conn.execute("SELECT user_id, email, display_name, role FROM app_user WHERE active AND role <> 'viewer' ORDER BY display_name").fetchall()
    return [{**r, "user_id": str(r["user_id"])} for r in rows]


def set_role(actor: Actor, user_id: str, role: str, ip: str | None = None) -> None:
    _need_admin(actor)
    if role not in ROLES:
        raise AuthError("Unknown role.", 400)
    with app_connection() as conn:
        u = conn.execute("SELECT email, role FROM app_user WHERE user_id = %s", (user_id,)).fetchone()
        if not u:
            raise AuthError("No such user.", 404)
        if u["role"] == "admin" and role != "admin" and conn.execute("SELECT count(*) AS n FROM app_user WHERE role = 'admin' AND active").fetchone()["n"] <= 1:
            raise AuthError("The last active administrator cannot lose the role.", 409)
        conn.execute("UPDATE app_user SET role = %s, updated_at = now() WHERE user_id = %s", (role, user_id))
        n = _revoke_all(conn, user_id)
        audit(conn, actor.email, "role_changed", "app_user", user_id, {"from": u["role"], "to": role, "sessions_revoked": n}, actor.user_id, ip)
        conn.commit()


def set_active(actor: Actor, user_id: str, active: bool, ip: str | None = None) -> None:
    _need_admin(actor)
    with app_connection() as conn:
        u = conn.execute("SELECT email, role, active FROM app_user WHERE user_id = %s", (user_id,)).fetchone()
        if not u:
            raise AuthError("No such user.", 404)
        if not active and u["role"] == "admin" and conn.execute("SELECT count(*) AS n FROM app_user WHERE role = 'admin' AND active").fetchone()["n"] <= 1:
            raise AuthError("The last active administrator cannot be deactivated.", 409)
        conn.execute("UPDATE app_user SET active = %s, updated_at = now() WHERE user_id = %s", (active, user_id))
        n = _revoke_all(conn, user_id) if not active else 0
        audit(conn, actor.email, "user_activated" if active else "user_deactivated", "app_user", user_id, {"sessions_revoked": n}, actor.user_id, ip)
        conn.commit()


def reset_password(actor: Actor, user_id: str, ip: str | None = None) -> dict:
    _need_admin(actor)
    temp = pw.temporary_password()
    with app_connection() as conn:
        u = conn.execute("SELECT email FROM app_user WHERE user_id = %s", (user_id,)).fetchone()
        if not u:
            raise AuthError("No such user.", 404)
        conn.execute("UPDATE app_user SET password_hash = %s, must_change_password = true, password_changed_at = now(), failed_attempts = 0, locked_until = NULL, updated_at = now() WHERE user_id = %s",
                     (pw.hash_password(temp), user_id))
        n = _revoke_all(conn, user_id)
        audit(conn, actor.email, "password_reset", "app_user", user_id, {"sessions_revoked": n}, actor.user_id, ip)
        conn.commit()
    return {"user_id": user_id, "email": u["email"], "temporary_password": temp}


def unlock(actor: Actor, user_id: str, ip: str | None = None) -> None:
    _need_admin(actor)
    with app_connection() as conn:
        if conn.execute("UPDATE app_user SET failed_attempts = 0, locked_until = NULL, updated_at = now() WHERE user_id = %s", (user_id,)).rowcount == 0:
            raise AuthError("No such user.", 404)
        audit(conn, actor.email, "user_unlocked", "app_user", user_id, {}, actor.user_id, ip)
        conn.commit()


def bootstrap_admin(email: str, display_name: str, password: str) -> str:
    """One-time creation of the first administrator by the owner at the console. Refused when any administrator exists. No default password."""
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise AuthError("Enter a valid email address.", 400)
    why = pw.check_policy(password, email)
    if why:
        raise AuthError(why, 400)
    with app_connection() as conn:
        if conn.execute("SELECT 1 FROM app_user WHERE role = 'admin'").fetchone():
            raise AuthError("An administrator already exists; ask them to create users.", 409)
        uid = conn.execute("INSERT INTO app_user (email, display_name, role, password_hash, must_change_password) VALUES (%s, %s, 'admin', %s, false) RETURNING user_id",
                           (email, display_name.strip(), pw.hash_password(password))).fetchone()["user_id"]
        audit(conn, email, "admin_bootstrapped", "app_user", str(uid), {}, uid)
        conn.commit()
    return str(uid)
