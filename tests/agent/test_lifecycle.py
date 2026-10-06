"""Run lifecycle and rollback (7.3, 5.4), checked from the harness side with /__admin/diff; the scripted agent."""

import asyncio

import pytest

from agent.lifecycle import rollback, run_writes
from agent.scripted import Step, run_script
from bench.oracles import oracle_for
from tests.agent.acme_fixtures import drive, sandbox  # noqa: F401  (sandbox is a fixture)

UNDONE = {"invoices": {"void"}, "approvals": {"withdrawn"}, "it_tickets": {"cancelled"}, "employees": {"cancelled"},
          "payments": {"cancelled"}}


def _oracle_then_rollback(sandbox, run_id: str, seed: str = "base"):
    sandbox.admin_call("POST", "/__admin/reset", seed=seed, now="2026-10-07T10:30:00+05:30")
    snapshot = sandbox.admin_call("POST", "/__admin/snapshot")["snapshot"]
    oracle = oracle_for(run_id)
    run = sandbox.run(plan=oracle.plan)  # the real policy gate: the oracle and every undo must pass it (ORG-008)

    async def body(run):
        script = await run_script(run, oracle.steps)
        assert script.ok, script.stopped_at
        return await rollback(run), await rollback(run)
    first, second = drive(run, body)
    return run, first, second, sandbox.admin_call("GET", "/__admin/diff", since=snapshot)["tables"]


@pytest.mark.parametrize("run_id,seed", [("T1", "base"), ("T3", "base"), ("T8", "t8")])
def test_rollback_restores_net_entity_state(sandbox, run_id, seed):
    run, first, second, diff = _oracle_then_rollback(sandbox, run_id, seed)
    assert first.ok and first.undone and not any(u["already_done"] for u in first.undone)
    for table, change in diff.items():
        assert change["removed"] == [], table
        if table == "audit_log":
            continue
        assert change["changed"] == [], f"{table}: a row the run did not create was changed"  # 5.4
        for row in change["added"]:
            if table == "mail":
                continue  # sent mail cannot be recalled; listed as not compensable below
            assert row["status"] in UNDONE[table], (table, row)
    # rolling back twice is safe: every compensation is already in effect
    assert second.ok and all(u["already_done"] for u in second.undone) and len(second.undone) == len(first.undone)
    assert second.not_compensable == first.not_compensable  # the first rollback's own undo calls are not "writes"


def test_rollback_undoes_in_reverse_and_lists_what_it_cannot_undo(sandbox):
    run, first, _, _ = _oracle_then_rollback(sandbox, "T3")
    assert [u["tool"] for u in first.undone] == ["cancel_it_ticket", "cancel_it_ticket", "cancel_employee"]
    assert [n["tool"] for n in first.not_compensable] == ["send_mail"]
    assert first.not_compensable[0]["reason"] == "sent mail cannot be recalled"
    # every compensation went through registry.call: logged with a policy decision
    events = sandbox.store.events(run.run_id)
    assert sum(1 for e in events if e["type"] == "policy_decision" and e["payload"]["tool"] == "cancel_employee") == 2


def test_run_writes_reads_only_successful_writes_from_the_log(sandbox):
    run = sandbox.run()

    async def body(run):
        await run.call("find_vendors", {})
        await run.call("void_invoice", {"invoice_id": 999})  # fails: not found
        await run.call("send_mail", {"to": "a@acme.example", "subject": "s", "body": "b"})
    drive(run, body)
    assert [tool for tool, _ in run_writes(sandbox.store.events(run.run_id))] == ["send_mail"]


def test_the_scripted_agent_stops_at_the_first_failure_and_returns_the_log(sandbox):
    run = sandbox.run()
    steps = [Step("find_vendors", {"q": "Rao"}),
             Step("get_vendor", lambda r: {"vendor_id": r["find_vendors"].data["items"][0]["id"]}, name="rao"),
             Step("get_vendor", {"vendor_id": 999}, name="missing"),
             Step("send_mail", {"to": "a@acme.example", "subject": "never", "body": "never sent"})]
    result = drive(run, lambda run: run_script(run, steps))
    assert (result.ok, result.stopped_at, list(result.results)) == (False, "missing", ["find_vendors", "rao", "missing"])
    assert result.results["rao"].data["id"] == 2 and result.results["missing"].error_type == "not_found"
    assert [e["payload"]["tool"] for e in result.events if e["type"] == "tool_call"] == [
        "list_audit", "find_vendors", "get_vendor", "get_vendor"]  # list_audit: the run's audit start mark
    assert sandbox.rows("SELECT COUNT(*) FROM mail WHERE folder = 'outbox'")[0][0] == 0


def test_two_runs_on_two_event_loops_each_get_their_own_session(sandbox):
    first, second = sandbox.run(), sandbox.run()
    assert drive(first, lambda run: run.call("list_files", {})).ok
    assert drive(second, lambda run: run.call("list_files", {})).ok  # N.135: no client bound to a closed loop
    assert first.client is not second.client and first.run_id != second.run_id
    assert asyncio.run(first.call("list_files", {})).ok  # a closed run's client reconnects lazily
