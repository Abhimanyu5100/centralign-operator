"""The run report (agent/report.py) beyond the contract test: a write Acme never stored is listed under side effects
(D-156), failures carry their class, recovered failures are listed without changing the status or showing a key
(7.2, 7.6), a run never verified is `unverified`, and the markdown fits one screen."""

import json

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


def test_t1_under_flaky_500_lists_the_recovered_server_errors_without_any_key(sandbox):
    """Both T1 writes fail once with a 500 inside the tool and then succeed: the report lists them as recovered
    (the keyed invoice retried, the keyless approval read back first), the status is unchanged and no idempotency
    key field appears anywhere in the report (7.6)."""
    sandbox.admin_call("POST", "/__admin/reset", seed="base", now=NOW)
    sandbox.admin_call("POST", "/__admin/chaos", profile="flaky_500", seed=0)
    oracle = oracle_for("T1")

    async def body(run):
        await run_script(run, oracle.steps)
        await verify(run)
        return build_report(run)
    report = drive(sandbox.run(plan=oracle.plan), body)
    assert report["status"] == "awaiting_business_approval" and report["failures"] == []
    assert [{k: r[k] for k in ("tool", "error_type", "kind", "count", "read_back")} for r in report["recovered"]] == [
        {"tool": "submit_invoice", "error_type": "server_error", "kind": "transient", "count": 1,
         "read_back": "retried once"},
        {"tool": "request_approval", "error_type": "server_error", "kind": "transient", "count": 1,
         "read_back": "read back: not written, so retried once"}]
    assert "idempotency" not in json.dumps(report)
    assert "- submit_invoice: server_error x1 (transient): retried once" in render_markdown(report)


def test_a_long_agent_summary_is_cut_at_a_word_boundary_and_says_so():
    """Live T6 report: the summary stopped mid-markup ("Attached the source file `"). Cut at a word and mark it."""
    from agent.report import _clip
    text = "Entered the invoice and attached the source file `mehta_INV-0091.pdf` to it " * 10
    cut = _clip(text, 120)
    assert cut.endswith(" ...") and len(cut) <= 124 and not cut[:-4].endswith(("`", " "))
    assert text.startswith(cut[:-4]) and _clip("short", 120) == "short"
