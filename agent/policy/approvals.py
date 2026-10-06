"""Action approvals (D-103): the human's OK for one held call, kept as append-only `approval` events in the run store.

An approval moves requested -> decided (approved or rejected) -> consumed. Each step is a new event in the run's
own log and nothing is ever updated in place: the state of an approval is a fold over its events, and the FIRST
decision and the FIRST consumption win, so two clicks on "approve" cannot change what was decided.

- `request` is called by the registry when the gate holds a call; it is idempotent while a request for the same
  (run, fingerprint) is still pending, so a repeated call does not pile up cards in the inbox.
- `decide` is called only by the approval inbox (ui/app.py); no agent tool reaches it.
- `usable` is what the gate asks: an approved, unconsumed approval for exactly this (run, fingerprint).
- `consume` is called by the registry just before the approved call runs. A second identical call needs a new
  approval, and so does a retry after a failure (N.151).
"""

import secrets
import threading
from typing import Any, Literal

from pydantic import BaseModel

from agent.store import RunStore

Status = Literal["pending", "approved", "rejected"]
_LOCK = threading.Lock()  # one process may serve the inbox on several threads, each with its own store connection


class Approval(BaseModel):
    approval_id: str
    run_id: str
    fingerprint: str
    policy_ids: list[str]
    reason: str
    predicted: dict[str, Any]
    status: Status = "pending"
    decided_by: str | None = None
    note: str = ""
    consumed: bool = False


class ApprovalError(ValueError):
    """The decision cannot be applied (unknown approval, or already decided)."""


class ApprovalStore:
    def __init__(self, store: RunStore):
        self.store = store

    def _fold(self, events: list[dict[str, Any]]) -> dict[str, Approval]:
        approvals: dict[str, Approval] = {}
        for event in events:
            p = event["payload"]
            if p["action"] == "requested":
                approvals[p["approval_id"]] = Approval(run_id=event["run_id"], **{k: v for k, v in p.items()
                                                                                    if k != "action"})
                continue
            approval = approvals.get(p["approval_id"])
            if approval is None:
                continue
            if p["action"] == "decided" and approval.status == "pending":
                approval.status, approval.decided_by, approval.note = p["decision"], p["by"], p.get("note", "")
            elif p["action"] == "consumed" and approval.status == "approved":
                approval.consumed = True
        return approvals

    def all(self) -> list[Approval]:
        return list(self._fold(self.store.events_of_type("approval")).values())

    def for_run(self, run_id: str) -> list[Approval]:
        events = [{**e, "run_id": run_id} for e in self.store.events(run_id) if e["type"] == "approval"]
        return list(self._fold(events).values())

    def pending(self) -> list[Approval]:
        return [a for a in self.all() if a.status == "pending"]

    def get(self, approval_id: str) -> Approval:
        found = next((a for a in self.all() if a.approval_id == approval_id), None)
        if found is None:
            raise ApprovalError(f"no approval {approval_id!r}")
        return found

    def _append(self, run_id: str, payload: dict[str, Any]) -> None:
        self.store.append(run_id, "approval", self.store.run(run_id)["now"], payload)

    def request(self, run_id: str, fingerprint: str, policy_ids: list[str], reason: str,
                predicted: dict[str, Any]) -> str:
        with _LOCK:
            waiting = next((a for a in self.for_run(run_id) if a.fingerprint == fingerprint and a.status == "pending"),
                           None)
            if waiting is not None:
                return waiting.approval_id
            approval_id = "A-" + secrets.token_hex(4)
            self._append(run_id, {"action": "requested", "approval_id": approval_id, "fingerprint": fingerprint,
                                  "policy_ids": policy_ids, "reason": reason, "predicted": predicted})
            return approval_id

    def decide(self, approval_id: str, decision: Literal["approved", "rejected"], by: str, note: str = "") -> Approval:
        if decision not in ("approved", "rejected"):
            raise ApprovalError(f"decision must be approved or rejected, not {decision!r}")
        with _LOCK:
            approval = self.get(approval_id)
            if approval.status != "pending":
                raise ApprovalError(f"approval {approval_id} is already {approval.status}")
            self._append(approval.run_id, {"action": "decided", "approval_id": approval_id, "decision": decision,
                                           "by": by, "note": note})
        return self.get(approval_id)

    def usable(self, run_id: str, fingerprint: str) -> str | None:
        return next((a.approval_id for a in self.for_run(run_id)
                     if a.fingerprint == fingerprint and a.status == "approved" and not a.consumed), None)

    def consume(self, run_id: str, approval_id: str) -> None:
        self._append(run_id, {"action": "consumed", "approval_id": approval_id})
