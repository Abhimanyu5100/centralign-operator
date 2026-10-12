"""The committed cassettes replay the recorded LLM runs end to end (`make run TASK=T1|T5 REPLAY=1`): a real Acme
child process, every API key removed from the agent's config, a fresh run id, and the task's checker (DB, side
effects, report status). Proves an evaluator can run the demo with no key (model plan M.6, register X.1, R.4)."""

import argparse
import asyncio

import pytest

from bench.run_agent import _main

pytestmark = pytest.mark.e2e


def replay(task, chaos, tmp_path, capsys) -> tuple[int, str]:
    args = argparse.Namespace(task=task, as_task=None, replay=True, chaos=chaos, chaos_seed=0, events=False, approve_wait=0.0,
                              store=str(tmp_path / "runs" / "runs.db"))
    code = asyncio.run(_main(args))
    return code, capsys.readouterr().out


@pytest.mark.parametrize("task, chaos", [("T2", None), ("T4", None), ("T5", None), ("T6", None), ("T7", None),
                                         ("T8", None), ("T9:none", None), ("T9:reject", None), ("T1", "flaky_500"),
                                         ("T3", "commit_then_timeout"), ("T8", "session_expiry_at_step_5"),
                                         ("T8", "commit_then_timeout")])
def test_the_recorded_llm_run_replays_with_no_key_and_passes_its_checker(task, chaos, tmp_path, capsys):
    """Day 6 revert run (bench/results/20261012-143613, D-216, D-220): every row whose live run passed replays to a pass."""
    code, out = replay(task, chaos, tmp_path, capsys)
    assert code == 0 and "['replayed']" in out and "FAIL" not in out


@pytest.mark.parametrize("task, chaos, status", [("T3", None, "needs_clarification"),
                                                 ("T9:approve", None, "failed")])
def test_a_run_that_failed_live_replays_to_the_same_measured_status(task, chaos, status, tmp_path, capsys):
    """Measured failures are kept, not hidden (D-216): no attempt of these rows passed in the revert run; the replay of
    the first attempt shows the same status (docs/EVALUATION.md, per-failure analysis)."""
    code, out = replay(task, chaos, tmp_path, capsys)
    assert code == 1 and "['replayed']" in out and "CassetteMiss" not in out and f"verifier: {status}" in out


def test_a_run_that_repeats_an_identical_request_replays_to_its_status_but_stops_early(tmp_path, capsys):
    """N.211: T1's live attempts each sent one identical replan request twice and got two replies; a cassette keeps
    one, so the replay reaches the live status (`failed`) by a shorter path and stops at a cassette miss."""
    code, out = replay("T1", None, tmp_path, capsys)
    assert code == 1 and "verifier: failed" in out and "CassetteMiss" in out
