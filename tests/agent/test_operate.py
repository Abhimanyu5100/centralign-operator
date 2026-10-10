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
from agent.memory.knowledge import load_sops, match_sops
from agent.plan import Plan
from agent.policy.approvals import ApprovalStore
from agent.llm.client import LLMUnavailable
from agent.planner import plan_errors, read_tools, replan_errors, tidy
from agent.run import _plan_failed
from agent.verifier import Verdict
from agent.verifier.predicates import Check, MilestoneCheck
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
                    "where": {"vendor_name": "Sharma Logistics Pvt Ltd"}}]},
    {"id": "M2", "target": "that invoice shows its source file", "sop_step": "PI-6",
     "predicates": [{"read": "list_invoices", "args": {"status": "pending_approval"},
                     "where": {"vendor_name": "Sharma Logistics Pvt Ltd"}}]}],
        "not_applicable": {"PI-7": "a test plan: no approval request"}}
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


def test_a_decline_or_an_ask_with_nothing_unknown_or_ambiguous_proceeds(sandbox):
    """1.6, D-171, D-194: Sharma Logistics is one vendor, so neither the model's decline nor its "which invoice
    number?" is trusted: the run proceeds and the gather phase, with the documents, asks or acts."""
    for reply in (gate("decline", reason="I would rather not."), gate("ask", question="Which invoice number?")):
        report, _, events = operate_with(sandbox, SHARMA, reply, calls(("ask_user", {"question": "Which one?"})))
        goal = next(e["payload"] for e in events if e["type"] == "goal")
        assert goal["decision"] == "proceed" and report["questions"][0]["text"] == "Which one?"


def test_with_no_start_date_anywhere_the_executor_asks_after_the_gate_proceeds(sandbox):
    """D-194 does not silence a needed question: "Onboard Priya Nair." names no date and HR's offer email has none
    (OE-2 "Ask when: no start date"), so the gate's ask becomes proceed (nothing ambiguous) and the gather phase,
    having read the offer email, asks. Nothing is planned or written."""
    def ask_after_reading(messages):
        text = messages[-1]["content"]  # mail is untrusted: a warning line comes first
        listed = json.loads(text.split("\n", 1)[1] if text.startswith("Untrusted") else text)["data"]["items"]
        offer = next(m for m in listed if "offer" in m["subject"].lower())
        return calls(("read_mail", {"mail_id": offer["id"]}))
    report, llm, events = operate_with(
        sandbox, "Onboard Priya Nair.", gate("ask", "onboard-employee", question="When does she start?"),
        calls(("list_mail", {"folder": "inbox"})), ask_after_reading,
        calls(("ask_user", {"question": "The offer email gives no start date. When does Priya Nair start?"})))
    goal = next(e["payload"] for e in events if e["type"] == "goal")
    offer_text = llm.requests[-1]["messages"][-1]["content"]
    assert goal["decision"] == "proceed" and "Priya" in offer_text and "start date" not in offer_text.lower()
    assert report["status"] == "needs_clarification" and "no start date" in report["questions"][0]["text"]
    assert [e for e in events if e["type"] == "plan"] == [] and report["side_effects"] == []


def test_an_ask_stands_when_a_named_party_matches_two_or_more_records(sandbox):
    """D-194: "Ra" matches two vendors (Rao Packaging, Verma Traders): the gate's ask goes to the requester."""
    report, llm, _ = operate_with(sandbox, "Pay Ra for the invoice.",
                                  gate("ask", "schedule-payment", question="Which vendor?"))
    assert "find_vendors q='Ra': 2 match(es)" in llm.requests[0]["messages"][1]["content"]
    assert report["status"] == "needs_clarification" and report["questions"][0]["text"] == "Which vendor?"


