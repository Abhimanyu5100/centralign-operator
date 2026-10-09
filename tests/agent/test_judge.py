"""The verifier's judge (agent/verifier/judge.py) through the real `verify` on an in-process Acme, with a scripted
model: it only lowers `completed` (to completed_with_exceptions); on `awaiting_business_approval` it adds
`judge_flags` and leaves the status; a criterion counts as met only with a quote found in the record; errors are
notes; no criteria or a failed run mean no judge call at all. Register 6.5, 6.6, N.183."""

import json

import pytest

from agent.llm.client import LLMUnavailable
from agent.plan import Plan
from agent.verifier import verify
from tests.agent.acme_fixtures import drive, sandbox  # noqa: F401  (sandbox is a fixture)
from tests.agent.llm_fakes import FakeLLM, say

CRITERION = "the vendor's name says it is a logistics company"


def plan(judge=(CRITERION,), awaits=False, where="Sharma Logistics Pvt Ltd"):
    return Plan.model_validate({"sop_id": "process-invoice", "milestones": [{
        "id": "M1", "target": "Sharma is a vendor", "sop_step": "PI-2", "awaits_business_approval": awaits,
        "judge": list(judge), "predicates": [{"read": "find_vendors", "args": {"q": "Sharma"}, "where": {"name": where}}]}]})


def answer(met, quote, criterion=CRITERION):
    return say(json.dumps({"criteria": [{"criterion": criterion, "met": met, "quote": quote}]}))


def verified(sandbox, the_plan, *replies):
    llm = FakeLLM(*replies)
    run = sandbox.run(plan=the_plan)

    async def body(run):
        await run.begin()
        return await verify(run, llm=llm)
    return drive(run, body), llm


@pytest.mark.parametrize("reply, status, met", [
    (answer(True, "Sharma  LOGISTICS pvt"), "completed", True),           # the quote is in the record
    (answer(True, "a trusted logistics partner"), "completed_with_exceptions", False),  # quote not in the record
    (answer(False, ""), "completed_with_exceptions", False),
    (say(json.dumps({"criteria": []})), "completed_with_exceptions", False),  # left out: unmet
])
def test_the_judge_lowers_completed_only_on_an_unmet_criterion(sandbox, reply, status, met):
    verdict, llm = verified(sandbox, plan(), reply)
    assert verdict.status == status and verdict.judge[0]["met"] is met and verdict.judge_flags == []
    shown = json.dumps(llm.requests[0]["messages"])
    assert llm.requests[0]["role"] == "judge" and "Sharma Logistics Pvt Ltd" in shown and "narrative" not in shown
    if not met:
        assert f"M1 not met: {CRITERION}" in verdict.reasons[-1]


def test_on_awaiting_business_approval_the_judge_only_flags(sandbox):
    verdict, _ = verified(sandbox, plan(awaits=True), answer(False, ""))
    assert verdict.status == "awaiting_business_approval" and verdict.reasons == []
    # the fake is not Groq, so the flag says the judge answered from the same family as the executor
    assert verdict.judge_flags == [f"judge (fake (fallback: same family as the executor)): M1 not met: {CRITERION}"]


def test_no_judge_call_without_criteria_or_on_a_failed_run(sandbox):
    verdict, llm = verified(sandbox, plan(judge=()))
    assert verdict.status == "completed" and llm.requests == []
    verdict, llm = verified(sandbox, plan(where="Nobody Ltd"))
    assert verdict.status == "failed" and llm.requests == [] and verdict.judge == []


def test_a_judge_error_is_a_note_and_never_changes_the_status(sandbox):
    def down(messages):
        raise LLMUnavailable("every configured model failed")
    verdict, _ = verified(sandbox, plan(), down)
    assert verdict.status == "completed" and verdict.judge == []
    assert verdict.notes == [f"judge not run on M1 (LLMUnavailable); fuzzy criteria unchecked: {CRITERION}"]


def test_judge_criteria_need_a_milestone_that_finds_its_record():
    with pytest.raises(ValueError, match="judge criteria need a milestone whose predicates find the record"):
        Plan.model_validate({"milestones": [{"id": "M1", "target": "no payment", "judge": ["polite"],
                                             "predicates": [{"read": "list_payments", "count": 0}]}]})


def test_a_reworded_criterion_is_matched_by_its_position(sandbox):
    second = "the record names a contact person"
    reply = say(json.dumps({"criteria": [{"criterion": "is it logistics?", "met": True, "quote": "Logistics"},
                                         {"criterion": "contact?", "met": False, "quote": ""}]}))
    verdict, _ = verified(sandbox, plan(judge=(CRITERION, second)), reply)
    assert [j["met"] for j in verdict.judge] == [True, False] and verdict.status == "completed_with_exceptions"
