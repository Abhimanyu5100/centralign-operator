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


@pytest.mark.parametrize("task, chaos", [("T1", None), ("T2", None), ("T3", None), ("T4", None), ("T5", None),
                                         ("T6", None), ("T7", None), ("T8", None), ("T9:none", None),
                                         ("T9:approve", None), ("T9:reject", None), ("T1", "flaky_500"),
                                         ("T3", "commit_then_timeout"), ("T8", "session_expiry_at_step_5"),
                                         ("T8", "commit_then_timeout")])
def test_the_recorded_llm_run_replays_with_no_key_and_passes_its_checker(task, chaos, tmp_path, capsys):
    """OpenRouter run (bench/results/20261012-211028, D-216, D-224): every row replays to a pass. T9:none failed live
    (no valid plan) but replays approve's recording up to the hold: the same requests share one cassette (D-211)."""
    code, out = replay(task, chaos, tmp_path, capsys)
    assert code == 0 and "['replayed']" in out and "FAIL" not in out
