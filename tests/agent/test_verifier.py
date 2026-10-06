"""The verifier (agent/verifier/): the status table, each layer passing and failing, polling through read lag,
crash and timeout, and layer 3's grouping of audit rows by ts. Register 4.4, 5.3, 6.1, 6.4, 6.7, 6.9, 6.10;
D-134, D-135; N.153, N.154, N.162. Runs use a real in-process Acme (tests/agent/acme_fixtures.py)."""

import asyncio

import pytest

from agent.plan import Milestone, Plan, Predicate, Ref
from agent.scripted import Step, run_script
from agent.verifier import Evidence, decide_status, verify
from agent.verifier.side_effects import Write, match
from agent.verifier.side_effects import side_effects as layer3_side_effects
from bench.oracles import oracle_for
from tests.agent.acme_fixtures import drive, sandbox  # noqa: F401  (sandbox is a fixture)

NOW = "2026-10-07T10:30:00+05:30"


# --- decide_status: one row of the table each, and the order between them -----------------------------------------

@pytest.mark.parametrize("evidence, status", [
    (Evidence(asked=True, wrote=True), "failed"),
    (Evidence(infeasible=True, wrote=True), "failed"),
    (Evidence(rejected=True), "blocked_by_policy"),
    (Evidence(refused=True), "blocked_by_policy"),
    (Evidence(pending=True), "paused_for_action_approval"),
    (Evidence(asked=True), "needs_clarification"),
    (Evidence(infeasible=True), "infeasible"),
    (Evidence(), "unverified"),                                   # nothing to check is never "completed" (6.10)
    (Evidence(has_milestones=True, unverifiable=True), "unverifiable"),
    (Evidence(has_milestones=True, failures=["x"]), "failed"),
    (Evidence(has_milestones=True, minor=["x"]), "completed_with_exceptions"),
    (Evidence(has_milestones=True, awaits=True), "awaiting_business_approval"),
    (Evidence(has_milestones=True), "completed"),
    # order: a rejection beats a pause, a failure beats an exception, a failure beats awaiting approval
    (Evidence(rejected=True, pending=True), "blocked_by_policy"),
    (Evidence(has_milestones=True, failures=["x"], minor=["y"], awaits=True), "failed"),
    (Evidence(pending=True, asked=True), "paused_for_action_approval"),
])
def test_decide_status_follows_the_table(evidence, status):
    assert decide_status(evidence)[0] == status


# --- whole runs on a real Acme --------------------------------------------------------------------------------------

def _oracle(sandbox, run_id, *, seed="base", plan=None, after=None, read_lag=None):
    sandbox.admin_call("POST", "/__admin/reset", seed=seed, now=NOW)
    oracle = oracle_for(run_id)
    run = sandbox.run(plan=plan or oracle.plan)
    if read_lag is not None:
        run.client.read_lag = read_lag

    async def body(run):
        await run_script(run, oracle.steps)
        if after:
            await after(run)
        return await verify(run)
    return run, drive(run, body)


def test_a_correct_run_is_completed_and_logged(sandbox):
    run, verdict = _oracle(sandbox, "T2")
    assert verdict.status == "completed", verdict.reasons
    assert [c.ok for c in verdict.postconditions] == [True] and verdict.side_effects.unexplained == []
    assert verdict.side_effects.wrote and [m.ok for m in verdict.milestones] == [True]
    logged = [e for e in sandbox.store.events(run.run_id) if e["type"] == "verifier_result"]
    assert len(logged) == 1 and logged[0]["payload"]["status"] == "completed"


def test_refs_carry_an_earlier_milestones_row_and_awaiting_approval_is_reported(sandbox):
    _, verdict = _oracle(sandbox, "T1")
    assert verdict.status == "awaiting_business_approval" and all(m.ok for m in verdict.milestones)


def test_a_wrong_value_fails_the_milestone(sandbox):
    plan = oracle_for("T2").plan.model_copy(deep=True)
    wrong = Plan(sop_id=plan.sop_id, milestones=[Milestone(id="M1", target="wrong total", predicates=[
        Predicate(read="list_invoices", where={"invoice_no": "INV-2210"}, expect={"amount_paise": 1})])])
    _, verdict = _oracle(sandbox, "T2", plan=wrong)
    assert verdict.status == "failed" and "milestone M1 not met" in verdict.reasons[0]
    assert "amount_paise=1850000, expected 1" in verdict.milestones[0].checks[0].detail


