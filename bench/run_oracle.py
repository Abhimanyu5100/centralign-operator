"""`make oracle TASK=T1 [CHANNEL=gui] [CHAOS=profile] [CHAOS_SEED=0] [LIVE=1] [EVENTS=1]`: reset Acme, set chaos, run the
task's oracle through the scripted agent, then the task's checker; print pass/fail per predicate.

By default Acme runs in-process on a temporary database (bench/live.py); LIVE=1 targets `make acme` (needs
ACME_ADMIN_TOKEN exported). TASK=all runs T1-T9. Each run is verified, its report written to
runs/<run_id>/report.{json,md} and checked (status and report checks). Runs go to the bench run store
(runs/bench.db), not the operator's (N.164). Exit code 1 when a chaos-off run fails its checker.
"""

import argparse
from pathlib import Path
import asyncio
import json
import sys

from agent.store import RunStore
from bench import tasks
from bench.live import BENCH_STORE, HARNESS_HTTP_TIMEOUT, HARNESS_SERVER_ENV, OracleRun, live, run_oracle, serve
from bench.oracles import oracle_for


def _print(o: OracleRun, store: RunStore, events: bool) -> None:
    steps = len(o.script.results)
    at = o.script.results.get(o.script.stopped_at) if o.script.stopped_at else None
    stopped = f" at {o.script.stopped_at}: {at.detail[:160]}" if at else ""
    chaos = "" if o.chaos_fired is None else f", chaos fired: {'yes' if o.chaos_fired else 'no'}"
    approver = "".join(f", {d['approval_id']} {d['status']} by the approver" for d in o.decisions)
    print(f"\n== {o.run.run_id}  (agent run {o.agent_run_id}: {steps} step(s), ended {o.script.ended}{stopped}"
          f"{approver}{chaos})")
    v = o.verdict
    mark = "PASS" if v.status == o.run.expected_outcome else "FAIL"
    print(f"  {mark}  verifier: {v.status} (expected {o.run.expected_outcome})"
          f"{'  ' + '; '.join(v.reasons)[:300] if v.reasons else ''}")
    for check in o.result.checks:
        print(f"  {'PASS' if check.ok else 'FAIL'}  {check.name}{'  ' + check.detail if check.detail else ''}")
    print(f"  checkpoints {o.result.checkpoint_score:.0%}")
    for key, result in o.script.results.items():
        if result.data.get("already_done") or len(result.data.get("attempts", [])) > 1:
            print(f"  retry {key}: {'; '.join(result.data['attempts'])}")
    if events:
        for e in store.events(o.agent_run_id):
            print(f"  {e['seq']:>3} {e['type']:<15} {json.dumps(e['payload'], ensure_ascii=False)[:160]}")


async def _main(args: argparse.Namespace) -> int:
    ids = [t.id for t in tasks.load_all()] if args.task == "all" else [args.task]
    if args.channel == "gui":  # only tasks with a GUI oracle
        ids = [i for i in ids if (Path(__file__).parent / "oracles" / f"{i}_gui.py").is_file()]
    store = RunStore(BENCH_STORE)
    results = []
    timeout = None if args.live else HARNESS_HTTP_TIMEOUT  # make acme (LIVE=1) keeps the defaults
    with serve(env=HARNESS_SERVER_ENV) if not args.live else _nullcontext(live()) as acme:
        for task_id in ids:
            task = tasks.load(task_id)
            for run in tasks.runs(task):
                o = await run_oracle(acme, task, run, oracle_for(run.run_id, args.channel), chaos=args.chaos,
                                     chaos_seed=args.chaos_seed, store=store, timeout=timeout)
                _print(o, store, args.events)
                results.append(o)
    print("\nrun          ended       verifier status               checker (DB, side effects, report)")
    for o in results:
        status = o.verdict.status + ("" if o.verdict.status == o.run.expected_outcome else " (!)")
        print(f"{o.run.run_id:<12} {o.script.ended:<11} {status:<29} {'PASS' if o.result.passed else 'FAIL'}")
    failed = [o for o in results if not o.passed]
    return 1 if failed and not args.chaos else 0


class _nullcontext:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self.value

    def __exit__(self, *exc):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("task", help="T1 .. T9, or all")
    parser.add_argument("--chaos", default=None)
    parser.add_argument("--chaos-seed", type=int, default=0)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--channel", choices=["api", "gui"], default="api", help="gui: bench/oracles/<task>_gui.py")
    parser.add_argument("--events", action="store_true", help="print the agent run's event log")
    sys.exit(asyncio.run(_main(parser.parse_args())))


if __name__ == "__main__":
    main()
