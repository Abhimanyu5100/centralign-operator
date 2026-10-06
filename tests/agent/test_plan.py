"""The plan schema (agent/plan.py): what the Day 4 planner must emit and the verifier reads. Register 2.2, 2.4,
N.156; D-131."""

import json

import pytest
from pydantic import ValidationError

from agent.plan import Plan, plan_problems
from bench.oracles import oracle_for
from tests.agent.agent_fixtures import AllowAllGate

M1 = {"id": "M1", "target": "invoice entered", "predicates": [{"read": "list_invoices", "where": {"invoice_no": "X"}}]}


def plan(*milestones, sop_id="process-invoice") -> dict:
    return {"sop_id": sop_id, "milestones": list(milestones)}


def test_a_plan_round_trips_through_json_with_its_refs():
    m2 = {"id": "M2", "target": "approval", "after": ["M1"], "predicates": [
        {"read": "list_approvals", "where": {"entity_id": {"ref": "M1"}}}]}
    parsed = Plan.model_validate_json(json.dumps(plan(M1, m2)))
    assert Plan.model_validate_json(parsed.model_dump_json()) == parsed


@pytest.mark.parametrize("bad, message", [
    (plan(M1, M1), "duplicate milestone id"),
    (plan({**M1, "after": ["M2"]}), "names no earlier milestone"),                       # no cycles: only backwards
    (plan({**M1, "predicates": [{"read": "list_x", "where": {"a": {"ref": "M1"}}}]}), "earlier milestone.s row"),
    (plan({**M1, "predicates": [{"read": "list_x", "count": 2}]},
          {"id": "M2", "target": "y", "predicates": [{"read": "list_y", "args": {"a": {"ref": "M1"}}}]}),
     "finds one row"),
    (plan({**M1, "predicates": []}), "give predicates"),
    (plan({**M1, "unverifiable_reason": "both"}), "not both"),
    (plan(*[{**M1, "id": f"M{i}"} for i in range(1, 9)]), "at most 7"),
    (plan({**M1, "id": "step1"}), "string_pattern_mismatch"),
    (plan({**M1, "predicates": [{"read": "list_x", "count": -1}]}), "greater than or equal"),
    (plan({**M1, "predicates": [{"read": "list_x", "expect": {"amount_paise": "62400"}, "sql": "x"}]}), "extra"),
    (plan(M1, sop_id="Process Invoice"), "string_pattern_mismatch"),
])
def test_a_malformed_plan_is_refused(bad, message):
    with pytest.raises(ValidationError, match=message):
        Plan.model_validate(bad)


def test_a_later_predicate_may_use_its_own_milestones_first_row():
    own = {"id": "M1", "target": "mail", "predicates": [
        {"read": "list_mail", "where": {"to_addr": "a@b.example"}},
        {"read": "read_mail", "args": {"mail_id": {"ref": "M1"}}, "contains": {"body": ["hi"]}}]}
    assert Plan.model_validate(plan(own)).milestones[0].predicates[1].refs() == ["M1"]


def test_plan_problems_names_reads_that_are_not_api_read_tools():
    from agent.tools.registry import build_registry
    bad = Plan.model_validate(plan({"id": "M1", "target": "x", "predicates": [
        {"read": "browser_open"}, {"read": "submit_invoice"}, {"read": "no_such_tool"}, {"read": "list_invoices"}]}))
    assert plan_problems(bad, build_registry(AllowAllGate())) == [
        "M1: 'browser_open' is not an API read tool", "M1: 'submit_invoice' is not an API read tool",
        "M1: 'no_such_tool' is not an API read tool"]


@pytest.mark.parametrize("run_id", ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9:approve"])
def test_every_oracle_plan_reads_only_through_api_read_tools(run_id):
    from agent.tools.registry import build_registry
    assert plan_problems(oracle_for(run_id).plan, build_registry(AllowAllGate())) == []
