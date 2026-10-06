"""Oracles end to end: a real Acme server (uvicorn on localhost, bench/live.py), the scripted agent through the
registry and the pass-through gate, the task's checker on the result (Day 2.2).

- every oracle run's end state passes its DB checker with chaos off (report checks stay pending until Day 3);
- `commit_then_timeout` (3.5): the first IT ticket commits but its response is held past the client timeout; the
  tool reads back, reports already_done and Acme holds exactly one ticket of each type;
- `flaky_500` seed 0 (attempts 1 and 2 fail before writing): exactly one invoice and one approval request;
- rollback on the live server restores net entity state (/__admin/diff since the snapshot).
"""

import asyncio
import sqlite3

import pytest

from agent.lifecycle import rollback, start_run
from agent.scripted import run_script
from bench import tasks
from bench.live import run_oracle, serve
from bench.oracles import oracle_for

pytestmark = pytest.mark.e2e

RUN_IDS = [run.run_id for task in tasks.load_all() for run in tasks.runs(task)]


@pytest.fixture(scope="module")
def acme():
    with serve(env={"ACME_CHAOS_TIMEOUT_DELAY_SECONDS": "3"}) as server:
        yield server


def _oracle(acme, run_id, **kwargs):
    task = tasks.load(run_id.partition(":")[0])
    run = next(r for r in tasks.runs(task) if r.run_id == run_id)
    return asyncio.run(run_oracle(acme, task, run, oracle_for(run_id), **kwargs))


def _count(acme, sql) -> int:
    conn = sqlite3.connect(acme.db_path)
    try:
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


@pytest.mark.parametrize("run_id", RUN_IDS)
def test_every_oracle_passes_its_db_checker_with_chaos_off(acme, run_id):
    result = _oracle(acme, run_id)
    assert result.script.ok, result.script.stopped_at
    assert result.result.passed, [(c.name, c.detail) for c in result.result.checks if not c.ok]
    assert result.pending and result.pending[0].startswith("report: status")  # never counted as passed


def test_commit_then_timeout_reads_back_instead_of_writing_twice(acme):
    result = _oracle(acme, "T3", chaos="commit_then_timeout", timeout=0.5)
    assert result.chaos_fired is True and result.passed
    laptop = result.script.results["laptop_ticket"]
    assert laptop.data["already_done"] is True and laptop.data["attempts"][0] == "attempt 1: timeout"
    assert result.script.results["accounts_ticket"].data["already_done"] is False
    assert _count(acme, "SELECT COUNT(*) FROM it_tickets t JOIN employees e ON e.id = t.employee_id "
                        "WHERE e.email = 'priya.nair@acme.example'") == 2


def test_flaky_500_leaves_one_invoice_and_one_approval(acme):
    result = _oracle(acme, "T1", chaos="flaky_500", chaos_seed=0)
    assert result.chaos_fired is True and result.passed
    assert result.script.results["submit_invoice"].data["attempts"] == ["attempt 1: server_error", "attempt 2: ok"]
    assert _count(acme, "SELECT COUNT(*) FROM invoices WHERE invoice_no = 'INV-1043'") == 1
    assert _count(acme, "SELECT COUNT(*) FROM approvals WHERE status = 'pending'") == 1


def test_session_expiry_recovers_with_one_login(acme):
    result = _oracle(acme, "T8", chaos="session_expiry_at_step_5")
    assert result.chaos_fired is True and result.passed


def test_rollback_on_the_live_server_restores_net_entity_state(acme):
    task = tasks.load("T1")
    acme.admin("POST", "/__admin/reset", seed=task.seed, now=task.now)
    snapshot = acme.admin("POST", "/__admin/snapshot")["snapshot"]
    from datetime import datetime
    run = start_run(task.request, datetime.fromisoformat(task.now), config=acme.agent_config())

    async def body():
        try:
            assert (await run_script(run, oracle_for("T1").steps)).ok
            return await rollback(run)
        finally:
            await run.close()
    report = asyncio.run(body())
    diff = acme.admin("GET", "/__admin/diff", since=snapshot)["tables"]
    assert report.ok and [u["tool"] for u in report.undone] == ["withdraw_approval", "void_invoice"]
    assert {t: [r["status"] for r in c["added"]] for t, c in diff.items() if t != "audit_log"} == {
        "invoices": ["void"], "approvals": ["withdrawn"]}
    assert all(not c["changed"] and not c["removed"] for c in diff.values())
