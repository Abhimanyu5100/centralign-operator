"""`make run TASK=T1|T9:approve|"<request>" [REPLAY=1] [CHAOS=profile CHAOS_SEED=0] [EVENTS=1] [APPROVE_WAIT=s]`: the
LLM operator on one request.

Harness side (agent/ never reads bench/, decision 11). A task id, or a request equal to a task's request, resets
the harness's own Acme (a child process, bench/live.serve) to that task's seed and frozen `now`, then runs
`agent.run.operate`, the task's checker on the result (DB, side effects, report) and prints both. With AS_TASK=T1 the
request text is any rewording, run on T1's seed and frozen `now` and judged by T1's checker (a held-out probe). Any other text
runs on seed `base` at the default `now`, with no checker. REPLAY=1 serves every LLM call from cassettes/ and
runs with every API key removed from the agent's config, so it proves no key is needed. Runs are written to the
operator's store (runs/runs.db), so `make ui` shows them. Exit 1 when the checker fails.
A held call is decided by the task run's scripted approver (T9:approve / T9:reject; T9:none leaves it pending), or
by a person in `make ui` within APPROVE_WAIT seconds. Live runs keep a per-model daily call estimate in
runs/llm_quota.json (the Pacific day, when Gemini's free quota resets) and print what is left (D-179).
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from acme.clock import DEFAULT_NOW
from agent.config import ROOT
from agent.llm.client import CHAINS, QuotaBook
from agent.run import operate
from agent.store import RunStore
from bench import tasks
from bench.approver import for_agent
from bench.checkers import engine
from bench.live import HARNESS_HTTP_TIMEOUT, HARNESS_SERVER_ENV, serve

KEYS = ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY")
QUOTA_FILE = ROOT / "runs" / "llm_quota.json"


def find_run(text: str) -> tasks.Run | None:
    """A task run by run id (T9:approve), task id (its first run) or request text."""
    return next((r for t in tasks.load_all() for r in tasks.runs(t) if text in (r.run_id, t.id, t.request)), None)


def quota_book(config) -> QuotaBook:
    return QuotaBook(QUOTA_FILE, datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat(),
                     config.get("LLM_DAILY_LIMITS", ""))


def quota_line(config, book: QuotaBook) -> str:
    models = dict.fromkeys(config[k] for chain in CHAINS.values() for _, k in chain if config.get(k))
    shown = [f"{m} {book.left(m)}/{book.limits[m]}" if m in book.limits else f"{m} used {book.calls.get(m, 0)} (limit ?)"
             + (" spent" if m in book.spent else "") for m in models]
    return f"  estimated calls left today ({book.day}, Pacific): " + ", ".join(shown)


async def _main(args: argparse.Namespace) -> int:
    found = find_run(args.as_task) if args.as_task else find_run(args.task)
    if args.as_task and found is None:
        raise SystemExit(f"--as {args.as_task}: no such task run")
    task = found.task if found else None
    request, seed, now = (task.request, task.seed, task.now) if task else (args.task, "base", DEFAULT_NOW)
    if args.as_task:  # a held-out rewording judged by that task's own checker, seed and now (Day 6 probe)
        request = args.task
    with serve(env=HARNESS_SERVER_ENV) as acme:
        acme.admin("POST", "/__admin/reset", seed=seed, now=now)
        if args.chaos:
            acme.admin("POST", "/__admin/chaos", profile=args.chaos, seed=args.chaos_seed)
        snapshot = acme.admin("POST", "/__admin/snapshot")["snapshot"]
        config = acme.agent_config(HARNESS_HTTP_TIMEOUT)
        # a chaos run or a T9 decision records its own replies, apart from the plain task's (D-209, D-211)
        config["CASSETTE_SCOPE"] = (tasks.cassette_scope(found, args.chaos, args.chaos_seed) if found else
                                    f"{args.chaos}:{args.chaos_seed}" if args.chaos else "")
        if args.replay:
            config = {k: v for k, v in config.items() if k not in KEYS} | {"REPLAY": "1"}
        store = RunStore(args.store) if args.store else RunStore()
        book = None if args.replay else quota_book(config)
        if book:
            print(quota_line(config, book))
        approver = for_agent(store.path, found.approver if found else "none", args.approve_wait)
        report = await operate(request, datetime.fromisoformat(now), store=store, config=config, approver=approver,
                               quota=book)
        diff = acme.admin("GET", "/__admin/diff", since=snapshot)["tables"]
        result = engine.check(found, acme.db_path, diff, report) if found else None
    events = store.events(report["run_id"])
    calls = [e["payload"] for e in events if e["type"] == "llm_call"]
    print(f"\n== {found.run_id if found else 'request'}: {request}  (run {report['run_id']}, report runs/{report['run_id']}/)")
    print(f"  verifier: {report['status']}" + (f" (expected {found.expected_outcome})" if found else ""))
    for reason in report["status_reasons"] + report.get("stops", []):
        print(f"  - {reason[:300]}")
    print(f"  LLM: {len(calls)} call(s), {sum(c.get('total_tokens', 0) for c in calls)} tokens "
          f"({sum(c.get('prompt_tokens', 0) for c in calls)} prompt), "
          f"models {sorted({c['model'] for c in calls})}, {sorted({c['source'] for c in calls})}")
    if book:
        print(quota_line(config, QuotaBook(QUOTA_FILE, book.day, config.get("LLM_DAILY_LIMITS", ""))))
    if result:
        for check in result.checks:
            print(f"  {'PASS' if check.ok else 'FAIL'}  {check.name}{'  ' + check.detail if check.detail else ''}")
    if args.events:
        for e in events:
            print(f"  {e['seq']:>3} {e['type']:<15} {json.dumps(e['payload'], ensure_ascii=False)[:200]}")
    return 0 if result is None or result.passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("task", help="T1 .. T9, a run id such as T9:approve, a task's request, or any request text")
    parser.add_argument("--approve-wait", type=float, default=0.0, help="seconds to wait for a person in make ui")
    parser.add_argument("--replay", action="store_true", help="cassettes only, no API key in the agent's config")
    parser.add_argument("--chaos", default=None)
    parser.add_argument("--chaos-seed", type=int, default=0)
    parser.add_argument("--events", action="store_true", help="print the run's event log")
    parser.add_argument("--store", default=None, help="run store file (default runs/runs.db)")
    parser.add_argument("--as", dest="as_task", default=None,
                        help="judge this request text with a task's checker, seed and now (a held-out rewording)")
    sys.exit(asyncio.run(_main(parser.parse_args())))


if __name__ == "__main__":
    main()