def test_a_non_critical_miss_is_completed_with_exceptions(sandbox):
    plan = oracle_for("T2").plan
    extra = Milestone(id="M2", target="a note that never exists", critical=False, predicates=[
        Predicate(read="list_invoices", where={"invoice_no": "INV-NONE"})])
    _, verdict = _oracle(sandbox, "T2", plan=Plan(sop_id=plan.sop_id, milestones=[*plan.milestones, extra]))
    assert verdict.status == "completed_with_exceptions" and "M2" in verdict.reasons[0]


def test_an_unreadable_effect_is_unverifiable(sandbox):
    plan = Plan(sop_id="process-invoice", milestones=[Milestone(
        id="M1", target="the vendor got the letter", unverifiable_reason="paper mail has no read-back")])
    _, verdict = _oracle(sandbox, "T2", plan=plan)
    assert verdict.status == "unverifiable"


def test_a_planted_extra_write_is_unexplained(sandbox):
    async def plant(run):  # a write the run's log does not show: straight to Acme, past the registry
        employee = (await run.call("find_employees", {"q": "Neha"})).data["items"][0]["id"]
        await run.client._authed("POST", "/api/it-tickets", body={"type": "laptop", "employee_id": employee})
    _, verdict = _oracle(sandbox, "T2", after=plant)
    assert verdict.status == "failed" and any("unexplained change: it_ticket.create" in r for r in verdict.reasons)
    assert [r["unexplained"] for r in verdict.side_effects.rows if r["entity_type"] == "it_ticket"] == [True]


def test_a_claimed_write_with_no_row_fails_layers_1_and_3(sandbox):
    async def claim(run):  # what a silent drop looks like in the log: an ok write Acme never stored
        store, now = run.ctx.store, run.ctx.now.isoformat()
        store.append(run.run_id, "tool_call", now, {"tool": "create_it_ticket", "side_effect": "reversible_write",
                                                     "args": {"type": "laptop", "employee_id": 1}})
        store.append(run.run_id, "tool_result", now, {"tool": "create_it_ticket", "ok": True, "error_type": None,
                                                       "detail": "", "data": {"id": 999}})
    _, verdict = _oracle(sandbox, "T2", after=claim)
    assert verdict.status == "failed"  # through its postcondition: the claimed row cannot be read back
    assert any("postcondition create_it_ticket -> get_it_ticket" in r for r in verdict.reasons)
    assert verdict.notes == ["claimed but not in the audit log: create_it_ticket"]


def test_a_postcondition_compares_what_was_written(sandbox):
    async def misreport(run):  # the log claims a different total for the invoice the run really entered
        invoice = next(e for e in run.ctx.store.events(run.run_id) if e["type"] == "tool_result"
                       and e["payload"]["tool"] == "submit_invoice")["payload"]["data"]["id"]
        store, now = run.ctx.store, run.ctx.now.isoformat()
        store.append(run.run_id, "tool_call", now, {"tool": "submit_invoice", "side_effect": "reversible_write",
                                                     "args": {"invoice_no": "INV-2210", "amount_paise": 1}})
        store.append(run.run_id, "tool_result", now, {"tool": "submit_invoice", "ok": True, "error_type": None,
                                                       "detail": "", "data": {"id": invoice, "already_done": True}})
    _, verdict = _oracle(sandbox, "T2", after=misreport)
    assert any("amount_paise=1850000, wrote 1" in c.detail for c in verdict.postconditions)


def test_the_verifier_waits_out_read_lag_before_saying_not_met(sandbox, monkeypatch):
    monkeypatch.setenv("ACME_CHAOS_VISIBILITY_SECONDS", "1")
    sandbox.admin_call("POST", "/__admin/reset", seed="base", now=NOW)
    oracle = oracle_for("T2")
    run = sandbox.run(plan=oracle.plan)
    run.client.read_lag = 3.0

    async def body(run):
        sandbox.admin_call("POST", "/__admin/chaos", profile="delayed_write", seed=0)
        await run_script(run, [s for s in oracle.steps if s.key != "invoice_read_back"])
        return await verify(run)
    verdict = drive(run, body)
    assert verdict.status == "completed", verdict.reasons
    assert max(c.reads for c in [*verdict.postconditions, *verdict.milestones[0].checks]) > 1  # it polled


