"""Failure classifier (register 5.2): what a failed tool result means and what to do next, decided in code.

The Day 4 executor acts on it (two strikes, read back first); the verifier uses it to tell a run that ended on a
policy refusal (`blocked_by_policy`); the report lists every failure with its class.

The signals are the typed `error_type` and, because Acme's error types are frozen (D-058), the policy id in the
detail: a 409 `conflict` naming ORG-002 is Acme refusing on policy (D-091, D-100); a plain 409 is a state conflict.
A write whose outcome is unknown (`outcome_unknown`, D-108) is never retried blindly: read back first.
"""

import re
from typing import Literal

from pydantic import BaseModel

from agent.tools.registry import ToolResult

Kind = Literal["ok", "policy_refusal", "pause", "read_back_first", "transient", "session", "state_conflict",
               "fix_or_replan", "escalate"]
POLICY_ID = re.compile(r"\b(?:ORG|USR|TSK)-\d{3}\b")
NEXT: dict[str, str] = {
    "ok": "continue",
    "policy_refusal": "do not retry or work around it; replan without this action or report it",
    "pause": "wait for the action approval in the inbox; then re-run the same call",
    "read_back_first": "read back whether the write happened before any new write",
    "transient": "retry once (it counts as a strike)",
    "session": "log in again, read back, then retry",
    "state_conflict": "read the current state, then replan",
    "fix_or_replan": "fix the arguments or replan; the same call will fail again",
    "escalate": "stop and report: the tool or the setup is broken",
}
FIX = {"invalid_args", "invalid_input", "invalid_request", "not_found", "unknown_tool", "precondition_failed",
       "idempotency_key_required", "idempotency_key_reused", "unsupported_media_type"}


class Failure(BaseModel):
    kind: Kind
    policy_id: str | None = None
    next: str


def classify(result: ToolResult) -> Failure:
    kind, policy = _kind(result)
    return Failure(kind=kind, policy_id=policy, next=NEXT[kind])


def _kind(result: ToolResult) -> tuple[Kind, str | None]:
    if result.ok:
        return "ok", None
    if result.data.get("outcome_unknown"):
        return "read_back_first", None
    error, named = result.error_type, POLICY_ID.search(result.detail or "")
    cited = (result.data.get("policy_ids") or [None])[0]
    if error == "policy_denied":
        return "policy_refusal", cited
    if error == "approval_required":
        return "pause", cited
    if error == "forbidden" or (error == "conflict" and named):  # Acme refusing on a role or a policy
        return "policy_refusal", named[0] if named else None
    if error == "conflict":
        return "state_conflict", None
    if error in ("timeout", "connection_error", "server_error"):
        return "transient", None
    if error in ("session_expired", "login_required"):
        return "session", None
    return ("fix_or_replan", None) if error in FIX else ("escalate", None)
