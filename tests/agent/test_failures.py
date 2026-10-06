"""The failure classifier (agent/failures.py): one test per error type, the two 409s, and an unknown outcome.
Register 5.2; D-091, D-100, D-108."""

import pytest

from agent.failures import NEXT, classify
from agent.tools.registry import ERROR_TYPES, ToolResult


def fail(error_type: str, detail: str = "", **data) -> ToolResult:
    return ToolResult.fail(error_type, detail, **data)


@pytest.mark.parametrize("where", ["create", "approve"])
def test_a_409_naming_org002_is_a_policy_refusal(where):
    detail = {"create": "ORG-002: the vendor of this invoice is not approved",
              "approve": "ORG-002: cannot approve a payment while the vendor is blocked"}[where]
    failure = classify(fail("conflict", detail, http_status=409))
    assert (failure.kind, failure.policy_id) == ("policy_refusal", "ORG-002") and "do not retry" in failure.next


def test_a_plain_409_is_a_state_conflict_not_a_refusal():
    failure = classify(fail("conflict", "Duplicate invoice number for this vendor", http_status=409))
    assert (failure.kind, failure.policy_id) == ("state_conflict", None)


@pytest.mark.parametrize("error_type", ["timeout", "connection_error", "server_error"])
def test_an_unknown_outcome_means_read_back_first_never_a_retry_or_a_refusal(error_type):
    failure = classify(fail(error_type, "no answer", outcome_unknown=True, attempts=["attempt 1: timeout"]))
    assert failure.kind == "read_back_first"


@pytest.mark.parametrize("error_type, kind", [
    ("policy_denied", "policy_refusal"), ("approval_required", "pause"), ("forbidden", "policy_refusal"),
    ("timeout", "transient"), ("connection_error", "transient"), ("server_error", "transient"),
    ("session_expired", "session"), ("login_required", "session"), ("invalid_credentials", "escalate"),
    ("invalid_args", "fix_or_replan"), ("invalid_input", "fix_or_replan"), ("invalid_request", "fix_or_replan"),
    ("not_found", "fix_or_replan"), ("unknown_tool", "fix_or_replan"), ("precondition_failed", "fix_or_replan"),
    ("idempotency_key_required", "fix_or_replan"), ("idempotency_key_reused", "fix_or_replan"),
    ("unsupported_media_type", "fix_or_replan"), ("tool_crashed", "escalate"), ("conflict", "state_conflict"),
])
def test_every_error_type_has_a_class(error_type, kind):
    assert classify(fail(error_type, "x")).kind == kind


def test_the_table_covers_every_declared_error_type():
    covered = {"policy_denied", "approval_required", "forbidden", "timeout", "connection_error", "server_error",
               "session_expired", "login_required", "invalid_credentials", "invalid_args", "invalid_input",
               "invalid_request", "not_found", "unknown_tool", "precondition_failed", "idempotency_key_required",
               "idempotency_key_reused", "unsupported_media_type", "tool_crashed", "conflict"}
    assert covered == set(ERROR_TYPES)


def test_a_gate_deny_cites_its_policy_and_an_ok_result_is_ok():
    assert classify(fail("policy_denied", "ORG-004: no admin", policy_ids=["ORG-004", "ORG-006"])).policy_id == "ORG-004"
    assert classify(ToolResult(ok=True)).kind == "ok"
    assert set(NEXT) >= {"ok", "policy_refusal", "pause", "read_back_first", "transient", "session", "state_conflict",
                         "fix_or_replan", "escalate"}
