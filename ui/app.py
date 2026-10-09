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

Run viewer (Day 6): `/runs` lists the store's runs, newest first, with the status from each run's report;
`/runs/<id>` shows one run: its request, the verifier's status and reasons, the timeline (every event with a
one-line summary and its full payload), and the report (runs/<id>/report.md). Read-only; every value is escaped by
Jinja's autoescape, because tool results hold untrusted email and PDF text (register 4.7). `RUN_STORE` picks
another store file, e.g. `RUN_STORE=runs/bench.db make ui` for the bench's runs.
"""

import hmac
import json
import os
import re
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field

from agent.policy.approvals import ApprovalError, ApprovalStore
from agent.store import DEFAULT_PATH, RunStore

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")  # autoescape on for .html
DECISIONS = {"approve": "approved", "reject": "rejected"}
RUN_ID = re.compile(r"[0-9a-f]{16}")


def summarize(type_: str, p: dict) -> str:
    """One line per event for the timeline; the full payload sits beside it. An older or odd payload shape falls back
    to the raw JSON rather than breaking the page."""
    try:
        return _summary(type_, p)
    except (AttributeError, KeyError, TypeError):
        return json.dumps(p, ensure_ascii=False)[:200]


def _summary(type_: str, p: dict) -> str:
    match type_:
        case "tool_call":
            return f"{p.get('tool')} {json.dumps(p.get('args', {}), ensure_ascii=False)[:160]} ({p.get('side_effect')})"
        case "tool_result":
            return f"{'ok' if p.get('ok') else 'FAILED ' + str(p.get('error_type'))}: {str(p.get('detail', ''))[:160]}"
        case "policy_decision":
            return f"{p.get('effect')} {p.get('tool')} {', '.join(p.get('policy_ids') or [])}: {p.get('reason', '')}"
        case "approval":
            return f"{p.get('action')} {p.get('approval_id')} {', '.join(p.get('policy_ids') or [])}"
        case "llm_call":
            return f"{p.get('role')} {p.get('model')} {p.get('total_tokens', 0)} tokens ({p.get('source')})"
        case "goal":
            return f"{p.get('decision')}: {p.get('reason', '')[:160]}"
        case "plan":
            return f"attempt {p.get('attempt')}: " + "; ".join(
                f"{m['id']} {m.get('target', '')[:80]}" for m in p.get("plan", {}).get("milestones", []))
        case "verifier_result":
            return f"{p.get('status', '')} " + ", ".join(
                f"{m['id']} {'met' if m.get('ok') else 'NOT met'}" for m in p.get("milestones", []))
        case "prediction":
            return str(p.get("effect", ""))
        case "security_finding":
            return f"{p.get('policy_id')} {p.get('kind')} in {p.get('origin')}: {p.get('excerpt', '')}"
        case "agent_message":
            return str(p.get("text", ""))[:200]
        case "precondition":
            return f"{'ok' if p.get('ok') else 'FAILED'}: {p.get('check')}"
    return json.dumps(p, ensure_ascii=False)[:200]


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str
    by: str = Field(default="approver", min_length=1, max_length=60)
    note: str = Field(default="", max_length=500)


def create_app(store_path: Path | str | None = None, token: str | None = None) -> FastAPI:
    store_path = Path(store_path or os.environ.get("RUN_STORE") or DEFAULT_PATH).resolve()
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

    def read_store() -> sqlite3.Connection:  # read-only: the viewer never writes the run store
        return sqlite3.connect(f"file:{store_path}?mode=ro", uri=True)

    def report(run_id: str) -> tuple[dict, str]:
        folder = store_path.parent / run_id
        data = json.loads((folder / "report.json").read_text()) if (folder / "report.json").is_file() else {}
        text = (folder / "report.md").read_text() if (folder / "report.md").is_file() else ""
        return data, text

    @app.get("/runs", response_class=HTMLResponse)
    def runs(request: Request, limit: int = 100) -> HTMLResponse:
        if not store_path.is_file():
            rows = []
        else:
            with read_store() as db:
                rows = db.execute("SELECT run_id, request, now FROM runs ORDER BY rowid DESC LIMIT ?",
                                  (max(1, min(limit, 1000)),)).fetchall()
        items = [{"run_id": r, "request": q, "now": n, "status": report(r)[0].get("status", "no report")}
                 for r, q, n in rows]
        return TEMPLATES.TemplateResponse(request, "runs.html", {"runs": items, "store": store_path.name})

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run(request: Request, run_id: str) -> HTMLResponse:
        if not RUN_ID.fullmatch(run_id) or not store_path.is_file():
            raise HTTPException(404, "no such run")
        with read_store() as db:
            head = db.execute("SELECT request, now FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            events = db.execute("SELECT seq, type, payload FROM events WHERE run_id = ? ORDER BY seq",
                                (run_id,)).fetchall()
        if head is None:
            raise HTTPException(404, "no such run")
        data, text = report(run_id)
        timeline = [{"seq": seq, "type": t, "summary": summarize(t, json.loads(body)),
                     "payload": json.dumps(json.loads(body), indent=1, ensure_ascii=False)} for seq, t, body in events]
        return TEMPLATES.TemplateResponse(request, "run.html", {
            "run_id": run_id, "asked": head[0], "now": head[1], "report": data, "report_md": text,
            "timeline": timeline, "types": sorted({e["type"] for e in timeline})})

    return app
