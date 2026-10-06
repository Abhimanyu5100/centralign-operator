"""Action-approval inbox (Day 3.1; register P.4, P.5, N.150).

When the policy gate holds a call (ORG-005 external mail, ORG-007, ORG-008, ORG-009), the registry files it in the
approval store with its predicted outcome and the run pauses. A human decides here: the page lists every pending
approval as a card (the run's request, the tool, the HTTP request, the arguments, the side effect, the rules that
held it and why) with Approve and Reject buttons. A JSON twin serves the bench's scripted approver, which drives
the same app through Starlette's TestClient, so the bench and a person use the same endpoints.

Safety: it listens on 127.0.0.1 only (`make ui`). Every decision needs this process's form token (a CSRF guard):
the token is in the page and in the JSON listing, which another site cannot read. No agent tool reaches this
server: the API client talks only to ACME_URL and the browser tool stays on Acme's origin (N.145). Deciding twice
is refused, and the first decision wins in the store anyway. The store is opened per request (an SQLite
connection belongs to one thread).
"""

import hmac
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field

from agent.policy.approvals import ApprovalError, ApprovalStore
from agent.store import DEFAULT_PATH, RunStore

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")  # autoescape on for .html
DECISIONS = {"approve": "approved", "reject": "rejected"}


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str
    by: str = Field(default="approver", min_length=1, max_length=60)
    note: str = Field(default="", max_length=500)


def create_app(store_path: Path | str = DEFAULT_PATH, token: str | None = None) -> FastAPI:
    app = FastAPI(title="Operator approval inbox", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.token = token or secrets.token_urlsafe(24)

    @contextmanager
    def approvals() -> Iterator[ApprovalStore]:
        store = RunStore(store_path)
        try:
            yield ApprovalStore(store)
        finally:
            store.close()

    def cards(status: str | None) -> list[dict]:
        with approvals() as inbox:
            items = [a for a in inbox.all() if status in (None, a.status)]
            requests = {a.run_id: inbox.store.run(a.run_id)["request"] for a in items}
        return [{**a.model_dump(), "request": requests[a.run_id]} for a in reversed(items)]

    def decide(approval_id: str, action: str, given: DecisionIn) -> tuple[int, dict]:
        if not hmac.compare_digest(given.token.encode(), app.state.token.encode()):
            return 403, {"ok": False, "error_type": "forbidden", "detail": "missing or wrong form token", "data": {}}
        if action not in DECISIONS:
            return 404, {"ok": False, "error_type": "not_found", "detail": f"no action {action!r}", "data": {}}
        with approvals() as inbox:
            try:
                approval = inbox.decide(approval_id, DECISIONS[action], by=given.by, note=given.note)
            except ApprovalError as exc:
                status = 404 if "no approval" in str(exc) else 409
                return status, {"ok": False, "error_type": "not_found" if status == 404 else "conflict",
                                "detail": str(exc), "data": {}}
        return 200, {"ok": True, "error_type": None, "detail": f"{approval_id} {approval.status}",
                     "data": approval.model_dump()}

    @app.get("/", response_class=HTMLResponse)
    def inbox(request: Request, done: str = "") -> HTMLResponse:
        all_cards = cards(None)
        return TEMPLATES.TemplateResponse(request, "inbox.html", {
            "pending": [c for c in all_cards if c["status"] == "pending"],
            "decided": [c for c in all_cards if c["status"] != "pending"][:20],
            "token": app.state.token, "done": done})

    @app.post("/approvals/{approval_id}/{action}", response_model=None)
    def decide_form(approval_id: str, action: Literal["approve", "reject"], token: str = Form(""),
                    by: str = Form("approver"), note: str = Form("")) -> RedirectResponse | JSONResponse:
        status, body = decide(approval_id, action, DecisionIn(token=token, by=by or "approver", note=note))
        if status != 200:
            return JSONResponse(body, status_code=status)
        return RedirectResponse(f"/?done={body['detail']}", status_code=303)

    @app.get("/api/approvals")
    def list_approvals(status: Literal["pending", "approved", "rejected"] | None = None) -> dict:
        return {"ok": True, "error_type": None, "detail": "", "data": {"items": cards(status),
                                                                       "token": app.state.token}}

    @app.post("/api/approvals/{approval_id}/{action}")
    def decide_json(approval_id: str, action: Literal["approve", "reject"], given: DecisionIn) -> JSONResponse:
        status, body = decide(approval_id, action, given)
        return JSONResponse(body, status_code=status)

    return app
