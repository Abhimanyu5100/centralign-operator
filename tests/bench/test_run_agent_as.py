"""`make run TASK="<rewording>" AS_TASK=T1` (Day 6 held-out probe, D-218): an unknown task is refused before anything runs."""

import argparse
import asyncio

import pytest

from bench.run_agent import _main


def test_an_unknown_as_task_is_refused_before_acme_starts():
    args = argparse.Namespace(task="Please enter Sharma's newest bill.", as_task="T99", replay=True, chaos=None,
                              chaos_seed=0, events=False, approve_wait=0.0, store=None)
    with pytest.raises(SystemExit, match="--as T99: no such task run"):
        asyncio.run(_main(args))
