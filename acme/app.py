"""Acme's FastAPI app. Part 2 holds only login, logout, whoami, the login page and the home page;
the UI pages (part 3), the read/write API (part 4) and the admin endpoints (part 8) are added to this app.

Every route requires a login unless its path is in `PUBLIC_PATHS` (risk N.36). The check is an app-wide
dependency, so a route added later is protected without anyone remembering to ask. The actor comes only
from the session cookie, never from request text (risk N.34). UI and API share one login (D-037).
"""

import time
from collections.abc import Callable, Iterator
from pathlib import Path
from urllib.parse import quote

import sqlite3
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from acme import auth
from acme.db import connect
from acme.permissions import role_of

PUBLIC_PATHS = {"/login", "/api/login", "/api/logout", "/healthz"}

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


class LoginRequired(Exception):
    def __init__(self, error_type: str):
        self.error_type = error_type  # "login_required" (no cookie) or "session_expired"


def _error(status: int, error_type: str, detail: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error_type": error_type, "detail": detail}, status_code=status)


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
    return check.actor


def create_app(db_path: Path | str | None = None, time_fn: Callable[[], float] = time.time) -> FastAPI:
    app = FastAPI(title="Acme", dependencies=[Depends(require_login)])
    app.state.db_path = db_path  # None: resolved from ACME_DB / the default on every request
    app.state.time_fn = time_fn

    @app.exception_handler(LoginRequired)
    async def login_required(request: Request, exc: LoginRequired) -> Response:
        if request.url.path.startswith("/api/"):  # API clients get a typed 401, never an HTML redirect
            detail = "No session; POST /api/login first." if exc.error_type == "login_required" \
                else "Session expired or invalidated; log in again."
            return _error(401, exc.error_type, detail)
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)

    def _set_cookie(response: Response, token: str) -> None:
        # No `Secure` flag: Acme runs on plain http://localhost (accepted, register row 0.11).
        response.set_cookie(auth.COOKIE_NAME, token, max_age=auth.session_ttl_seconds(), path="/",
                            httponly=True, samesite="lax")

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.get("/login")
    def login_page(request: Request, next: str | None = None) -> Response:
        return templates.TemplateResponse(request, "login.html", {"next": auth.safe_next(next), "error": None})

    @app.post("/api/login")
    async def login(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
        """The one login for both channels: a JSON body (API) or a form post (the /login page)."""
        content_type = request.headers.get("content-type", "")
        is_form = content_type.startswith(("application/x-www-form-urlencoded", "multipart/form-data"))
        if is_form:
            fields = dict(await request.form())
        else:
            try:
                fields = await request.json()
            except ValueError:
                return _error(400, "invalid_request", "Body must be JSON or a form with username and password.")
            if not isinstance(fields, dict):
                return _error(400, "invalid_request", "Body must be a JSON object.")
        username, password = fields.get("username"), fields.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            return _error(400, "invalid_request", "username and password must be strings.")

        actor = auth.authenticate(username, password)
        if actor is None:
            if is_form:
                return templates.TemplateResponse(
                    request, "login.html",
                    {"next": auth.safe_next(fields.get("next")), "error": "Invalid username or password."},
                    status_code=401)
            return _error(401, "invalid_credentials", "Invalid username or password.")

        token = auth.create_session(conn, actor, request.app.state.time_fn())
        if is_form:
            response: Response = RedirectResponse(auth.safe_next(fields.get("next")), status_code=303)
        else:
            response = JSONResponse({"ok": True, "error_type": None, "detail": "logged in",
                                     "data": {"actor": actor, "role": role_of(actor),
                                              "expires_in": auth.session_ttl_seconds()}})
        _set_cookie(response, token)
        return response

    @app.post("/api/logout")
    def logout(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
        auth.revoke(conn, request.cookies.get(auth.COOKIE_NAME))
        response = JSONResponse({"ok": True, "error_type": None, "detail": "logged out", "data": {}})
        response.delete_cookie(auth.COOKIE_NAME, path="/")
        return response

    @app.get("/api/whoami")
    def whoami(actor: str = Depends(require_login)) -> dict:
        return {"ok": True, "error_type": None, "detail": "", "data": {"actor": actor, "role": role_of(actor)}}

    @app.get("/")
    def home(request: Request, actor: str = Depends(require_login)) -> Response:
        return templates.TemplateResponse(request, "home.html", {"actor": actor, "role": role_of(actor)})

    return app