def test_absence_is_believed_only_after_the_read_lag(sandbox):
    import time
    started = time.perf_counter()
    _, verdict = _oracle(sandbox, "T6", read_lag=1.0)  # T6's M2: no payment request (count 0)
    assert verdict.status == "completed" and time.perf_counter() - started >= 1.0


def test_a_paused_run_is_not_polled_for_its_milestones(sandbox):
    _, verdict = _oracle(sandbox, "T9:none", seed="t9", read_lag=30.0)  # 30 s per poll if it tried
    assert verdict.status == "paused_for_action_approval" and verdict.milestones == []


def test_an_ask_after_a_write_is_failed(sandbox):
    sandbox.admin_call("POST", "/__admin/reset", seed="base", now=NOW)
    run = sandbox.run(plan=Plan(sop_id="onboard-employee"))
    employee = sandbox.rows("SELECT id FROM employees WHERE status = 'active' ORDER BY id")[0][0]

    async def body(run):
        await run_script(run, [Step("create_it_ticket", {"type": "laptop", "employee_id": employee}),
                               Step("ask_user", {"question": "Which one?"})])
        return await verify(run)
    assert drive(run, body).status == "failed"


def test_a_run_without_milestones_is_never_completed(sandbox):
    _, verdict = _oracle(sandbox, "T2", plan=Plan(sop_id="process-invoice"))
    assert verdict.status == "unverified"


def test_a_plan_that_reads_through_a_non_api_tool_is_unverified(sandbox):
    plan = Plan(sop_id="process-invoice", milestones=[Milestone(id="M1", target="x", predicates=[
        Predicate(read="browser_open", args={"path": "/invoices"})])])
    _, verdict = _oracle(sandbox, "T2", plan=plan)
    assert verdict.status == "unverified" and "not an API read tool" in verdict.reasons[0]


@pytest.mark.parametrize("failure", ["crash", "timeout"])
def test_a_verifier_that_cannot_finish_says_unverified(sandbox, monkeypatch, failure):
    async def broken(*args):
        if failure == "crash":
            raise RuntimeError("audit log gone")
        await asyncio.sleep(5)
    monkeypatch.setattr("agent.verifier.side_effects", broken)
    sandbox.admin_call("POST", "/__admin/reset", seed="base", now=NOW)
    oracle = oracle_for("T2")
    run = sandbox.run(plan=oracle.plan)

    async def body(run):
        await run_script(run, oracle.steps)
        return await verify(run, timeout=0.5)
    verdict = drive(run, body)
    assert verdict.status == "unverified" and ("audit log gone" in verdict.reasons[0] or "timed out" in verdict.reasons[0])


# --- layer 3 groups by ts: a cascading write is one write (D-135, N.162) ---------------------------------------------

def test_a_void_cascade_is_one_explained_group_on_a_real_run(sandbox):
    async def void(run):  # undo the run's own invoice: Acme also withdraws its pending approval, same ts
        invoice = next(e for e in run.ctx.store.events(run.run_id) if e["type"] == "tool_result"
                       and e["payload"]["tool"] == "submit_invoice")["payload"]["data"]["id"]
        assert (await run.call("void_invoice", {"invoice_id": invoice})).ok
    _, verdict = _oracle(sandbox, "T1", after=void)
    effects = verdict.side_effects
    actions = [r["action"] for r in effects.rows]
    assert {"invoice.void", "approval.withdraw"} <= set(actions)
    assert effects.unexplained == [] and effects.claimed_not_audited == []


def _row(id_, ts, entity, entity_id, action, actor="ops-agent"):
    return {"id": id_, "ts": ts, "entity_type": entity, "entity_id": entity_id, "action": action, "actor": actor,
            "channel": "api"}


def test_any_row_of_a_group_may_explain_it_even_when_the_cascade_comes_first():
    rows = [_row(1, "t1", "approval", 30, "approval.withdraw"), _row(2, "t1", "invoice", 9, "invoice.void")]
    effects = match(rows, [Write("void_invoice", "invoice", 9, False)], "ops-agent")
    assert effects.unexplained == [] and effects.claimed_not_audited == []


