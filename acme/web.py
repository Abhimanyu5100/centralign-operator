"""Shared web plumbing for Acme's routes: public paths, per-request connection, login guard, templates.

Kept apart from `app.py` so `ui.py` (and the part-4 API router) can import it without a circular import.
The actor comes only from the session cookie, never from request text (risk N.34).
"""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, Request
from fastapi.templating import Jinja2Templates

from acme import auth
from acme.db import connect
from acme.money import format_inr

PUBLIC_PATHS = {"/login", "/api/login", "/api/logout", "/healthz"}

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


