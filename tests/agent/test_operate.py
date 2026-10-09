"""The run path end to end (agent/run.py) on an in-process Acme with the real policy gate: the feasibility gate
(agent/feasibility.py), the planner's checks (agent/planner.py), the status from the verifier only (6.10), and
record -> replay with a fresh run id and no key (X.1, D-106, author's change 2). The model is scripted (fake), or
a real LLMClient over a scripted mock provider for the replay test. Register 1.2, 1.3, 1.5, 1.6, 2.1, 2.3."""

import asyncio
import json

import httpx
import pytest

from agent.feasibility import names_in
from agent.goal import Fact, Field, GoalSpec
from agent.llm.client import LLMClient
from agent.memory.knowledge import load_sops
from agent.plan import Plan
from agent.planner import plan_errors
from agent.run import operate
from tests.acme.sop_format import load_sops as strict_sops
from tests.agent.acme_fixtures import CONFIG, drive, sandbox  # noqa: F401  (sandbox is a fixture)
from tests.agent.agent_fixtures import NOW
from tests.agent.llm_fakes import FakeLLM, calls, say

SHARMA = "Process the latest invoice from Sharma Logistics."
KAPOOR = "Pay the invoice from Kapoor Steel."


def gate(decision, sop="process-invoice", **extra):
    return say(json.dumps({"decision": decision, "sop_id": sop, "fields": [], "success": [], "question": "",
                           "candidates": [], "reason": "", **extra}))


PLAN = {"sop_id": "process-invoice", "milestones": [{
    "id": "M1", "target": "an invoice from Sharma Logistics Pvt Ltd waits for approval", "sop_step": "PI-5",
    "predicates": [{"read": "list_invoices", "args": {"status": "pending_approval"},
                    "where": {"vendor_name": "Sharma Logistics Pvt Ltd"}}]}]}
VENDOR_FACT = {"facts": [{"name": "vendor_name", "raw": "Sharma Logistics Pvt Ltd", "result": 1}]}


def operate_with(sandbox, request, *replies, config=None, make_llm=None):
    llm = FakeLLM(*replies)
    report = asyncio.run(operate(request, NOW, store=sandbox.store, config=config or CONFIG,
                                 transport=httpx.ASGITransport(app=sandbox.app), make_llm=make_llm or (lambda run: llm)))
    return report, llm, sandbox.store.events(report["run_id"])


# --- feasibility gate ------------------------------------------------------------------------------------------

def test_names_are_the_capitalised_runs_after_the_verb():
    assert names_in(SHARMA) == ["Sharma Logistics"] and names_in(KAPOOR) == ["Kapoor Steel"]
    assert names_in("Onboard Priya Nair, she joins Monday.") == ["Priya Nair"]


def test_an_unknown_vendor_is_declined_with_evidence_written_by_code(sandbox):
    report, llm, _ = operate_with(sandbox, KAPOOR, gate("decline", "schedule-payment", reason="No such vendor."))
    assert report["status"] == "infeasible" and report["refusal"]["reason"] == "No such vendor."
    assert "find_vendors q='Kapoor Steel': 0 match(es)" in report["refusal"]["evidence"]
    assert "find_vendors q='Kapoor': 0 match(es)" in llm.requests[0]["messages"][1]["content"]


def test_a_decline_with_no_empty_lookup_becomes_a_question(sandbox):
    """1.6: the vendor was found (only the employee lookups were empty), so the model's decline is not trusted; the
    run asks instead and writes nothing."""
    report, _, _ = operate_with(sandbox, SHARMA, gate("decline", reason="I would rather not."))
    assert report["status"] == "needs_clarification" and report["questions"][0]["text"] == "I would rather not."


