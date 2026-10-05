"""Acme login and cookie sessions (D-037, D-043; risks N.32 to N.37).

Credentials: users and roles are in `permissions.py`; passwords come from `ACME_PASSWORD_<USER>`
(e.g. `ACME_PASSWORD_OPS_AGENT`) with dev-only defaults. There is no users table.

Sessions: a random token in an HttpOnly cookie. The database holds only its SHA-256 hash, in the
`sessions` table, which is outside the state hash and is dropped by reset. Expiry is wall-clock time
(default 8 hours, so during runs only the chaos profile expires a session). Each session counts its
authenticated requests; `session_expiry_at_step_N` (part 9) revokes a session once it reaches N.
Time is passed in as a number so tests control it.
"""

import hashlib
import hmac
import os
import secrets
import sqlite3
from dataclasses import dataclass

from acme.permissions import LOGIN_USERS

COOKIE_NAME = "acme_session"
DEFAULT_TTL_SECONDS = 8 * 3600

# Dev-only defaults so a fresh clone runs; override in the environment. Sandbox only (README limitations).
DEV_PASSWORDS = {"ops-agent": "ops-agent-dev-pw", "meera": "meera-dev-pw", "admin": "admin-dev-pw"}
_DUMMY_PASSWORD = "not-a-real-user"  # compared when the username is unknown, so both failures look alike


def session_ttl_seconds() -> int:
    return int(os.environ.get("ACME_SESSION_TTL_SECONDS", DEFAULT_TTL_SECONDS))


def _password_for(username: str) -> str:
    env_name = "ACME_PASSWORD_" + username.upper().replace("-", "_")
    return os.environ.get(env_name) or DEV_PASSWORDS[username]


def authenticate(username: str, password: str) -> str | None:
    """Return the username if the credentials are valid, else None. Same cost either way."""
    known = username in LOGIN_USERS
    expected = _password_for(username) if known else _DUMMY_PASSWORD
    matches = hmac.compare_digest(password.encode(), expected.encode())
    return username if known and matches else None


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(conn: sqlite3.Connection, actor: str, now: float) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
    conn.execute(
        "INSERT INTO sessions (token_hash, actor, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (_hash(token), actor, now, now + session_ttl_seconds()),
    )
    return token


@dataclass(frozen=True)
class SessionCheck:
    actor: str | None
    error_type: str | None  # None when valid, else "login_required" or "session_expired"


def check_session(conn: sqlite3.Connection, token: str | None, now: float) -> SessionCheck:
    """Validate a cookie value and count the request, in one statement so two requests cannot race."""
    if not token:
        return SessionCheck(None, "login_required")
    row = conn.execute(
        "UPDATE sessions SET request_count = request_count + 1 "
        "WHERE token_hash = ? AND revoked = 0 AND expires_at > ? RETURNING actor",
        (_hash(token), now),
    ).fetchone()
    if row is None:  # unknown (e.g. wiped by reset), revoked or past its expiry
        return SessionCheck(None, "session_expired")
    return SessionCheck(row["actor"], None)


def revoke(conn: sqlite3.Connection, token: str | None) -> None:
    if token:
        conn.execute("UPDATE sessions SET revoked = 1 WHERE token_hash = ?", (_hash(token),))


def safe_next(value: str | None) -> str:
    """Only same-site relative paths; anything else becomes `/` (no open redirect, risk N.36)."""
    if not isinstance(value, str) or not value.startswith("/") or value.startswith("//"):
        return "/"
    return "/" if "\\" in value or "\n" in value else value