def test_two_writes_in_one_group_or_one_write_in_two_groups_do_not_match():
    one_group = [_row(1, "t1", "invoice", 9, "invoice.submit"), _row(2, "t1", "invoice", 10, "invoice.submit")]
    effects = match(one_group, [Write("submit_invoice", "invoice", 9, False),
                                Write("submit_invoice", "invoice", 10, False)], "ops-agent")
    assert effects.claimed_not_audited == [{"tool": "submit_invoice", "entity": "invoice", "id": 10}]
    split = [_row(1, "t1", "invoice", 9, "invoice.submit"), _row(2, "t2", "invoice", 9, "invoice.void")]
    assert len(match(split, [Write("submit_invoice", "invoice", 9, False)], "ops-agent").unexplained) == 1


def test_rows_by_other_actors_are_listed_never_unexplained():
    rows = [_row(1, "t1", "approval", 3, "approval.decide", actor="meera"),
            _row(2, "t2", "invoice", 4, "invoice.auto_approve", actor="system")]
    effects = match(rows, [], "ops-agent")
    assert effects.unexplained == [] and not effects.wrote and len(effects.rows) == 2


def test_a_gui_write_matches_by_entity_and_a_replay_needs_no_row():
    rows = [_row(1, "t1", "invoice", 42, "invoice.submit")]
    writes = [Write("browser_click", "invoice", None, False), Write("send_mail", "mail", 7, True)]
    effects = match(rows, writes, "ops-agent")
    assert effects.unexplained == [] and effects.claimed_not_audited == []


def test_layer_3_needs_the_runs_start_mark():
    with pytest.raises(RuntimeError, match="start mark"):
        asyncio.run(layer3_side_effects(None, [], []))


def test_a_run_that_ended_on_a_gate_deny_is_blocked_by_policy(sandbox):
    sandbox.admin_call("POST", "/__admin/reset", seed="base", now=NOW)
    run = sandbox.run(plan=oracle_for("T2").plan)
    steps = [Step("submit_invoice", {"vendor_id": 2, "invoice_no": "INV-X", "invoice_date": "2026-10-03",
                                     "due_date": "2026-11-02", "amount_paise": 100, "tax_paise": 0})]  # vendor unread

    async def body(run):
        await run_script(run, steps)
        return await verify(run)
    verdict = drive(run, body)
    assert verdict.status == "blocked_by_policy" and verdict.milestones == []


def test_a_write_explains_only_rows_of_its_own_entity():
    rows = [_row(1, "t1", "approval", 9, "approval.request")]
    effects = match(rows, [Write("submit_invoice", "invoice", 9, False)], "ops-agent")
    assert len(effects.unexplained) == 1 and effects.claimed_not_audited[0]["tool"] == "submit_invoice"


def test_a_gui_change_of_a_record_is_matched_by_its_id():
    rows = [_row(1, "t1", "invoice", 42, "invoice.attach_source"), _row(2, "t2", "invoice", 43, "invoice.void")]
    writes = [Write("browser_click", "invoice", 43, False), Write("browser_click", "invoice", 42, False)]
    assert match(rows, writes, "ops-agent").unexplained == []
    wrong = match(rows[:1], [Write("browser_click", "invoice", 99, False)], "ops-agent")
    assert len(wrong.unexplained) == 1


def test_writes_of_reads_a_gui_writes_entity_and_record_from_its_form_path():
    """D-155: a GUI submit's entity comes from its ui_forms entry, and its record id from the path when it changes one."""
    from agent.tools.api import load_catalog
    from agent.verifier.side_effects import writes_of
    def click(path):
        return ({"tool": "browser_click", "side_effect": "irreversible_write", "channel": "gui",
                 "request": {"method": "POST", "path": path}}, {"ok": True, "data": {"url": "/invoices"}})
    writes = writes_of(load_catalog(), [click("/invoices/42/attach-source"), click("/invoices/new"),
                                        click("/some/unknown/form")])
    assert [(w.entity, w.id) for w in writes] == [("invoice", 42), ("invoice", None), (None, None)]
