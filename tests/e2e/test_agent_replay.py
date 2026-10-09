"""The committed cassettes replay the recorded LLM runs end to end (`make run TASK=T1|T5 REPLAY=1`): a real Acme
child process, every API key removed from the agent's config, a fresh run id, and the task's checker (DB, side
effects, report status). Proves an evaluator can run the demo with no key (model plan M.6, register X.1, R.4)."""

import argparse
import asyncio

import pytest

from bench.run_agent import _main

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("task, chaos", [("T1", None), ("T3", None), ("T4", None), ("T5", None), ("T9:none", None),
                                         ("T9:approve", None), ("T9:reject", None), ("T1", "flaky_500")])
def test_the_recorded_llm_run_replays_with_no_key_and_passes_its_checker(task, chaos, tmp_path, capsys):
    """Day 5 done-when: T3, T4 and T9 (every approver decision) pass in replay; T1 under flaky_500 recovers."""
    args = argparse.Namespace(task=task, replay=True, chaos=chaos, chaos_seed=0, events=False, approve_wait=0.0,
                              store=str(tmp_path / "runs" / "runs.db"))
    assert asyncio.run(_main(args)) == 0
    out = capsys.readouterr().out
    assert "['replayed']" in out and "FAIL" not in out