def test_an_sop_outside_the_candidates_and_an_unseen_field_are_dropped(sandbox):
    reply = gate("ask", "schedule-payment", question="Which one?",
                 fields=[{"name": "vendor", "value": "Sharma Logistics Pvt Ltd", "source": "probe"},
                         {"name": "invoice_no", "value": "INV-9999", "source": "request"}])
    _, _, events = operate_with(sandbox, SHARMA, reply)
    goal = next(e["payload"] for e in events if e["type"] == "goal")
    assert goal["sop_id"] is None and [f["value"] for f in goal["fields"]] == ["Sharma Logistics Pvt Ltd"]


def test_the_agent_loader_agrees_with_the_strict_sop_parser():
    strict = {s.id: s for s in strict_sops()}
    assert {k: (s.title, s.triggers, s.steps) for k, s in load_sops().items()} == {
        k: (s.title, s.triggers, [step.id for step in s.steps]) for k, s in strict.items()}


# --- planner and the whole path --------------------------------------------------------------------------------

def test_the_agents_done_never_sets_the_status(sandbox):
    """6.10: the plan's milestone is not met and the agent says it is done: the verifier says failed."""
    report, _, events = operate_with(sandbox, SHARMA, gate("proceed"), calls(("find_vendors", {"q": "Sharma"})),
                                     calls(("facts_ready", VENDOR_FACT)), say(json.dumps(PLAN)), say("All done."))
    assert report["status"] == "failed" and report["narrative"] == ["All done."]
    assert [e["payload"]["problems"] for e in events if e["type"] == "plan"] == [[]]


def test_a_bad_plan_gets_one_retry_then_the_run_never_acts(sandbox):
    invented = json.loads(json.dumps(PLAN))
    invented["milestones"][0]["predicates"][0]["expect"] = {"amount_paise": 999}
    report, llm, events = operate_with(sandbox, SHARMA, gate("proceed"), calls(("find_vendors", {"q": "Sharma"})),
                                       calls(("facts_ready", VENDOR_FACT)), say(json.dumps(invented)), say("no JSON"))
    problems = [e["payload"]["problems"] for e in events if e["type"] == "plan"]
    assert "M1: 999 is not from the facts, the goal, the procedure or the tools" in problems[0]
    assert "Fix these problems" in llm.requests[-1]["messages"][-1]["content"] and len(problems) == 2
    assert report["status"] == "unverified" and not llm.replies


def plan_with(**milestone):
    return Plan.model_validate({**PLAN, "milestones": [{**PLAN["milestones"][0], **milestone}]})


@pytest.mark.parametrize("plan, problem", [
    (plan_with(sop_step="SP-1"), "M1: sop_step 'SP-1' is not a step of process-invoice"),
    (plan_with(predicates=[{"read": "list_invoices", "args": {"colour": "red"}}]), "list_invoices args: colour: Extra"),
    (plan_with(predicates=[{"read": "list_invoices", "args": {"status": "any"}}]), "list_invoices args: status: Input"),
    (plan_with(predicates=[{"read": "list_invoices", "expect": {"colour": "red"}}]), "rows have no field 'colour'"),
    (plan_with(predicates=[{"read": "submit_invoice"}]), "'submit_invoice' is not an API read tool"),
    (plan_with(predicates=[{"read": "list_invoices", "where": {"invoice_no": "INV-4040"}}]), "'INV-4040' is not from"),
    (Plan(sop_id="process-invoice"), "give 1 to 7 milestones"),
])
def test_each_planner_rule_has_a_failing_plan(sandbox, plan, problem):
    run = sandbox.run(plan=Plan(sop_id="process-invoice"))
    goal = GoalSpec(request=SHARMA, decision="proceed", sop_id="process-invoice",
                    fields=[Field(name="vendor", value="Sharma Logistics Pvt Ltd", source="probe")])
    sop = load_sops()["process-invoice"]
    assert plan_errors(plan_with(), run, goal, sop, []) == []
    problems = plan_errors(plan, run, goal, sop, [], {"list_invoices": ["invoice_no", "status", "vendor_name"]})
    assert any(problem in p for p in problems), problems
    drive(run, lambda run: asyncio.sleep(0))


