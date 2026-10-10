"""Password hashing (argon2id) and the password policy."""
from __future__ import annotations

import secrets
import string

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_ph = PasswordHasher()
MIN_LENGTH = 12
# verifying against this keeps the response time the same for an unknown email
DUMMY_HASH = _ph.hash("not-a-real-password-" + secrets.token_hex(8))


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _ph.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    return _ph.check_needs_rehash(stored_hash)


def check_policy(password: str, email: str = "") -> str | None:
    """None when acceptable, otherwise the reason."""
    if len(password) < MIN_LENGTH:
        return f"The password must have at least {MIN_LENGTH} characters."
    local = email.split("@")[0].lower()
    if len(local) >= 4 and local in password.lower():
        return "The password must not contain the email name."
    if len(set(password)) < 5:
        return "The password is too repetitive."
    return None


def temporary_password() -> str:
    a = string.ascii_letters + string.digits
    return "".join(secrets.choice(a) for _ in range(16))
