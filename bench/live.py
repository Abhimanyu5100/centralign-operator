"""Harness side of a live run: an Acme server to talk to, the admin calls the harness makes, and one oracle run
(reset -> chaos -> snapshot -> scripted agent -> diff -> checker). Used by `make oracle` and the e2e tests.

`serve()` starts Acme as a child process (uvicorn on a free localhost port) on a temporary database, with a random
admin token and a random ops-agent password in that child's env only: the harness process, the agent in it and the
Playwright driver it starts never hold the token (N.92, D-105), `make oracle` needs no exported token and never
touches the author's dev database (N.136). `live()` targets an already running `make acme` instead. The agent gets
an explicit config (URL, its own password, timeout) and never the admin token (N.30).
A run that the policy gate pauses for an action approval is decided by the scripted approver (bench/approver.py,
the task's `approver`: none / approve / reject) through the approval inbox, then resumed (Day 3.1).
Harness side only: agent/ never imports bench/ (decision 11).
"""

import asyncio
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from acme import auth
from acme.db import connect, db_path as default_db_path
from acme.seed import reset
from agent.config import load_config
from agent.lifecycle import Run as AgentRun, start_run
from agent.scripted import ScriptResult, resume_script, run_script
from agent.store import RunStore
from bench.approver import decide
from bench.checkers import engine
from bench.oracles import Oracle
from bench.tasks import Run, Task

ADMIN_HEADER = "X-Admin-Token"
ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Acme:
    url: str
    db_path: Path
    admin_token: str
    agent_password: str

    def admin(self, method: str, path: str, **params: Any) -> dict[str, Any]:
        response = httpx.request(method, self.url + path, params=params, headers={ADMIN_HEADER: self.admin_token},
                                 timeout=30)
        body = response.json()
        if not body.get("ok"):
            raise RuntimeError(f"{method} {path}: {body.get('error_type')}: {body.get('detail')}")
        return body["data"]

    def agent_config(self, timeout: float | None = None) -> dict[str, str]:
        config = {**load_config(), "ACME_URL": self.url, "ACME_PASSWORD_OPS_AGENT": self.agent_password}
        if timeout is not None:
            config["ACME_HTTP_TIMEOUT_SECONDS"] = str(timeout)
        return config


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def serve(db_path: Path | None = None, env: Mapping[str, str] | None = None) -> Iterator[Acme]:
    """Acme on a free localhost port, backed by `db_path` (a temporary file by default)."""
    token, password = secrets.token_hex(16), secrets.token_hex(16)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(db_path or Path(tmp) / "acme.db")
        conn = connect(path)
        reset(conn, "base")
        conn.close()
        port = _free_port()
        child_env = {**os.environ, "ACME_DB": str(path), "ACME_ADMIN_TOKEN": token,
                     "ACME_PASSWORD_OPS_AGENT": password, **(env or {})}
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "--factory", "acme.app:create_app", "--host", "127.0.0.1",
             "--port", str(port), "--log-level", "warning", "--timeout-graceful-shutdown", "1"],
            env=child_env, cwd=ROOT)
        url = f"http://127.0.0.1:{port}"
        try:
            _wait_until_up(url, server)
            yield Acme(url, path, token, password)
        finally:
            server.terminate()
            try:
                server.wait(10)
            except subprocess.TimeoutExpired:
                server.kill()


def _wait_until_up(url: str, server: subprocess.Popen) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError(f"Acme exited with code {server.returncode}")
        try:
            if httpx.get(url + "/healthz", timeout=1).status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.05)
    raise RuntimeError("Acme did not start within 15 s")


def live() -> Acme:
    """The running `make acme` server: ACME_URL, ACME_ADMIN_TOKEN and ACME_DB from the harness environment."""
    token = os.environ.get("ACME_ADMIN_TOKEN", "")
    if not token:
        raise SystemExit("LIVE=1 needs ACME_ADMIN_TOKEN exported, the same value `make acme` was started with")
    url = os.environ.get("ACME_URL") or load_config().get("ACME_URL", "http://localhost:8000")
    return Acme(url.rstrip("/"), default_db_path(), token, auth._password_for("ops-agent"))


@dataclass
class OracleRun:
    run: Run
    agent_run_id: str
    script: ScriptResult
    result: engine.Result
    pending: list[str] = field(default_factory=list)  # what only the Day 3.3 report can show
    chaos_fired: bool | None = None
    decisions: list[dict[str, Any]] = field(default_factory=list)  # what the scripted approver decided

    @property
    def passed(self) -> bool:
        return self.script.ok and self.result.passed


async def run_oracle(acme: Acme, task: Task, run: Run, oracle: Oracle, *, chaos: str | None = None,
                     chaos_seed: int = 0, store: RunStore | None = None, timeout: float | None = None) -> OracleRun:
    acme.admin("POST", "/__admin/reset", seed=task.seed, now=task.now)
    if chaos:
        acme.admin("POST", "/__admin/chaos", profile=chaos, seed=chaos_seed)  # after reset: reset clears it
    snapshot = acme.admin("POST", "/__admin/snapshot")["snapshot"]
    agent: AgentRun = start_run(task.request, datetime.fromisoformat(task.now), store=store,
                                config=acme.agent_config(timeout), plan=oracle.plan)
    decisions: list[dict[str, Any]] = []
    try:
        script = await run_script(agent, oracle.steps)
        if script.ended == "paused":  # the approver decides in the inbox, then the run resumes
            decisions = await asyncio.to_thread(decide, agent.ctx.store.path, agent.run_id, run.approver)
            script = await resume_script(agent, oracle.steps, script)
    finally:
        await agent.close()
    diff = acme.admin("GET", "/__admin/diff", since=snapshot)["tables"]
    result = engine.check(run.model_copy(update={"report_checks": []}), acme.db_path, diff)
    pending = [f"report: status == {run.expected_outcome}"] + [f"report: {rc.path}" for rc in run.report_checks]
    pending += [oracle.pending] if oracle.pending else []
    fired = acme.admin("GET", "/__admin/chaos/events")["fired"] if chaos else None
    return OracleRun(run, agent.run_id, script, result, pending, fired, decisions)