def test_an_sop_outside_the_candidates_and_an_unseen_field_are_dropped(sandbox):
    reply = gate("ask", "schedule-payment", question="Which one?",
                 fields=[{"name": "vendor", "value": "Sharma Logistics Pvt Ltd", "source": "probe"},
                         {"name": "invoice_no", "value": "INV-9999", "source": "request"}])
    _, _, events = operate_with(sandbox, SHARMA, reply, calls(("ask_user", {"question": "?"})))
    goal = next(e["payload"] for e in events if e["type"] == "goal")
    assert goal["sop_id"] is None and [f["value"] for f in goal["fields"]] == ["Sharma Logistics Pvt Ltd"]


def test_an_email_request_matches_the_notify_vendor_sop_by_a_generic_word():
    """N.178: "Email <vendor> that ..." has no "email vendor" phrase; the generic trigger "email" matches it."""
    assert "notify-vendor" in match_sops("Email Sharma Logistics that invoice INV-1043 is under review.", load_sops())


def test_write_steps_are_the_steps_whose_source_names_a_post():
    sops = load_sops()
    assert sops["process-invoice"].write_steps() == ["PI-5", "PI-6", "PI-7"]
    assert sops["notify-vendor"].write_steps() == ["NV-4"]
    assert sops["process-invoice"].write_steps(optional=True) == ["PI-7"]  # "... when required" (D-195)
    assert [s for sop in sops.values() for s in sop.write_steps(optional=True)] == ["PI-7"]


def test_the_agent_loader_agrees_with_the_strict_sop_parser():
    strict = {s.id: s for s in strict_sops()}
    assert {k: (s.title, s.triggers, s.steps) for k, s in load_sops().items()} == {
        k: (s.title, s.triggers, [step.id for step in s.steps]) for k, s in strict.items()}


# --- planner and the whole path --------------------------------------------------------------------------------

def test_the_agents_done_never_sets_the_status_and_replanning_stops_after_three(sandbox):
    """6.10: the milestone is not met and the agent says it is done: the verifier says failed. Register 2.6: the
    planner is asked again (here it sends the same plan back, which is allowed) and the agent acts again, exactly
    three times; then an escalation event with the unmet milestone. Not-applicable SOP steps are listed (N.177)."""
    report, llm, events = operate_with(sandbox, SHARMA, gate("proceed"), calls(("find_vendors", {"q": "Sharma"})),
                                       calls(("facts_ready", VENDOR_FACT)), say(json.dumps(PLAN)), say("All done."),
                                       *[say(json.dumps(PLAN)), say("All done.")] * 3)
    assert report["status"] == "failed" and report["narrative"] == ["All done."] * 4 and not llm.replies
    assert [e["payload"].get("replan", 0) for e in events if e["type"] == "plan"] == [0, 1, 2, 3]
    targets = [f"{m['id']}: {m['target']}" for m in PLAN["milestones"]]
    assert report["escalation"] == {"replans": 3, "unmet": targets,
                                    "reasons": [f"milestone {t.replace(': ', ' not met: ', 1)}" for t in targets]}
    act_brief = llm.requests[-1]["messages"][1]["content"]
    assert "An independent check found these milestones unmet: M1 (0 matching row(s)" in act_brief
    assert act_brief.endswith("Records you already wrote stay: read before you write again.")
    assert report["skipped_steps"] == PLAN["not_applicable"] and len(report["replans"]) == 3


def test_a_fact_from_the_gates_lookups_is_quoted_from_result_0(sandbox):
    """D-214: the brief shows the gate's lookups and says not to repeat them, so result 0 holds them as well as the
    request; live T1 (3.1 Flash-Lite) quoted vendor_id 1 from there and was refused until its two strikes."""
    lookup = {"facts": [{"name": "vendor_id", "raw": "1", "result": 0}]}
    report, llm, events = operate_with(sandbox, SHARMA, gate("proceed"), calls(("facts_ready", lookup)),
                                       say(json.dumps(PLAN)), say("All done."),
                                       *[say(json.dumps(PLAN)), say("All done.")] * 3)
    assert not [e for e in events if e["type"] == "executor_stop"] and any(e["type"] == "plan" for e in events)
    assert "facts refused" not in json.dumps(llm.requests)


