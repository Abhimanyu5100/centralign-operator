"""The bench's scripted approver: the human of the approval inbox, for runs whose task names an approver decision
(T9: `none`, `approve`, `reject`). It uses the inbox's own JSON endpoints (ui/app.py through Starlette's
TestClient), so the bench decides exactly the way a person does, form token included. Harness side only."""

import asyncio
import time
from pathlib import Path
from typing import Any, Literal

from fastapi.testclient import TestClient

from agent.policy.approvals import ApprovalStore
from agent.store import RunStore
from ui.app import create_app

ACTION = {"approve": "approve", "reject": "reject"}


def decide(store_path: Path, run_id: str, decision: Literal["none", "approve", "reject"],
           by: str = "scripted-approver") -> list[dict[str, Any]]:
    """Apply `decision` to every pending approval of `run_id`; `none` leaves them pending. Returns what was decided."""
    if decision == "none":
        return []
    client = TestClient(create_app(store_path))
    listing = client.get("/api/approvals", params={"status": "pending"}).json()["data"]
    decided = []
    for item in (i for i in listing["items"] if i["run_id"] == run_id):
        response = client.post(f"/api/approvals/{item['approval_id']}/{ACTION[decision]}",
                               json={"token": listing["token"], "by": by})
        if response.status_code != 200:
            raise RuntimeError(f"the inbox refused {decision} on {item['approval_id']}: {response.text}")
        decided.append(response.json()["data"])
    return decided


def for_agent(store_path: Path, decision: Literal["none", "approve", "reject"], wait: float = 0.0):
    """The approver an LLM run asks when a call is held (agent.run.operate): the task's scripted decision through the
    inbox, then up to `wait` seconds for a person deciding in `make ui` (same run store). Returns the status."""
    async def approver(approval_id: str) -> str:
        if decision != "none":
            run_id = ApprovalStore(RunStore(store_path)).get(approval_id).run_id
            await asyncio.to_thread(decide, store_path, run_id, decision)
        deadline = time.monotonic() + wait
        while (status := ApprovalStore(RunStore(store_path)).get(approval_id).status) == "pending" \
                and time.monotonic() < deadline:
            await asyncio.sleep(1)
        return status
    return approver
