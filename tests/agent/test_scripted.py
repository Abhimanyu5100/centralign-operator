"""The scripted agent's endings, pause and resume (agent/scripted.py) against a real in-process Acme and the real
policy gate. Register P.5, 1.5, 1.7; Day 3 plan A4."""

from agent.lifecycle import Run
from agent.plan import Plan
from agent.policy.gate import PolicyGate
from agent.scripted import Step, resume_script, run_script
from tests.agent.acme_fixtures import drive, sandbox  # noqa: F401  (sandbox is a fixture)

NOTIFY = Plan(sop_id="notify-vendor")
VENDOR = Step("find_vendors", {"q": "Sharma"})
SEND = Step("send_mail", lambda r: {"to": r["find_vendors"].data["items"][0]["contact_email"],
                                    "subject": "Invoice INV-1043 is under review", "body": "Hello, under review."})
STEPS = [VENDOR, SEND, Step("list_mail", {"folder": "outbox"}, name="outbox")]


def _outbox(sandbox) -> int:
    return sandbox.rows("SELECT COUNT(*) FROM mail WHERE folder = 'outbox'")[0][0]


def test_start_run_uses_the_policy_gate(sandbox):
    run = sandbox.run(plan=NOTIFY)
    assert isinstance(run.registry.gate, PolicyGate) and run.ctx.sop_id == "notify-vendor"
    assert run.registry.approvals is run.approvals


def test_begin_records_the_audit_start_mark_once(sandbox):
    run = sandbox.run()

    async def body(run: Run):
        first, second = await run.begin(), await run.begin()
        return first, second
    first, second = drive(run, body)
    marks = [e for e in sandbox.store.events(run.run_id) if e["type"] == "run_start"]
    assert len(marks) == 1 and marks[0]["payload"]["audit_since"] == first.data["audit_since"]
    assert second.detail == "already started"


def test_ask_user_ends_the_script_and_nothing_after_it_runs(sandbox):
    steps = [VENDOR, Step("ask_user", {"question": "Which invoice?", "candidates": ["INV-1", "INV-2"]}), SEND]
    result = drive(sandbox.run(plan=NOTIFY), lambda run: run_script(run, steps))
    assert (result.ended, result.ok, list(result.results)) == ("asked", True, ["find_vendors", "ask_user"])
    assert result.results["ask_user"].data == {"question": "Which invoice?", "candidates": ["INV-1", "INV-2"]}
    assert _outbox(sandbox) == 0


def test_declare_infeasible_ends_the_script(sandbox):
    steps = [Step("find_vendors", {"q": "Nobody"}),
             Step("declare_infeasible", {"reason": "no such vendor", "evidence": ["find_vendors q=Nobody: 0"]}), SEND]
    result = drive(sandbox.run(plan=NOTIFY), lambda run: run_script(run, steps))
    assert result.ended == "infeasible" and "send_mail" not in result.results


def test_a_held_call_pauses_and_stays_paused_while_pending(sandbox):
    run = sandbox.run(plan=NOTIFY)

    async def body(run: Run):
        paused = await run_script(run, STEPS)
        return paused, await resume_script(run, STEPS, paused)
    paused, still = drive(run, body)
    assert (paused.ended, paused.stopped_at, paused.next_step) == ("paused", "send_mail", 1)
    approval = run.approvals.get(paused.approval_id)
    assert approval.status == "pending" and approval.policy_ids == ["ORG-005"]
    assert approval.predicted["args"]["to"] == "accounts@sharmalogistics.example"
    assert still.ended == "paused" and _outbox(sandbox) == 0


def test_after_approval_resume_re_runs_the_same_call_once_and_finishes(sandbox):
    run = sandbox.run(plan=NOTIFY)

    async def body(run: Run):
        paused = await run_script(run, STEPS)
        run.approvals.decide(paused.approval_id, "approved", by="meera")
        return paused, await resume_script(run, STEPS, paused)
    paused, done = drive(run, body)
    assert done.ended == "done" and done.results["send_mail"].ok and _outbox(sandbox) == 1
    assert run.approvals.get(paused.approval_id).consumed
    calls = [e["payload"]["tool"] for e in sandbox.store.events(run.run_id) if e["type"] == "tool_call"]
    assert calls.count("send_mail") == 2 and calls.count("find_vendors") == 1  # the held call, then its re-run


def test_after_rejection_resume_ends_blocked_and_sends_nothing(sandbox):
    run = sandbox.run(plan=NOTIFY)

    async def body(run: Run):
        paused = await run_script(run, STEPS)
        run.approvals.decide(paused.approval_id, "rejected", by="meera")
        return await resume_script(run, STEPS, paused)
    blocked = drive(run, body)
    assert blocked.ended == "blocked" and blocked.ok and _outbox(sandbox) == 0


def test_a_denied_call_ends_the_script_blocked(sandbox):
    steps = [Step("submit_invoice", {"vendor_id": 3, "invoice_no": "INV-X", "invoice_date": "2026-10-03",
                                     "due_date": "2026-11-02", "amount_paise": 100, "tax_paise": 0})]
    result = drive(sandbox.run(plan=Plan(sop_id="process-invoice")), lambda run: run_script(run, steps))
    assert result.ended == "blocked" and result.results["submit_invoice"].data["policy_ids"] == ["ORG-002"]
    assert sandbox.rows("SELECT COUNT(*) FROM invoices WHERE invoice_no = 'INV-X'")[0][0] == 0
