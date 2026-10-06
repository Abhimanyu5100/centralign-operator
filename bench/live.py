"""Harness side of a live run: an Acme server to talk to, the admin calls the harness makes, and one oracle run
(reset -> chaos -> snapshot -> scripted agent -> diff -> checker). Used by `make oracle` and the e2e tests.

`serve()` starts Acme in-process on a temporary database (a thread running uvicorn on a free localhost port), with
a random admin token and a random ops-agent password set for that server only, so `make oracle` needs no exported
token and never touches the author's dev database (N.136). `live()` targets an already running `make acme` instead.
The agent gets an explicit config (URL, its own password, timeout) and never the admin token (N.30, N.92).
Harness side only: agent/ never imports bench/ (decision 11).
"""

import os
import secrets
import socket
import tempfile
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import uvicorn

from acme import auth
from acme.app import create_app
from acme.db import connect, db_path as default_db_path
from acme.seed import reset
from agent.config import load_config
from agent.lifecycle import Run as AgentRun, start_run
from agent.scripted import ScriptResult, run_script
from agent.store import RunStore
from bench.checkers import engine
from bench.oracles import Oracle
from bench.tasks import Run, Task

ADMIN_HEADER = "X-Admin-Token"


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
def _env(values: Mapping[str, str]) -> Iterator[None]:
    saved = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def serve(db_path: Path | None = None, env: Mapping[str, str] | None = None) -> Iterator[Acme]:
    """Acme on a free localhost port, backed by `db_path` (a temporary file by default)."""
    token, password = secrets.token_hex(16), secrets.token_hex(16)
    with tempfile.TemporaryDirectory() as tmp, _env({"ACME_ADMIN_TOKEN": token, "ACME_PASSWORD_OPS_AGENT": password,
                                                      **(env or {})}):
        path = Path(db_path or Path(tmp) / "acme.db")
        conn = connect(path)
        reset(conn, "base")
        conn.close()
        port = _free_port()
        server = uvicorn.Server(uvicorn.Config(create_app(path), host="127.0.0.1", port=port, log_level="warning",
                                               lifespan="off", timeout_graceful_shutdown=1))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started:
            if time.monotonic() > deadline or not thread.is_alive():
                raise RuntimeError("Acme did not start")
            time.sleep(0.02)
        try:
            yield Acme(f"http://127.0.0.1:{port}", path, token, password)
        finally:
            server.should_exit = True
            thread.join(10)


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
    pending: list[str] = field(default_factory=list)  # what only the Day 3 report or gate can show
    chaos_fired: bool | None = None

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
                                config=acme.agent_config(timeout))
    try:
        script = await run_script(agent, oracle.steps)
    finally:
        await agent.close()
    diff = acme.admin("GET", "/__admin/diff", since=snapshot)["tables"]
    result = engine.check(run.model_copy(update={"report_checks": []}), acme.db_path, diff)
    pending = [f"report: status == {run.expected_outcome}"] + [f"report: {rc.path}" for rc in run.report_checks]
    pending += [oracle.pending] if oracle.pending else []
    fired = acme.admin("GET", "/__admin/chaos/events")["fired"] if chaos else None
    return OracleRun(run, agent.run_id, script, result, pending, fired)
