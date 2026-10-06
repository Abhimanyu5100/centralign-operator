"""Shared web plumbing for Acme's routes: public paths, per-request connection, login guard, templates.

The admin routes (`/__admin/*`, part 8) are guarded here too, by a token instead of a session (risk N.91).

Kept apart from `app.py` so `ui.py` (and the part-4 API router) can import it without a circular import.
The actor comes only from the session cookie, never from request text (risk N.34).
"""

import hmac
import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, Request
from fastapi.responses import JSONResponse, Response
from fastapi.templating import Jinja2Templates

from acme import auth, chaos, files
from acme.db import connect
from acme.money import format_inr
from acme.services import Forbidden, NotFound

PUBLIC_PATHS = {"/login", "/api/login", "/api/logout", "/healthz"}
ADMIN_PREFIX = "/__admin"
ADMIN_TOKEN_HEADER = "X-Admin-Token"


def is_admin_path(path: str) -> bool:
    return path == ADMIN_PREFIX or path.startswith(ADMIN_PREFIX + "/")


def is_json_path(path: str) -> bool:
    """Paths whose errors are typed JSON: the API and the admin endpoints."""
    return path.startswith("/api/") or is_admin_path(path)


def check_admin_token(request: Request) -> None:
    """Admin routes need `X-Admin-Token` equal to the ACME_ADMIN_TOKEN environment variable, never a session.
    An unset or empty variable closes every admin route (compare_digest("", "") would be true, risk N.90)."""
    expected = os.environ.get("ACME_ADMIN_TOKEN", "")
    supplied = request.headers.get(ADMIN_TOKEN_HEADER, "")
    if not expected or not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        raise Forbidden(f"Admin endpoints need a valid {ADMIN_TOKEN_HEADER} header")

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
    """Returns the actor for this request (None on public and admin paths). Runs once per request.
    Everything under /__admin is token-only: a valid session without the token is still 403 (N.91).
    Admin and public paths return before any session count or chaos hook (N.104)."""
    if is_admin_path(request.url.path):
        check_admin_token(request)
        return None
    if request.url.path in PUBLIC_PATHS:
        return None
    token = request.cookies.get(auth.COOKIE_NAME)
    check = auth.check_session(conn, token, request.app.state.time_fn())
    if check.actor is None:
        raise LoginRequired(check.error_type)
    limit = chaos.session_step_limit(conn, check.actor)
    if limit is not None and check.request_count > limit:  # chaos: request N+1 finds the session gone
        auth.revoke(conn, token)
        chaos.record_session_expiry(conn, check.actor, request.method, request.url.path, check.request_count)
        raise LoginRequired("session_expired")
    request.state.actor = check.actor  # lets error pages show the nav for the right user
    return check.actor




def pdf_response(name: str) -> Response:
    """A generated PDF as a download. Invalid and missing names get the same 404 (risk N.67)."""
    data = files.read(name)
    if data is None:
        raise NotFound("File not found")
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff"})
