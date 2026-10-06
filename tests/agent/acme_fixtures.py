"""Fixtures for agent tests against a real Acme app in-process (httpx ASGITransport, no server, no network).

`Faults` wraps the transport: it records every request and can make one request fail the way a network does,
either before Acme sees it (nothing written) or after Acme answered (committed, but the client hears a timeout).
That is `commit_then_timeout` without waiting for a real timeout; the e2e tests use the real chaos profile.
"""

import asyncio
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
import pytest
from fastapi.testclient import TestClient

from acme.app import create_app
from acme.db import connect
from acme.seed import reset
from agent.lifecycle import Run, start_run
from agent.plan import Plan
from agent.store import RunStore
from tests.agent.agent_fixtures import NOW, AllowAllGate

ADMIN = {"X-Admin-Token": "test-admin-token"}
PASSWORD = "test-agent-password"
CONFIG = {"ACME_URL": "http://acme.test", "ACME_PASSWORD_OPS_AGENT": PASSWORD, "ACME_HTTP_TIMEOUT_SECONDS": "5",
          "READ_LAG_SECONDS": "0.3"}  # short: these Acme apps have no read lag unless a test turns delayed_write on


@dataclass
class Fault:
    method: str
    path: str
    when: str               # "before": Acme never sees it; "after": Acme committed, the client hears a timeout
    nth: int = 1            # fail the nth matching request
    error: type[Exception] = httpx.ReadTimeout
    seen: int = 0


@dataclass
class Faults(httpx.AsyncBaseTransport):
    inner: httpx.AsyncBaseTransport
    faults: list[Fault] = field(default_factory=list)
    requests: list[httpx.Request] = field(default_factory=list)

    def calls(self, method: str, path: str) -> int:
        return sum(1 for r in self.requests if r.method == method and r.url.path == path)

    def _due(self, request: httpx.Request, when: str) -> Fault | None:
        for fault in self.faults:
            if fault.when == when and fault.method == request.method and fault.path == request.url.path \
                    and fault.seen == fault.nth:
                self.faults.remove(fault)
                return fault
        return None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for fault in self.faults:
            if fault.method == request.method and fault.path == request.url.path:
                fault.seen += 1
        if fault := self._due(request, "before"):
            raise fault.error("injected before the request reached Acme", request=request)
        response = await self.inner.handle_async_request(request)
        if fault := self._due(request, "after"):
            await response.aread()
            raise fault.error("injected after Acme answered", request=request)
        return response


@dataclass
class Sandbox:
    app: object
    db_path: object
    admin: TestClient
    store: RunStore

    def faults(self, *faults: Fault) -> Faults:
        return Faults(httpx.ASGITransport(app=self.app), list(faults))

    def run(self, transport: httpx.AsyncBaseTransport | None = None, request: str = "test request", *,
            plan: Plan | None = None, gate=None) -> Run:
        """A run on this sandbox. With a `plan`, the operator's own policy gate decides, as in a real run; without
        one, the allow-all test gate, for tests of tool and lifecycle mechanics that are not about policy."""
        if gate is None and plan is None:
            gate = AllowAllGate()
        return start_run(request, NOW, store=self.store, config=CONFIG, gate=gate, plan=plan,
                         transport=transport or httpx.ASGITransport(app=self.app))

    def admin_call(self, method: str, path: str, **params) -> dict:
        response = self.admin.request(method, path, params=params, headers=ADMIN)
        assert response.status_code < 300, response.text
        return response.json()["data"]

    def rows(self, sql: str, *params) -> list[sqlite3.Row]:
        conn = connect(self.db_path)
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()


@pytest.fixture
def sandbox(tmp_path, monkeypatch) -> Sandbox:
    monkeypatch.setenv("ACME_ADMIN_TOKEN", ADMIN["X-Admin-Token"])
    monkeypatch.setenv("ACME_PASSWORD_OPS_AGENT", PASSWORD)
    monkeypatch.setenv("ACME_CHAOS_TIMEOUT_DELAY_SECONDS", "0.01")
    db_path = tmp_path / "acme.db"
    conn = connect(db_path)
    reset(conn, "base")
    conn.close()
    app = create_app(db_path)
    store = RunStore(tmp_path / "runs" / "runs.db")
    yield Sandbox(app, db_path, TestClient(app), store)
    store.close()


def drive(run: Run, body: Callable) -> object:
    """Run `await body(run)` on a fresh event loop and close the run's client afterwards."""
    async def main():
        try:
            return await body(run)
        finally:
            await run.close()
    return asyncio.run(main())
