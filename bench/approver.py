"""The bench's scripted approver: the human of the approval inbox, for runs whose task names an approver decision
(T9: `none`, `approve`, `reject`). It uses the inbox's own JSON endpoints (ui/app.py through Starlette's
TestClient), so the bench decides exactly the way a person does, form token included. Harness side only."""

from pathlib import Path
from typing import Any, Literal

from fastapi.testclient import TestClient

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
