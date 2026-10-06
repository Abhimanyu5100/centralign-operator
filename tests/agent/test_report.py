"""The run report (agent/report.py) beyond the contract test: a write Acme never stored is listed under side effects
(D-156), failures carry their class, a run never verified is `unverified`, and the markdown fits one screen."""

from agent.report import build_report, render_markdown
from agent.scripted import run_script
from agent.verifier import verify
from bench.oracles import oracle_for
from tests.agent.acme_fixtures import drive, sandbox  # noqa: F401  (sandbox is a fixture)

NOW = "2026-10-07T10:30:00+05:30"


def _t2(sandbox, after=None, verified=True):
    sandbox.admin_call("POST", "/__admin/reset", seed="base", now=NOW)
    oracle = oracle_for("T2")
    run = sandbox.run(plan=oracle.plan)

    async def body(run):
        await run_script(run, oracle.steps)
        if after:
            await after(run)
        if verified:
            await verify(run)
        return build_report(run)
    return drive(run, body)


def test_a_claimed_write_acme_never_stored_is_listed_under_side_effects(sandbox):
    async def claim(run):
        store, now = run.ctx.store, run.ctx.now.isoformat()
        store.append(run.run_id, "tool_call", now, {"tool": "create_it_ticket", "side_effect": "reversible_write",
                                                     "args": {"type": "laptop", "employee_id": 1}})
        store.append(run.run_id, "tool_result", now, {"tool": "create_it_ticket", "ok": True, "error_type": None,
                                                       "detail": "", "data": {"id": 999}})
    report = _t2(sandbox, claim)
    claimed = [s for s in report["side_effects"] if s.get("claimed_not_audited")]
    assert claimed == [{"table": "it_tickets", "entity_id": 999, "action": "claimed, but not in Acme's audit log",
                        "tool": "create_it_ticket", "claimed_not_audited": True}]
    assert "claimed, but not in Acme's audit log" in render_markdown(report)


def test_side_effects_name_acmes_tables_and_failures_carry_their_class(sandbox):
    async def fail(run):
        await run.call("get_invoice", {"invoice_id": 99999})
    report = _t2(sandbox, fail)
    assert {s["table"] for s in report["side_effects"]} == {"invoices"}
    assert [(f["tool"], f["kind"]) for f in report["failures"]] == [("get_invoice", "fix_or_replan")]


def test_a_run_that_was_never_verified_reports_unverified(sandbox):
    report = _t2(sandbox, verified=False)
    assert report["status"] == "unverified" and report["status_reasons"] == ["the verifier never ran"]


def test_the_markdown_leads_with_the_status_and_stays_short(sandbox):
    text = render_markdown(_t2(sandbox))
    assert text.splitlines()[0].endswith(": completed") and len(text.splitlines()) < 40
