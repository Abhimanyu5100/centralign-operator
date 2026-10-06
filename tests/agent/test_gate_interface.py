"""The gate's interface (agent/policy/gate.py, D-101, extended by D-131). Risks P.2, N.121.

The evaluator itself is tested in tests/policy/test_gate.py; these tests pin the models every caller relies on."""

import pytest
from pydantic import ValidationError

from agent.policy.gate import GATE_ERROR, Decision, HttpRequest, Target, ToolCall
from tests.agent.agent_fixtures import NOW

CALL = dict(run_id="r1", now=NOW, tool="send_mail", args={"to": "accounts@example.com"},
            side_effect="external_comms", channel="api", request=HttpRequest(method="POST", path="/api/mail/send"),
            fingerprint="f" * 64)


def test_the_day_3_fields_are_optional_so_day_2_callers_still_fit():
    call = ToolCall(**CALL)
    assert (call.sop_id, call.trust_sensitive, call.target) == (None, (), None)
    assert Decision(effect="allow", reason="x").approval_id is None
    assert ToolCall(**CALL, target=Target(entity="invoice", id=4)).target.id == 4


@pytest.mark.parametrize("effect", ["deny", "require_approval"])
def test_only_an_allow_can_rest_on_an_approval(effect):
    with pytest.raises(ValidationError, match="only an allow"):
        Decision(effect=effect, policy_ids=["ORG-005"], reason="x", approval_id="A-1")
    assert Decision(effect="allow", policy_ids=["ORG-005"], reason="x", approval_id="A-1").approval_id == "A-1"


@pytest.mark.parametrize("effect", ["deny", "require_approval"])
def test_a_block_must_name_a_policy(effect):
    with pytest.raises(ValidationError, match="at least one policy id"):
        Decision(effect=effect, reason="no reason to cite")
    assert Decision(effect=effect, policy_ids=["ORG-001", "ORG-003"], reason="two rules").policy_ids == ["ORG-001",
                                                                                                    "ORG-003"]


@pytest.mark.parametrize("fields", [dict(effect="allow", reason=""), dict(effect="maybe", reason="x"),
                                    dict(effect="allow", reason="x", policy_id="ORG-001")])
def test_a_malformed_decision_is_refused(fields):
    with pytest.raises(ValidationError):
        Decision(**fields)


def test_gate_error_is_a_valid_policy_id_for_a_deny():
    assert Decision(effect="deny", policy_ids=[GATE_ERROR], reason="gate failed").policy_ids == ["GATE-ERROR"]


@pytest.mark.parametrize("change", [dict(now=NOW.replace(tzinfo=None)), dict(side_effect="write"),
                                    dict(channel="email"), dict(extra=1)])
def test_a_malformed_tool_call_is_refused(change):
    with pytest.raises(ValidationError):
        ToolCall(**{**CALL, **change})


def test_tool_call_and_decision_are_frozen():
    call = ToolCall(**CALL)
    decision = Decision(effect="allow", reason="x")
    with pytest.raises(ValidationError):
        call.tool = "other"
    with pytest.raises(ValidationError):
        decision.effect = "deny"
