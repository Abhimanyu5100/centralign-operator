"""`make run TASK=T1|"<request>" [REPLAY=1] [CHAOS=profile CHAOS_SEED=0] [EVENTS=1]`: the LLM operator on one request.

Harness side (agent/ never reads bench/, decision 11). A task id, or a request equal to a task's request, resets
the harness's own Acme (a child process, bench/live.serve) to that task's seed and frozen `now`, then runs
`agent.run.operate`, the task's checker on the result (DB, side effects, report) and prints both. Any other text
runs on seed `base` at the default `now`, with no checker. REPLAY=1 serves every LLM call from cassettes/ and
runs with every API key removed from the agent's config, so it proves no key is needed. Runs are written to the
operator's store (runs/runs.db), so `make ui` shows them. Exit 1 when the checker fails.
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime

from acme.clock import DEFAULT_NOW
from agent.run import operate
from agent.store import RunStore
from bench import tasks
from bench.checkers import engine
from bench.live import HARNESS_HTTP_TIMEOUT, HARNESS_SERVER_ENV, serve

KEYS = ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY")


def find_task(text: str) -> tasks.Task | None:
    every = tasks.load_all()
    return next((t for t in every if text in (t.id, t.request)), None)


async def _main(args: argparse.Namespace) -> int:
    task = find_task(args.task)
    request, seed, now = (task.request, task.seed, task.now) if task else (args.task, "base", DEFAULT_NOW)
    with serve(env=HARNESS_SERVER_ENV) as acme:
        acme.admin("POST", "/__admin/reset", seed=seed, now=now)
        if args.chaos:
            acme.admin("POST", "/__admin/chaos", profile=args.chaos, seed=args.chaos_seed)
        snapshot = acme.admin("POST", "/__admin/snapshot")["snapshot"]
        config = acme.agent_config(HARNESS_HTTP_TIMEOUT)
        if args.replay:
            config = {k: v for k, v in config.items() if k not in KEYS} | {"REPLAY": "1"}
        store = RunStore(args.store) if args.store else RunStore()
        report = await operate(request, datetime.fromisoformat(now), store=store, config=config)
        diff = acme.admin("GET", "/__admin/diff", since=snapshot)["tables"]
        result = engine.check(tasks.runs(task)[0], acme.db_path, diff, report) if task else None
    events = store.events(report["run_id"])
    calls = [e["payload"] for e in events if e["type"] == "llm_call"]
    print(f"\n== {task.id if task else 'request'}: {request}  (run {report['run_id']}, report runs/{report['run_id']}/)")
    print(f"  verifier: {report['status']}" + (f" (expected {task.expected_outcome})" if task else ""))
    for reason in report["status_reasons"] + report.get("stops", []):
        print(f"  - {reason[:300]}")
    print(f"  LLM: {len(calls)} call(s), {sum(c.get('total_tokens', 0) for c in calls)} tokens "
          f"({sum(c.get('prompt_tokens', 0) for c in calls)} prompt), "
          f"models {sorted({c['model'] for c in calls})}, {sorted({c['source'] for c in calls})}")
    if result:
        for check in result.checks:
            print(f"  {'PASS' if check.ok else 'FAIL'}  {check.name}{'  ' + check.detail if check.detail else ''}")
    if args.events:
        for e in events:
            print(f"  {e['seq']:>3} {e['type']:<15} {json.dumps(e['payload'], ensure_ascii=False)[:200]}")
    return 0 if result is None or result.passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("task", help="T1 .. T9, a task's request, or any request text")
    parser.add_argument("--replay", action="store_true", help="cassettes only, no API key in the agent's config")
    parser.add_argument("--chaos", default=None)
    parser.add_argument("--chaos-seed", type=int, default=0)
    parser.add_argument("--events", action="store_true", help="print the run's event log")
    parser.add_argument("--store", default=None, help="run store file (default runs/runs.db)")
    sys.exit(asyncio.run(_main(parser.parse_args())))


if __name__ == "__main__":
    main()
