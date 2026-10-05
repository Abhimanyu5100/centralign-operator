"""Shared web plumbing for Acme's routes: public paths, per-request connection, login guard, templates.

Kept apart from `app.py` so `ui.py` (and the part-4 API router) can import it without a circular import.
The actor comes only from the session cookie, never from request text (risk N.34).
"""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from acme import auth
from acme.db import connect
from acme.money import format_inr

PUBLIC_PATHS = {"/login", "/api/login", "/api/logout", "/healthz"}

# Every `error_type` an API response can carry. Stable from Day 1.4: the Day 2 failure classifier keys off
# these values (risk N.50, D-058). Documented in docs/acme-spec.md, "API".
ERROR_TYPES = (
    "invalid_request",           # malformed request: not JSON, bad query or path value, unknown route or method
    "invalid_input",             # a field value or business rule rejected the input (422)
    "not_found",                 # the entity does not exist (404)
    "forbidden",                 # role or ownership check failed (403)
    "conflict",                  # current state does not allow it: duplicate, wrong status (409)
    "idempotency_key_required",  # invoice/payment write without an Idempotency-Key header (400)
    "idempotency_key_reused",    # the same key with different data (409)
    "unsupported_media_type",    # a write with a body that is not application/json (415)
    "login_required",            # no session cookie (401)
    "session_expired",           # cookie unknown, revoked or past its expiry (401)
    "invalid_credentials",       # wrong username or password (401)
    "server_error",              # unexpected failure; the write was rolled back (500)
)


def api_error(status: int, error_type: str, detail: str, data: dict | None = None) -> JSONResponse:
    """The one typed error shape for /api/ (CLAUDE.md "Tool results are typed")."""
    if error_type not in ERROR_TYPES:
        raise ValueError(f"undeclared error_type {error_type!r}")  # fail loudly in tests, never ship a new name
    return JSONResponse({"ok": False, "error_type": error_type, "detail": detail, "data": data or {}},
                        status_code=status)

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.filters["inr"] = format_inr  # autoescape stays on; no template uses |safe (risk N.42)


class LoginRequired(Exception):
    def __init__(self, error_type: str):
        self.error_type = error_type  # "login_required" (no cookie) or "session_expired"


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


def require_login(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> str | None:
    """Returns the actor for this request (None on public paths). Runs once per request."""
    if request.url.path in PUBLIC_PATHS:
        return None
    check = auth.check_session(conn, request.cookies.get(auth.COOKIE_NAME), request.app.state.time_fn())
    if check.actor is None:
        raise LoginRequired(check.error_type)
    request.state.actor = check.actor  # lets error pages show the nav for the right user
    return check.actor


