"""`make bench [K=1] [ONLY=T1,T2] [NO_ADVERSARIAL=1]`: AcmeBench in one command (Day 3.3).

Acme runs as a child process on a temporary database (bench/live.py). For every task:
- each run (T9: none / approve / reject) with chaos off, K times (pass^K; oracles are deterministic, K=1);
- the GUI oracle where one exists (T1), chaos off;
- each chaos variant in the task YAML (`chaos_variants`, seed 0), once. `delayed_write` is refused for T3 and T8:
  their keyless writes have no natural uniqueness (D-123; T3 under delayed_write is an e2e test instead). A variant
  marked `channel: gui` (a UI-only profile) runs only with the task's GUI oracle and is listed as skipped when the
  task has none (D-161). Every chaos run that does run must fire: one that did not fails the bench.
The bench's own Acme holds a commit_then_timeout response for 5 s and its agent times out after 3 s (D-162).
Then every adversarial script. Each oracle run is verified, reported and checked by the engine (DB predicates, side
effects, status and report checks). Oracles judge the checkers with chaos off; chaos runs measure detection and
failure classification, not success.

Columns per run: passed, verifier status vs expected, CuP (D-130), unexplained side effects, correct refusal (T4,
T5), chaos fired (runs where it did not fire are listed apart and excluded from recovery, D-095), verifier-vs-diff
agreement (the verifier's audit rows against `/__admin/diff`), held calls, wall time and verifier time.
Results: bench/results/<timestamp>.json and .md. Runs go to the bench run store, never the operator's (N.164).

`--agent --live` (Day 6, D-211): the LLM operator live (REPLAY=0) on every task run, chaos off K times; a task
with scripted-approver variants (T9) once per decision; every API chaos variant once. Each attempt records into
its own folder (`<cassettes>/a<attempt>`, default runs/cassettes-live/<timestamp>; the committed cassettes/ is never
written), calls are counted in the daily quota book, and each row prints as it finishes. LLM rows also carry calls,
tokens, models and the cassette key prefixes they used.
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.store import RunStore
from bench import tasks
from bench.adversarial import run_all
from bench.live import BENCH_STORE, HARNESS_HTTP_TIMEOUT, HARNESS_SERVER_ENV, OracleRun, run_agent, run_oracle, serve
from bench.oracles import oracle_for
from bench.run_agent import quota_book

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "bench" / "results"
NO_DELAYED_WRITE = {"T3", "T8"}       # D-123
# Chaos variants with LLM cassettes (`--agent` replays only these). T1 flaky_500's live recording (Day 6, failed)
# no longer replays: D-215 changed the refusal its replan retry was sent; its live result stays in the results file.
RECORDED_CHAOS = {("T3", "commit_then_timeout"), ("T8", "session_expiry_at_step_5"), ("T8", "commit_then_timeout")}
REFUSALS = {"T4": "needs_clarification", "T5": "infeasible"}


@dataclass
class Row:
    run_id: str
    channel: str
    chaos: str                      # "off" or "profile:seed"
    attempt: int
    passed: bool                    # the engine: DB predicates, side effects, status, report checks
    status: str
    expected: str
    ended: str
    cup: bool
    unexplained: int
    refusal_correct: bool | None    # T4 / T5 only
    chaos_fired: bool | None
    agreement: bool | None
    disagreement: list[str] = field(default_factory=list)
    held: int = 0                   # action approvals filed
    failure_kinds: list[str] = field(default_factory=list)
    recovered: list[str] = field(default_factory=list)  # "<error_type> (recovered)": failed inside a tool, then ok
    seconds: float = 0.0
    verify_seconds: float = 0.0
    llm_calls: int = 0               # LLM runs only
    tokens: int = 0
    models: list[str] = field(default_factory=list)
    cassettes: list[str] = field(default_factory=list)


# --- the columns (pure functions, tested in tests/bench/test_run_bench.py) ----------------------------------------

def completed_under_policy(passed: bool, report: dict[str, Any]) -> bool:
    """D-130: the checker passed, no gate deny or Acme policy refusal happened, and nothing changed unexplained."""
    refused = any(f["kind"] == "policy_refusal" for f in report.get("failures", []))
    unexplained = any(s.get("unexplained") for s in report.get("side_effects", []))
    return passed and not refused and not unexplained


def agreement(report: dict[str, Any], diff: dict[str, Any]) -> tuple[bool, list[str]]:
    """Do the verifier's audit rows name the same records the harness's /__admin/diff shows changed (6.4)?"""
    seen = {(s["table"], s["entity_id"]) for s in report.get("side_effects", []) if not s.get("claimed_not_audited")}
    changed = {(table, row["id"]) for table, change in diff.items() if table != "audit_log"
               for row in [*change.get("added", []), *change.get("changed", [])]}
    missing = [f"verifier missed {t} {i}" for t, i in sorted(changed - seen)]
    extra = [f"verifier listed {t} {i}, the diff did not" for t, i in sorted(seen - changed)]
    return not (missing or extra), missing + extra


def pass_k(rows: list[Row]) -> dict[str, bool]:
    """pass^k per run id over the chaos-off API rows: every attempt passed."""
    by_run: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        if row.chaos == "off" and row.channel == "api":
            by_run[row.run_id].append(row.passed)
    return {run_id: all(results) for run_id, results in by_run.items()}


def chaos_variants(task) -> list[tuple[str, int, str]]:
    variants = [(v.profile, v.seed, v.channel) for v in task.chaos_variants]
    if task.id in NO_DELAYED_WRITE and any(profile == "delayed_write" for profile, _, _ in variants):
        raise ValueError(f"{task.id}: delayed_write is never a bench variant for T3 or T8 (D-123)")
    return variants


def row_of(o: OracleRun, channel: str, chaos: str, attempt: int) -> Row:
    ok, differences = agreement(o.report, o.diff)
    task_id = o.run.run_id.partition(":")[0]
    return Row(
        run_id=o.run.run_id, channel=channel, chaos=chaos, attempt=attempt, passed=o.passed,
        status=o.verdict.status, expected=o.run.expected_outcome, ended=o.script.ended,
        cup=completed_under_policy(o.passed, o.report),
        unexplained=sum(1 for s in o.report.get("side_effects", []) if s.get("unexplained")),
        refusal_correct=(o.verdict.status == REFUSALS[task_id] and o.passed) if task_id in REFUSALS else None,
        chaos_fired=o.chaos_fired, agreement=ok, disagreement=differences,
        held=len(o.report.get("action_approvals", [])),
        failure_kinds=sorted({f["kind"] for f in o.report.get("failures", [])}),
        recovered=sorted({f"{r['error_type']} (recovered)" for r in o.report.get("recovered", [])}),
        seconds=round(o.seconds, 2), verify_seconds=round(o.verify_seconds, 2),
        llm_calls=o.llm_calls, tokens=o.tokens, models=o.models, cassettes=o.cassettes)


def summary(rows: list[Row], adversarial: list[dict[str, Any]], skipped: list[str] | None = None) -> dict[str, Any]:
    off = [r for r in rows if r.chaos == "off"]
    on = [r for r in rows if r.chaos != "off"]
    fired = [r for r in on if r.chaos_fired]
    refusals = [r for r in off if r.refusal_correct is not None]
    passes = pass_k(rows)
    k = max((r.attempt for r in off), default=1)
    repeated = {run_id for run_id in passes if sum(r.run_id == run_id for r in off if r.channel == "api") == k}
    llm = {"llm_calls": sum(r.llm_calls for r in rows), "tokens": sum(r.tokens for r in rows)} \
        if any(r.llm_calls for r in rows) else {}
    return {
        "runs_passed": f"{sum(r.passed for r in off)}/{len(off)}",
        "pass_k": f"{sum(passes[i] for i in repeated)}/{len(repeated)}",
        **({"run_once_passed": f"{sum(passes[i] for i in set(passes) - repeated)}/{len(set(passes) - repeated)}"}
           if set(passes) - repeated else {}),
        "cup": f"{sum(r.cup for r in off)}/{len(off)}",
        "unexplained_side_effects": sum(r.unexplained for r in rows),
        "correct_refusals": f"{sum(bool(r.refusal_correct) for r in refusals)}/{len(refusals)}",
        "chaos_fired": f"{len(fired)}/{len(on)}",
        "chaos_not_fired": [f"{r.run_id} {r.chaos}" for r in on if not r.chaos_fired],
        "chaos_skipped": skipped or [],
        "recovered_when_fired": f"{sum(r.passed for r in fired)}/{len(fired)}",
        "verifier_diff_agreement": f"{sum(bool(r.agreement) for r in rows)}/{len(rows)}",
        "adversarial_stopped": f"{sum(a['passed'] for a in adversarial)}/{len(adversarial)}",
        **llm,
        "seconds": round(sum(r.seconds for r in rows), 1),
    }


def llm_cell(r: dict[str, Any]) -> str:
    return f"{r['llm_calls']} ({r['tokens']})" if r.get("llm_calls") else ""


def markdown(result: dict[str, Any]) -> str:
    meta, s = result["meta"], result["summary"]
    lines = [f"# AcmeBench {meta['started']}", "",
             f"Commit {meta['commit']}, k={meta['k']}, chaos seed 0, "
             + (f"LLM agent live (REPLAY=0), recorded into {meta.get('cassettes')} (D-211)." if meta.get("live") else
                "LLM agent replayed from cassettes, no API key (D-210)." if meta.get("agent") else
                "oracle agent (the scripted perfect agent)."), "",
             "| Measure | Result |", "| --- | --- |"]
    lines += [f"| {key.replace('_', ' ')} | {value if not isinstance(value, list) else ', '.join(value) or 'none'} |"
              for key, value in s.items()]
    header = ("| Run | Channel | Chaos | Try | Passed | Status (expected) | CuP | Unexplained | Refusal | Fired | "
              "Agrees with diff | Held | Failures | LLM calls (tokens) | Seconds (verify) |")
    lines += ["", "## Runs", "", header, "|" + " --- |" * 15]
    for r in result["rows"]:
        status = r["status"] + ("" if r["status"] == r["expected"] else f" (expected {r['expected']})")
        lines.append(f"| {r['run_id']} | {r['channel']} | {r['chaos']} | {r['attempt']} | {'yes' if r['passed'] else 'NO'}"
                     f" | {status} | {'yes' if r['cup'] else 'no'} | {r['unexplained']} | "
                     f"{'' if r['refusal_correct'] is None else ('yes' if r['refusal_correct'] else 'NO')} | "
                     f"{'' if r['chaos_fired'] is None else ('yes' if r['chaos_fired'] else 'no')} | "
                     f"{'yes' if r['agreement'] else 'NO: ' + '; '.join(r['disagreement'])} | {r['held']} | "
                     f"{', '.join(r['failure_kinds'] + r.get('recovered', []))} | "
                     f"{llm_cell(r)} | "
                     f"{r['seconds']} ({r['verify_seconds']}) |")
    if result["pass_k"]:
        tries = defaultdict(int)
        for r in result["rows"]:
            tries[r["run_id"]] += r["chaos"] == "off" and r["channel"] == "api"
        lines += ["", f"## pass^{meta['k']}", ""] + [
            f"- {k}: {'yes' if v else 'NO'}" + (f" (run {tries[k]} time(s), not k)" if tries[k] != meta["k"] else "")
            for k, v in result["pass_k"].items()]
    lines += ["", "## Adversarial", "", "| Script | Expected stop | Stopped as expected |", "| --- | --- | --- |"]
    lines += [f"| {a['name']} | {a['expected']} | {'yes' if a['passed'] else 'NO: ' + '; '.join(a['problems'])} |"
              for a in result["adversarial"]]
    return "\n".join(lines) + "\n"


# --- the run ---------------------------------------------------------------------------------------------------

async def bench(acme, *, k: int = 1, only: set[str] | None = None, adversarial: bool = True,
                store: RunStore | None = None, timeout: float | None = HARNESS_HTTP_TIMEOUT,
                agent: bool = False, live: bool = False, cassettes: Path | None = None) -> dict[str, Any]:
    """`agent`: the LLM operator from cassettes instead of the oracles; no GUI oracle row; only recorded chaos variants.
    `live` (with `agent`): REPLAY=0, every API chaos variant, a scripted-approver run once, recordings under
    `cassettes` (one folder per attempt when k > 1)."""
    store = store or RunStore(BENCH_STORE)
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    rows: list[Row] = []
    skipped: list[str] = []

    async def agent_run(task, run, attempt: int, chaos: str | None = None, seed: int = 0):
        if not live:
            return await run_agent(acme, task, run, chaos=chaos, chaos_seed=seed, store=store, timeout=timeout)
        folder = cassettes / f"a{attempt}" if k > 1 else cassettes
        return await run_agent(acme, task, run, chaos=chaos, chaos_seed=seed, store=store, timeout=timeout,
                               replay=False, cassettes=folder, quota=quota_book(acme.agent_config()))

    def add(row: Row) -> None:
        rows.append(row)
        if agent:  # a long live bench: each row as it finishes, so a crash loses nothing (D-211)
            print(f"[{datetime.now():%H:%M:%S}] {row.run_id} {row.chaos} try {row.attempt}: "
                  f"{'PASS' if row.passed else 'FAIL'} {row.status} (expected {row.expected}), {row.llm_calls} calls, "
                  f"{row.tokens} tokens, {row.seconds} s, failures {row.failure_kinds + row.recovered}", flush=True)

    for task in tasks.load_all():
        if only and task.id not in only:
            continue
        variants = chaos_variants(task)
        has_gui = not agent and (ROOT / "bench" / "oracles" / f"{task.id}_gui.py").is_file()
        for run in tasks.runs(task):
            tries = 1 if live and task.variants is not None else k  # T9: once per decision (D-211)
            for attempt in range(1, tries + 1):
                o = await (agent_run(task, run, attempt) if agent else
                           run_oracle(acme, task, run, oracle_for(run.run_id), store=store, timeout=timeout))
                add(row_of(o, "api", "off", attempt))
            if has_gui:
                o = await run_oracle(acme, task, run, oracle_for(run.run_id, "gui"), store=store, timeout=timeout)
                add(row_of(o, "gui", "off", 1))
            for profile, seed, channel in variants:
                if channel == "gui" and not has_gui:  # a UI-only profile cannot fire on an API run (D-161)
                    skipped.append(f"{run.run_id} {profile}:{seed} (GUI only, no GUI oracle)")
                    continue
                if agent and not live and (task.id, profile) not in RECORDED_CHAOS:
                    skipped.append(f"{run.run_id} {profile}:{seed} (no LLM recording for the current code)")
                    continue
                o = await (agent_run(task, run, 1, profile, seed) if agent else
                           run_oracle(acme, task, run, oracle_for(run.run_id, "gui" if channel == "gui" else "api"),
                                      chaos=profile, chaos_seed=seed, store=store, timeout=timeout))
                add(row_of(o, channel if channel == "gui" else "api", f"{profile}:{seed}", 1))
    stopped = [{"name": o.name, "expected": o.expected, "passed": o.passed, "problems": o.problems}
               for o in (await run_all(acme, store) if adversarial else [])]
    return {"meta": {"started": started, "commit": _commit(), "k": k, "agent": agent, "live": live,
                     **({"cassettes": str(cassettes.relative_to(ROOT) if cassettes.is_relative_to(ROOT) else cassettes)}
                        if live else {})},
            "rows": [asdict(r) for r in rows], "pass_k": pass_k(rows), "adversarial": stopped,
            "summary": summary(rows, stopped, skipped)}


def _commit() -> str:
    if os.environ.get("GIT_COMMIT"):  # the Docker image has no .git; its build arg says which commit it is (Day 6)
        return os.environ["GIT_COMMIT"]
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        return out.stdout.strip() + (" (with uncommitted changes)" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def save(result: dict[str, Any], folder: Path = RESULTS) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (folder / f"{stamp}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (folder / f"{stamp}.md").write_text(markdown(result), encoding="utf-8")
    return folder / f"{stamp}.md"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--k", type=int, default=1, help="chaos-off attempts per run (pass^k)")
    parser.add_argument("--only", default="", help="comma-separated task ids, e.g. T1,T2")
    parser.add_argument("--no-adversarial", action="store_true")
    parser.add_argument("--agent", action="store_true", help="the LLM operator from cassettes (no key) instead of oracles")
    parser.add_argument("--live", action="store_true", help="with --agent: live LLM calls (REPLAY=0), recorded apart")
    parser.add_argument("--cassettes", type=Path, default=None,
                        help="with --live: where recordings go (default runs/cassettes-live/<timestamp>)")
    parser.add_argument("--results", type=Path, default=RESULTS, help="folder for the results files")
    args = parser.parse_args()
    if args.live and not args.agent:
        parser.error("--live needs --agent (the oracles call no LLM)")
    cassettes = (args.cassettes or ROOT / "runs" / "cassettes-live" / datetime.now().strftime("%Y%m%d-%H%M%S")).resolve()
    with serve(env=HARNESS_SERVER_ENV) as acme:
        result = asyncio.run(bench(acme, k=args.k, only=set(filter(None, args.only.split(","))) or None,
                                   adversarial=not args.no_adversarial, agent=args.agent, live=args.live,
                                   cassettes=cassettes))
    path = save(result, args.results)
    print(markdown(result))
    print(f"saved {path} and {path.with_suffix('.json')}")
    sys.exit(1 if problems(result) else 0)


def problems(result: dict[str, Any]) -> list[str]:
    """Why the bench fails: a chaos-off run that did not pass, a chaos run whose fault never fired, an adversarial
    script that was not stopped as expected."""
    rows = result["rows"]
    return ([f"{r['run_id']} ({r['channel']}) failed" for r in rows if r["chaos"] == "off" and not r["passed"]]
            + [f"{r['run_id']} {r['chaos']}: the fault never fired" for r in rows
               if r["chaos"] != "off" and not r["chaos_fired"]]
            + [f"adversarial {a['name']} not stopped as expected" for a in result["adversarial"] if not a["passed"]])


if __name__ == "__main__":
    main()
