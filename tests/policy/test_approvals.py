"""Action approvals (agent/policy/approvals.py) and how the registry files and consumes them: matched on (run,
fingerprint), single use, first decision wins, a deny is never lifted. D-103; risks P.5, N.128, N.150, N.151."""

import pytest

from agent.policy.approvals import ApprovalError, ApprovalStore
from agent.policy.facts import Facts
from agent.policy.gate import PolicyGate
from agent.policy.models import PolicyFile
from agent.store import RunStore
from agent.tools.registry import Registry, RunContext
from tests.agent.agent_fixtures import NOW, call, spec

PREDICTED = {"tool": "echo", "args": {"text": "hi"}, "request": None, "side_effect": "read", "effect": "x"}


class NoFacts:
    def of(self, run_id):
        return Facts()


@pytest.fixture
def store(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    yield store
    store.close()


def test_a_request_is_pending_until_decided_and_filed_once_while_pending(store):
    approvals, run_id = ApprovalStore(store), store.start_run("r", NOW)
    first = approvals.request(run_id, "f1", ["ORG-005"], "external mail", PREDICTED)
    assert approvals.request(run_id, "f1", ["ORG-005"], "external mail", PREDICTED) == first
    assert [a.approval_id for a in approvals.pending()] == [first] and approvals.usable(run_id, "f1") is None
    decided = approvals.decide(first, "approved", by="meera", note="fine")
    assert (decided.status, decided.decided_by, decided.note) == ("approved", "meera", "fine")
    assert approvals.usable(run_id, "f1") == first and approvals.pending() == []


def test_an_approval_is_used_once(store):
    approvals, run_id = ApprovalStore(store), store.start_run("r", NOW)
    approval = approvals.request(run_id, "f1", ["ORG-005"], "x", PREDICTED)
    approvals.decide(approval, "approved", by="meera")
    approvals.consume(run_id, approval)
    assert approvals.usable(run_id, "f1") is None and approvals.get(approval).consumed
    assert approvals.request(run_id, "f1", ["ORG-005"], "x", PREDICTED) != approval  # the next call needs a new one


def test_decide_twice_is_refused_and_the_first_decision_wins(store):
    approvals, run_id = ApprovalStore(store), store.start_run("r", NOW)
    approval = approvals.request(run_id, "f1", ["ORG-005"], "x", PREDICTED)
    approvals.decide(approval, "rejected", by="meera")
    with pytest.raises(ApprovalError, match="already rejected"):
        approvals.decide(approval, "approved", by="meera")
    # even a decision that lands in the log anyway (a race) cannot change the first one
    store.append(run_id, "approval", NOW.isoformat(), {"action": "decided", "approval_id": approval,
                                                       "decision": "approved", "by": "x"})
    assert approvals.get(approval).status == "rejected" and approvals.usable(run_id, "f1") is None


@pytest.mark.parametrize("decision", ["approve", "yes", ""])
def test_only_approved_or_rejected_are_decisions(store, decision):
    approvals, run_id = ApprovalStore(store), store.start_run("r", NOW)
    approval = approvals.request(run_id, "f1", ["ORG-005"], "x", PREDICTED)
    with pytest.raises(ApprovalError):
        approvals.decide(approval, decision, by="meera")


def test_an_unknown_approval_cannot_be_decided(store):
    with pytest.raises(ApprovalError, match="no approval"):
        ApprovalStore(store).decide("A-nope", "approved", by="meera")


def test_approvals_belong_to_one_run_and_one_fingerprint(store):
    approvals = ApprovalStore(store)
    run_a, run_b = store.start_run("a", NOW), store.start_run("b", NOW)
    approval = approvals.request(run_a, "f1", ["ORG-005"], "x", PREDICTED)
    approvals.decide(approval, "approved", by="meera")
    assert approvals.usable(run_b, "f1") is None and approvals.usable(run_a, "f2") is None
    assert [a.run_id for a in approvals.all()] == [run_a] and approvals.for_run(run_b) == []


# --- through the registry and the real gate ----------------------------------------------------------------------

def _held_echo(store: RunStore):
    """A registry whose policy holds every `echo` call, with a real approval store, and a context for one run."""
    policies = PolicyFile.model_validate({"schema_version": 0, "rules": [
        {"id": "ORG-901", "level": "org", "enforced_by": "runtime", "effect": "require_approval",
         "message": "echo needs a human", "when": [{"type": "tool_in", "tools": ["echo"]}]}]})
    policies.attach_allowlists({})
    approvals = ApprovalStore(store)
    registry = Registry(PolicyGate(policies, NoFacts(), approvals), approvals)
    ran = []

    async def tool(args, ctx):
        from agent.tools.registry import ToolResult
        ran.append(args.text)
        return ToolResult(ok=False, error_type="timeout", detail="no answer") if args.text == "fail" else \
            ToolResult(ok=True, detail="echoed", data={"text": args.text})
    registry.register(spec(fn=tool))
    ctx = RunContext(run_id=store.start_run("r", NOW), now=NOW, store=store, sop_id="notify-vendor")
    return registry, approvals, ctx, ran


def test_a_held_call_is_filed_with_its_predicted_outcome_and_does_not_run(store):
    registry, approvals, ctx, ran = _held_echo(store)
    result = call(registry, "echo", {"text": "hi"}, ctx)
    assert result.error_type == "approval_required" and ran == []
    approval = approvals.get(result.data["approval_id"])
    assert approval.policy_ids == ["ORG-901"] and approval.predicted["args"] == {"text": "hi"}
    assert approval.predicted["tool"] == "echo" and approval.fingerprint == result.data["fingerprint"]


def test_after_approval_the_same_call_runs_once_and_a_second_identical_call_is_held_again(store):
    registry, approvals, ctx, ran = _held_echo(store)
    approval_id = call(registry, "echo", {"text": "hi"}, ctx).data["approval_id"]
    approvals.decide(approval_id, "approved", by="meera")
    assert call(registry, "echo", {"text": "hi"}, ctx).ok and ran == ["hi"]
    again = call(registry, "echo", {"text": "hi"}, ctx)
    assert again.error_type == "approval_required" and again.data["approval_id"] != approval_id and ran == ["hi"]
    decision = [e["payload"] for e in store.events(ctx.run_id) if e["type"] == "policy_decision"][1]
    assert decision["effect"] == "allow" and decision["approval_id"] == approval_id
    assert decision["policy_ids"] == ["ORG-901"]  # the allow still cites the rule it rests on


def test_an_approval_does_not_cover_a_changed_call(store):
    registry, approvals, ctx, ran = _held_echo(store)
    approvals.decide(call(registry, "echo", {"text": "hi"}, ctx).data["approval_id"], "approved", by="meera")
    assert call(registry, "echo", {"text": "changed"}, ctx).error_type == "approval_required" and ran == []


def test_a_rejected_call_stays_held(store):
    registry, approvals, ctx, ran = _held_echo(store)
    approvals.decide(call(registry, "echo", {"text": "hi"}, ctx).data["approval_id"], "rejected", by="meera")
    assert call(registry, "echo", {"text": "hi"}, ctx).error_type == "approval_required" and ran == []


def test_a_failed_call_after_consume_needs_a_new_approval(store):
    registry, approvals, ctx, ran = _held_echo(store)
    approval_id = call(registry, "echo", {"text": "fail"}, ctx).data["approval_id"]
    approvals.decide(approval_id, "approved", by="meera")
    assert call(registry, "echo", {"text": "fail"}, ctx).error_type == "timeout" and ran == ["fail"]
    assert approvals.get(approval_id).consumed  # consumed before the tool ran (N.151)
    assert call(registry, "echo", {"text": "fail"}, ctx).error_type == "approval_required" and ran == ["fail"]
