"""Acme's FastAPI app: login, logout, whoami and the UI pages (`acme/ui.py`, part 3). The read/write API
(part 4) and the admin endpoints (part 8) are added to this app.

Every route requires a login unless its path is in `PUBLIC_PATHS` (risk N.36). The check is an app-wide
dependency, so a route added later is protected without anyone remembering to ask. The actor comes only
from the session cookie, never from request text (risk N.34). UI and API share one login (D-037).
"""

import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response

from acme import auth, ui
from acme.permissions import role_of
from acme.services import AcmeError
from acme.web import PUBLIC_PATHS, LoginRequired, get_conn, require_login, templates

__all__ = ["PUBLIC_PATHS", "create_app", "require_login"]


def _error(status: int, error_type: str, detail: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error_type": error_type, "detail": detail}, status_code=status)


def create_app(db_path: Path | str | None = None, time_fn: Callable[[], float] = time.time) -> FastAPI:
    app = FastAPI(title="Acme", dependencies=[Depends(require_login)])
    app.include_router(ui.router)
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

    @app.exception_handler(AcmeError)
    async def acme_error(request: Request, exc: AcmeError) -> Response:
        """One mapping from service errors to responses: typed JSON for /api/, an error page for the UI."""
        if request.url.path.startswith("/api/"):
            return _error(exc.status_code, type(exc).__name__.lower(), exc.message)
        return ui.error_page(request, exc)

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc: RequestValidationError) -> Response:
        """A malformed path or query value (e.g. /invoices/abc): typed JSON for /api/, an error page for the UI."""
        message = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        if request.url.path.startswith("/api/"):
            return _error(422, "invalid_request", message)
        return ui.error_page(request, status=422, message=f"Invalid request: {message}")

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

    return app