def test_a_fact_counts_as_a_source_by_its_value_or_its_raw_text(sandbox):
    run = sandbox.run(plan=Plan(sop_id="process-invoice"))
    goal = GoalSpec(request=SHARMA, decision="proceed", sop_id="process-invoice")
    amount = Fact(name="amount_paise", raw="₹62,400.00", value=6_240_000, result=3)
    by_value = plan_with(predicates=[{"read": "list_invoices", "expect": {"amount_paise": 6_240_000},
                                      "where": {"vendor_name": "Sharma Logistics Pvt Ltd"}}])
    by_raw = plan_with(predicates=[{"read": "list_invoices", "where": {"invoice_no": "₹62,400.00"}}])
    sop = load_sops()["process-invoice"]
    vendor = Fact(name="vendor_name", raw="Sharma Logistics Pvt Ltd", value="Sharma Logistics Pvt Ltd", result=1)
    assert plan_errors(by_value, run, goal, sop, [amount, vendor]) == []
    assert plan_errors(by_raw, run, goal, sop, [amount, vendor]) == []
    assert plan_errors(by_value, run, goal, sop, [vendor]) != []
    drive(run, lambda run: asyncio.sleep(0))


# --- record, then replay with a fresh run id and no key ---------------------------------------------------------

def provider(request: httpx.Request) -> httpx.Response:
    """A scripted OpenAI-compatible provider, answering by the step the request comes from."""
    body = json.loads(request.content)
    system, last = body["messages"][0]["content"], body["messages"][-1]
    if system.startswith("You are the intake step"):
        message = {"content": json.dumps({"decision": "proceed", "sop_id": "process-invoice", "fields": [],
                                          "success": [], "question": "", "candidates": [], "reason": ""})}
    elif "Phase: gather" in system:
        call = ("facts_ready", VENDOR_FACT) if last["role"] == "tool" else ("find_vendors", {"q": "Sharma"})
        message = {"content": None, "tool_calls": [{"id": "", "type": "function", "function": {
            "name": call[0], "arguments": json.dumps(call[1])}}]}
    elif system.startswith("You write the plan"):
        message = {"content": json.dumps(PLAN)}
    else:
        message = {"content": "All done."}
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", **message}}],
                                     "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}})


def test_a_recorded_run_replays_with_a_fresh_run_id_and_no_key(sandbox, tmp_path):
    keys = {"GEMINI_API_KEY": "gk-test-key-1", "GEMINI_BASE_URL": "https://gemini.test/", "GEMINI_MODEL": "flash"}
    folder = {"CASSETTE_DIR": str(tmp_path / "cassettes")}
    live = {**CONFIG, **keys, **folder}

    def recording(run):
        return LLMClient(live, now=NOW.isoformat(), forbidden=(run.run_id,), transport=httpx.MockTransport(provider))
    first, _, _ = operate_with(sandbox, SHARMA, config=live, make_llm=recording)
    files = sorted(p.name for p in (tmp_path / "cassettes").rglob("*.json"))
    sandbox.admin_call("POST", "/__admin/reset", seed="base", now=NOW.isoformat())

    def replaying(run):
        return LLMClient({**CONFIG, **folder, "REPLAY": "1"}, now=NOW.isoformat(), forbidden=(run.run_id,),
                         transport=httpx.MockTransport(lambda r: pytest.fail("a replay must not call a provider")))
    again, _, _ = operate_with(sandbox, SHARMA, config={**CONFIG, **folder, "REPLAY": "1"}, make_llm=replaying)
    assert again["run_id"] != first["run_id"] and len(files) == 5  # gate, 2 gather turns, plan, act
    assert sorted(p.name for p in (tmp_path / "cassettes").rglob("*.json")) == files
    assert (again["status"], again["narrative"]) == (first["status"], first["narrative"]) == ("failed", ["All done."])
    stored = "".join(p.read_text() for p in (tmp_path / "cassettes").rglob("*.json"))
    assert first["run_id"] not in stored and "gk-test-key-1" not in stored