def test_a_bad_plan_gets_two_retries_then_the_run_never_acts(sandbox):
    invented = json.loads(json.dumps(PLAN))
    invented["milestones"][0]["predicates"][0]["expect"] = {"amount_paise": 999}
    report, llm, events = operate_with(sandbox, SHARMA, gate("proceed"), calls(("find_vendors", {"q": "Sharma"})),
                                       calls(("facts_ready", VENDOR_FACT)), say(json.dumps(invented)), say("no JSON"),
                                       say("still none"))
    problems = [e["payload"]["problems"] for e in events if e["type"] == "plan"]
    assert "M1: 999 is not from the facts, the goal, the procedure or the tools" in problems[0]
    assert "Fix these problems" in llm.requests[-1]["messages"][-1]["content"] and len(problems) == 3
    assert report["status"] == "unverified" and not llm.replies


def plan_with(**milestone):
    return Plan.model_validate({**PLAN, "milestones": [{**PLAN["milestones"][0], **milestone}, *PLAN["milestones"][1:]]})


@pytest.mark.parametrize("plan, problem", [
    (plan_with(sop_step="SP-1"), "M1: sop_step 'SP-1' is not a step of process-invoice"),
    (plan_with(predicates=[{"read": "list_invoices", "args": {"colour": "red"}}]), "list_invoices args: colour: Extra"),
    (plan_with(predicates=[{"read": "list_invoices", "args": {"status": "any"}}]), "list_invoices args: status: Input"),
    (plan_with(predicates=[{"read": "list_invoices", "expect": {"colour": "red"}}]), "rows have no field 'colour'"),
    (plan_with(predicates=[{"read": "submit_invoice"}]), "'submit_invoice' is not an API read tool"),
    (plan_with(predicates=[{"read": "list_invoices", "where": {"vendor_name": "Sharma Logistics Pvt Ltd"},
                            "expect": {"status": "pending"}}]), "M1: status='pending' is not one of ['draft', "),
    (plan_with(predicates=[{"read": "list_invoices", "where": {"invoice_no": "INV-4040"}}]), "'INV-4040' is not from"),
    (Plan(sop_id="process-invoice"), "give 1 to 7 milestones"),
    (plan_with(sop_step="PI-1"), "M1: PI-1 writes nothing; only a count 0 check may cite it"),
    (Plan.model_validate({**PLAN, "milestones": [PLAN["milestones"][0], {
        "id": "M2", "target": "not there yet", "sop_step": "PI-8", "predicates": [{**PLAN["milestones"][0]["predicates"][0],
                                                                                  "count": 0}]}]}),
     "M2: count 0 on list_invoices rows another milestone expects to exist"),
    (plan_with().model_copy(update={"not_applicable": {}}), "write step PI-7 needs a milestone or a not_applicable reason"),
    (plan_with().model_copy(update={"not_applicable": {"PI-7": " "}}), "write step PI-7 needs a milestone or a not_"),
    (Plan.model_validate({**PLAN, "milestones": PLAN["milestones"][:1], "not_applicable": {
        "PI-6": "handled by the ingestion pipeline", "PI-7": "x"}}),
     "write step PI-6 needs a milestone: the procedure does not make it optional"),  # D-195: an invented reason
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


@pytest.mark.parametrize("value, refused", [
    ("invoice.pdf", True),            # live T1 flaky_500: an invented file name (D-217)
    ("INV-1043.pdf", False),          # holds the fact INV-1043
    ("sharma_INV-1043.pdf", False),   # holds it too
    ("INV-10", False),                # a part of the fact
    ("Logistics", False),             # a part of the goal's vendor
    ("latest", False),                # from the request
    ("1.pdf", True),                  # a short value (an id) never sources a longer one
])
def test_a_contains_value_must_come_from_a_fact_the_goal_the_request_or_the_procedure(sandbox, value, refused):
    run = sandbox.run(plan=Plan(sop_id="process-invoice"))
    goal = GoalSpec(request=SHARMA, decision="proceed", sop_id="process-invoice",
                    fields=[Field(name="vendor", value="Sharma Logistics Pvt Ltd", source="probe")])
    facts = [Fact(name="invoice_no", raw="INV-1043", value="INV-1043", result=1),
             Fact(name="vendor_id", raw="1", value=1, result=1)]
    plan = plan_with(predicates=[{"read": "list_invoices", "where": {"invoice_no": "INV-1043"},
                                  "contains": {"source_file": [value]}}])
    problems = plan_errors(plan, run, goal, load_sops()["process-invoice"], facts)
    assert any(f"contains {value!r} is in no fact" in p for p in problems) is refused, problems
    drive(run, lambda run: asyncio.sleep(0))


def test_the_planner_reads_acmes_own_limits_from_the_policy_file_at_run_time(tmp_path):
    """D-217, live T6 and T7: a business approval planned for invoices under the limit. The limit reaches the planner
    from policies.yaml (the constant Acme's code is checked against), never from the prompt or the planner's code."""
    from agent.planner import PROMPT, company_rules
    from agent.policy.loader import POLICIES_PATH
    moved = tmp_path / "policies.yaml"
    moved.write_text(POLICIES_PATH.read_text().replace("equals: 5000000", "equals: 7500000"))
    (tmp_path / "mail_allowlist.yaml").write_text((POLICIES_PATH.parent / "mail_allowlist.yaml").read_text())
    assert {"APPROVAL_LIMIT_PAISE": 5000000} in [r.get("limits") for r in company_rules()]
    assert {"APPROVAL_LIMIT_PAISE": 7500000} in [r.get("limits") for r in company_rules(moved)]
    assert "5,000,000" not in PROMPT and "50,000" not in PROMPT and "company_rules" in PROMPT


def test_the_planner_brief_carries_the_company_rules(sandbox):
    report, llm, _ = operate_with(sandbox, SHARMA, gate("proceed"), calls(("find_vendors", {"q": "Sharma"})),
                                  calls(("facts_ready", VENDOR_FACT)), say(json.dumps(PLAN)), say("Done."),
                                  *[say(json.dumps(PLAN)), say("Done.")] * 3)
    planner = next(r for r in llm.requests if r["messages"][0]["content"].startswith("You write the plan"))
    assert '"APPROVAL_LIMIT_PAISE": 5000000' in planner["messages"][1]["content"]


def test_the_prompts_say_contains_is_per_row_and_judge_criteria_are_about_meaning():
    """D-217, live T3 (a list read per ticket) and T9 approve (a criterion naming the subject). These pin the text;
    whether the model follows it is what the live bench measures."""
    from agent.planner import PROMPT
    from agent.verifier.judge import PROMPT as JUDGE
    assert "`contains` checks text inside ONE row's field" in PROMPT and "need one predicate each" in PROMPT
    assert "about meaning and tone only" in PROMPT and "never which field must say it" in PROMPT
    assert "whatever field the criterion names" in JUDGE


def test_tidy_fixes_what_the_model_gets_wrong_every_time_and_says_so():
    """D-200, from the live T1, T3 and T9 plans: status "any", `contains` as a string, read-step milestones."""
    data = {"milestones": [
        {"id": "M1", "sop_step": "NV-1", "predicates": [{"read": "get_vendor", "args": {"vendor_id": 1}}]},
        {"id": "M2", "sop_step": "NV-4", "after": ["M1"], "target": "x" * 300, "predicates": [
            {"read": "list_mail", "args": {"folder": "outbox", "status": "any", "q": None},
             "contains": {"subject": "INV-1043"}, "expect": {"id": {"ref": "M1"}, "folder": "outbox"}}]},
        {"id": "M3", "sop_step": "NV-2", "predicates": [{"read": "list_mail", "count": 0}]}]}
    data["milestones"].append({"id": "M4", "sop_id": "NV-4", "predicates": [{"read": "list_mail"}]})
    data["milestones"].append({"id": "M5", "predicates": [{"read": "list_mail"}]})  # no step: validation says so
    assert tidy(data, load_sops()["notify-vendor"]) == ["dropped M1: NV-1 writes nothing",
                                                        "M4: sop_id NV-4 read as its sop_step"]
    assert [m["id"] for m in data["milestones"]] == ["M2", "M3", "M4", "M5"]  # a count 0 check may cite any step
    assert data["milestones"][2]["sop_step"] == "NV-4" and "sop_id" not in data["milestones"][2]
    assert len(data["milestones"][0]["target"]) == 200
    paise = {"milestones": [{"id": "M1", "sop_step": "PI-5", "predicates": [
        {"read": "list_invoices", "where": {"status": "any"}, "expect": {"amount_paise": "4130000", "po_number": "42"}}]}]}
    tidy(paise, load_sops()["process-invoice"])
    assert paise["milestones"][0]["predicates"][0]["where"] == {}
    assert paise["milestones"][0]["predicates"][0]["expect"] == {"amount_paise": 4_130_000, "po_number": "42"}
    assert data["milestones"][0]["after"] == [] and data["milestones"][0]["predicates"][0] == {  # where: "any" dropped
        "read": "list_mail", "args": {"folder": "outbox"}, "contains": {"subject": ["INV-1043"]},
        "where": {"id": {"ref": "M1"}}, "expect": {"folder": "outbox"}}


def test_a_messy_plan_is_tidied_and_accepted_on_the_first_attempt(sandbox):
    messy = json.loads(json.dumps(PLAN))
    messy["milestones"][0]["predicates"][0]["args"]["status"] = "any"
    messy["milestones"].insert(0, {"id": "M9", "target": "the email is found", "sop_step": "PI-1",
                                   "predicates": [{"read": "list_mail", "args": {"folder": "inbox"}}]})
    _, _, events = operate_with(sandbox, SHARMA, gate("proceed"), calls(("find_vendors", {"q": "Sharma"})),
                                calls(("facts_ready", VENDOR_FACT)), say(json.dumps(messy)), say("Stop."),
                                *[say(json.dumps(PLAN)), say("Stop.")] * 3)
    first = next(e["payload"] for e in events if e["type"] == "plan")
    assert first["problems"] == [] and first["tidied"] == ["dropped M9: PI-1 writes nothing"]
    assert [m["id"] for m in first["plan"]["milestones"]] == ["M1", "M2"]
    assert "status" not in first["plan"]["milestones"][0]["predicates"][0]["args"]


def test_list_reads_the_gather_phase_skipped_are_sampled_so_their_fields_are_checked(sandbox):
    """D-201, live T9:approve: the gather phase never listed mail, so a plan expecting a mail row's `status` (mail
    rows have none) went unchecked and failed a correct run. Now the outbox read's real fields are known."""
    request = "Email Sharma Logistics that invoice INV-1043 is under review."
    mail = lambda expect: {"sop_id": "notify-vendor", "milestones": [{  # noqa: E731
        "id": "M1", "target": "one email to Sharma", "sop_step": "NV-4", "predicates": [{
            "read": "list_mail", "args": {"folder": "outbox"}, "where": {"to_addr": "accounts@sharmalogistics.example"},
            "expect": expect}]}]}
    fact = {"facts": [{"name": "to", "raw": "accounts@sharmalogistics.example", "result": 1}]}
    _, _, events = operate_with(sandbox, request, gate("proceed", "notify-vendor"), calls(("get_vendor", {"vendor_id": 1})),
                                calls(("facts_ready", fact)), say(json.dumps(mail({"status": "sent"}))),
                                say(json.dumps(mail({}))), say("Stop."), *[say(json.dumps(mail({}))), say("Stop.")] * 3)
    problems = [e["payload"]["problems"] for e in events if e["type"] == "plan"]
    assert any("list_mail rows have no field 'status'" in p for p in problems[0]) and problems[1] == []


def test_unseen_reads_advertise_the_row_fields_their_rows_have(sandbox):
    """A mail row has `to_addr`, not the send tool's `to` (live T9's planner wrote where {"to": ...})."""
    run = sandbox.run(plan=Plan(sop_id="notify-vendor"))
    fields = {t["read"]: t["row_fields"] for t in read_tools(run, {})}
    assert "to_addr" in fields["list_mail"] and "to" not in fields["list_mail"]
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


# --- replan (register 2.5, 2.6, N.182) -----------------------------------------------------------------------------

def two_milestones(m2=None, m1=None):
    base = [{"id": "M1", "target": "Sharma is in the vendor master", "sop_step": "PI-2",
             "predicates": [{"read": "find_vendors", "args": {"q": "Sharma"}, "where": {"name": "Sharma Logistics Pvt Ltd"}}]},
            {"id": "M2", "target": "INV-1012 is paid", "sop_step": "PI-5",
             "predicates": [{"read": "list_invoices", "where": {"invoice_no": "INV-1012"}, "expect": {"status": "paid"}}]}]
    base[0] |= m1 or {}
    base[1]["predicates"][0] |= m2 or {}
    return Plan.model_validate({**PLAN, "milestones": base})


@pytest.mark.parametrize("change, problem", [
    (dict(m2={"count": 0}), "M2: correct only how its rows are found"),                # loosened count
    (dict(m2={"expect": {"status": "approved"}}), "M2: correct only how its rows are found"),  # status changed
    (dict(m2={"expect": {}}), "M2: correct only how its rows are found"),             # assertion dropped
    (dict(m1={"target": "a vendor exists"}), "M1 is met: keep it exactly as it was"),  # met milestone changed
    (dict(m2={"where": {"invoice_no": "INV-0987"}}), None),                             # a lookup fixed: allowed
    (dict(m2={"args": {"vendor": 1}}), None),
])
def test_a_replan_may_correct_only_how_an_unmet_milestones_rows_are_found(change, problem):
    problems = replan_errors(two_milestones(), two_milestones(**change), {"M2"})
    assert (problems == []) if problem is None else any(problem in p for p in problems), problems


def test_a_replan_may_not_drop_an_unmet_milestone_but_may_add_one():
    old = two_milestones()
    dropped = Plan.model_validate({**PLAN, "milestones": [old.milestones[0].model_dump()]})
    assert replan_errors(old, dropped, {"M2"}) == ["M2 was dropped: keep it exactly as it was"]
    extra = {"id": "M3", "target": "x", "sop_step": "PI-5", "predicates": [{"read": "list_invoices"}]}
    added = Plan.model_validate({**PLAN, "milestones": [m.model_dump() for m in old.milestones] + [extra]})
    assert replan_errors(old, added, {"M2"}) == []


def test_a_replan_that_corrects_a_lookup_lets_the_run_pass(sandbox):
    """The first plan looks for INV-1012 under the wrong vendor (0 rows); the replan corrects the lookup only."""
    facts = {"facts": [{"name": "invoice_no", "raw": "INV-1012", "result": 1},
                       {"name": "vendor_name", "raw": "Sharma Logistics Pvt Ltd", "result": 1},
                       {"name": "other_vendor", "raw": "Rao Packaging Industries", "result": 1}]}
    one = lambda vendor: {**PLAN, "milestones": [{"id": m, "target": "INV-1012 is paid", "sop_step": step,  # noqa: E731
        "predicates": [{"read": "list_invoices", "where": {"invoice_no": "INV-1012", "vendor_name": vendor},
                        "expect": {"status": "paid"}}]} for m, step in (("M1", "PI-5"), ("M2", "PI-6"))]}
    report, llm, _ = operate_with(sandbox, SHARMA, gate("proceed"), calls(("list_invoices", {})),
                                  calls(("facts_ready", facts)), say(json.dumps(one("Rao Packaging Industries"))),
                                  say("Done."), say(json.dumps(one("Sharma Logistics Pvt Ltd"))), say("Done."))
    assert report["status"] == "completed" and not llm.replies
    assert [(r["replan"], r["changed"]) for r in report["replans"]] == [(1, ["M1", "M2"])] and report["escalation"] is None


def test_a_replan_that_also_rewrites_a_met_milestone_keeps_the_met_one_frozen(sandbox):
    """D-215, live T3: the replan corrected the unmet milestone but also rewrote a met one, was refused twice and the
    run escalated. Met milestones are now kept as they were (2.6) and the correction is used."""
    facts = {"facts": [{"name": "invoice_no", "raw": "INV-1012", "result": 1},
                       {"name": "vendor_name", "raw": "Sharma Logistics Pvt Ltd", "result": 1},
                       {"name": "other_vendor", "raw": "Rao Packaging Industries", "result": 1}]}
    step = lambda m, s, vendor, target="INV-1012 is paid": {"id": m, "target": target, "sop_step": s,  # noqa: E731
        "predicates": [{"read": "list_invoices", "where": {"invoice_no": "INV-1012", "vendor_name": vendor},
                        "expect": {"status": "paid"}}]}
    first = {**PLAN, "milestones": [step("M1", "PI-5", "Sharma Logistics Pvt Ltd"),
                                    step("M2", "PI-6", "Rao Packaging Industries")]}
    second = {**PLAN, "milestones": [step("M1", "PI-5", "Rao Packaging Industries", "rewritten"),
                                     step("M2", "PI-6", "Sharma Logistics Pvt Ltd")]}
    report, llm, _ = operate_with(sandbox, SHARMA, gate("proceed"), calls(("list_invoices", {})),
                                  calls(("facts_ready", facts)), say(json.dumps(first)), say("Done."),
                                  say(json.dumps(second)), say("Done."))
    assert report["status"] == "completed" and not llm.replies
    assert [(r["replan"], r["changed"]) for r in report["replans"]] == [(1, ["M2"])]


def test_tidy_passes_a_where_value_for_an_enum_arg_as_that_arg_too(sandbox):
    """D-215, live T3: `folder: outbox` in `where` only, so list_mail read the inbox and never saw the sent mail."""
    registry = sandbox.run().registry
    data = {"milestones": [{"id": "M3", "target": "welcome mail sent", "sop_step": "OE-5", "predicates": [
        {"read": "list_mail", "where": {"folder": "outbox", "to_addr": "x@acme.example"}},
        {"read": "list_mail", "args": {"folder": "inbox"}, "where": {"folder": "outbox"}},
        {"read": "list_mail", "where": {"folder": "trash"}}]}]}
    notes = tidy(data, None, registry)
    preds = data["milestones"][0]["predicates"]
    assert preds[0]["args"] == {"folder": "outbox"} and preds[0]["where"]["folder"] == "outbox"
    assert preds[1]["args"] == {"folder": "inbox"} and preds[2]["args"] == {}  # an explicit arg wins; no bad value
    assert notes == ["M3: list_mail where folder='outbox' also passed as its arg"]
    assert tidy({"milestones": [{"id": "M1", "predicates": [{"read": "list_mail", "where": {"folder": "outbox"}}]}]},
                None) == []  # no registry: unchanged behaviour


def test_an_act_phase_after_a_replan_does_not_write_the_same_record_again(sandbox):
    """Register 2.7, live T8 (four approval requests): the entry made before the replan is not made again."""
    entry = {"vendor_id": 1, "invoice_no": "EX-1", "invoice_date": "2026-10-01", "due_date": "2026-10-31",
             "amount_paise": 100_000, "tax_paise": 0}
    report, llm, _ = operate_with(sandbox, SHARMA, gate("proceed"), calls(("find_vendors", {"q": "Sharma"})),
                                  calls(("facts_ready", VENDOR_FACT)), say(json.dumps(PLAN)),
                                  calls(("get_vendor", {"vendor_id": 1})), calls(("submit_invoice", entry)), say("Done."),
                                  say(json.dumps(PLAN)), calls(("submit_invoice", {**entry, "invoice_no": "EX-2"})),
                                  say("Stop."), *[say(json.dumps(PLAN)), say("Stop.")] * 2)
    assert "submit_invoice already succeeded in this run" in json.dumps(llm.requests)
    assert sandbox.rows("SELECT COUNT(*) FROM invoices WHERE invoice_no LIKE 'EX-%'")[0][0] == 1


def test_no_replan_after_a_failed_postcondition_an_unexplained_change_or_a_stopped_executor(sandbox):
    unmet = MilestoneCheck(id="M1", target="t", ok=False, critical=True, awaits_business_approval=False)
    assert _plan_failed(Verdict(status="failed", milestones=[unmet])) == [unmet]
    assert _plan_failed(Verdict(status="failed", milestones=[unmet], postconditions=[Check(name="p", ok=False)])) == []
    assert _plan_failed(Verdict(status="completed_with_exceptions", milestones=[unmet])) == []

    def down(messages):
        raise LLMUnavailable("every configured model failed")
    report, llm, events = operate_with(sandbox, SHARMA, gate("proceed"), calls(("find_vendors", {"q": "Sharma"})),
                                       calls(("facts_ready", VENDOR_FACT)), say(json.dumps(PLAN)), down)
    assert report["status"] == "failed" and [e["type"] for e in events].count("plan") == 1
    assert report["replans"] == [] and report["escalation"] is None


# --- resume after an action approval (P.5) -----------------------------------------------------------------------

def test_a_rejected_action_ends_blocked_and_rolls_back_what_the_run_wrote(sandbox):
    """Onboarding: the employee is created, then an external email is held (ORG-005) and rejected, so the run ends
    blocked_by_policy and the rollback cancels the employee the run created (passes ORG-008: the run's own row).
    The card names the recipient's source; the model never sees an approval id."""
    async def approver(approval_id):
        ApprovalStore(sandbox.store).decide(approval_id, "rejected", "tester")
        return "rejected"
    request = "Onboard Priya Nair, she joins Monday."
    plan = {"sop_id": "onboard-employee", "milestones": [{
        "id": m, "target": "Priya Nair is onboarded", "sop_step": step,
        "predicates": [{"read": "find_employees", "args": {"q": "Priya Nair"}}]} for m, step in (
            ("M1", "OE-3"), ("M2", "OE-4"), ("M3", "OE-5"))]}
    employee = {"name": "Priya Nair", "email": "priya.nair@acme.example", "role": "Analyst", "department": "Finance",
                "manager_id": 1, "start_date": "2026-10-12"}
    mail = {"to": "priya@gmail.example", "subject": "Welcome", "body": "Welcome aboard."}
    llm = FakeLLM(gate("proceed", sop="onboard-employee"),
                  calls(("facts_ready", {"facts": [{"name": "employee_name", "raw": "Priya Nair", "result": 0}]})),
                  say(json.dumps(plan)), calls(("create_employee", employee)), calls(("send_mail", mail)))
    report = asyncio.run(operate(request, NOW, store=sandbox.store, config=CONFIG, approver=approver,
                                 transport=httpx.ASGITransport(app=sandbox.app), make_llm=lambda run: llm))
    assert report["status"] == "blocked_by_policy"
    assert [a["decision"] for a in report["action_approvals"]] == ["rejected"]
    assert report["action_approvals"][0]["predicted"]["sources"] == {"to": "not seen in any read"}
    assert [(u["tool"], u["ok"]) for u in report["rollback"]["undone"]] == [("cancel_employee", True)]
    assert [tuple(r) for r in sandbox.rows("SELECT status FROM employees WHERE name = 'Priya Nair'")] == [("cancelled",)]
    assert sandbox.rows("SELECT COUNT(*) FROM mail WHERE folder = 'outbox'")[0][0] == 0
    assert report["action_approvals"][0]["approval_id"] not in json.dumps([r["messages"] for r in llm.requests])


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
    assert again["run_id"] != first["run_id"] and len(files) == 7  # gate, 2 gather turns, plan, act, replan, act again
    assert sorted(p.name for p in (tmp_path / "cassettes").rglob("*.json")) == files
    assert (again["status"], again["narrative"]) == (first["status"], first["narrative"]) == ("failed", ["All done."] * 4)
    stored = "".join(p.read_text() for p in (tmp_path / "cassettes").rglob("*.json"))
    assert first["run_id"] not in stored and "gk-test-key-1" not in stored
