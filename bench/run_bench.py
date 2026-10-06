"""`make bench [K=1] [ONLY=T1,T2] [NO_ADVERSARIAL=1]`: AcmeBench in one command (Day 3.3).

Acme runs as a child process on a temporary database (bench/live.py). For every task:
- each run (T9: none / approve / reject) with chaos off, K times (pass^K; oracles are deterministic, K=1);
- the GUI oracle where one exists (T1), chaos off;
- each chaos variant in the task YAML (`chaos_variants`, seed 0), once. `delayed_write` is refused for T3 and T8:
  their keyless writes have no natural uniqueness (D-123; T3 under delayed_write is an e2e test instead).
Then every adversarial script. Each oracle run is verified, reported and checked by the engine (DB predicates, side
effects, status and report checks). Oracles judge the checkers with chaos off; chaos runs measure detection and
failure classification, not success.

Columns per run: passed, verifier status vs expected, CuP (D-130), unexplained side effects, correct refusal (T4,
T5), chaos fired (runs where it did not fire are listed apart and excluded from recovery, D-095), verifier-vs-diff
agreement (the verifier's audit rows against `/__admin/diff`), held calls, wall time and verifier time.
Results: bench/results/<timestamp>.json and .md. Runs go to the bench run store, never the operator's (N.164).
"""

import argparse
import asyncio
import json
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
from bench.live import BENCH_STORE, OracleRun, run_oracle, serve
from bench.oracles import oracle_for

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "bench" / "results"
NO_DELAYED_WRITE = {"T3", "T8"}       # D-123
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
    seconds: float = 0.0
    verify_seconds: float = 0.0


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


def chaos_variants(task) -> list[tuple[str, int]]:
    variants = [(v.profile, v.seed) for v in task.chaos_variants]
    if task.id in NO_DELAYED_WRITE and any(profile == "delayed_write" for profile, _ in variants):
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
        seconds=round(o.seconds, 2), verify_seconds=round(o.verify_seconds, 2))


def summary(rows: list[Row], adversarial: list[dict[str, Any]]) -> dict[str, Any]:
    off = [r for r in rows if r.chaos == "off"]
    on = [r for r in rows if r.chaos != "off"]
    fired = [r for r in on if r.chaos_fired]
    refusals = [r for r in off if r.refusal_correct is not None]
    passes = pass_k(rows)
    return {
        "oracle_runs_passed": f"{sum(r.passed for r in off)}/{len(off)}",
        "pass_k": f"{sum(passes.values())}/{len(passes)}",
        "cup": f"{sum(r.cup for r in off)}/{len(off)}",
        "unexplained_side_effects": sum(r.unexplained for r in rows),
        "correct_refusals": f"{sum(bool(r.refusal_correct) for r in refusals)}/{len(refusals)}",
        "chaos_fired": f"{len(fired)}/{len(on)}",
        "chaos_not_fired": [f"{r.run_id} {r.chaos}" for r in on if not r.chaos_fired],
        "recovered_when_fired": f"{sum(r.passed for r in fired)}/{len(fired)}",
        "verifier_diff_agreement": f"{sum(bool(r.agreement) for r in rows)}/{len(rows)}",
        "adversarial_stopped": f"{sum(a['passed'] for a in adversarial)}/{len(adversarial)}",
        "seconds": round(sum(r.seconds for r in rows), 1),
    }


def markdown(result: dict[str, Any]) -> str:
    meta, s = result["meta"], result["summary"]
    lines = [f"# AcmeBench {meta['started']}", "",
             f"Commit {meta['commit']}, k={meta['k']}, chaos seed 0, oracle agent (the scripted perfect agent).", "",
             "| Measure | Result |", "| --- | --- |"]
    lines += [f"| {key.replace('_', ' ')} | {value if not isinstance(value, list) else ', '.join(value) or 'none'} |"
              for key, value in s.items()]
    header = ("| Run | Channel | Chaos | Try | Passed | Status (expected) | CuP | Unexplained | Refusal | Fired | "
              "Agrees with diff | Held | Failures | Seconds (verify) |")
    lines += ["", "## Runs", "", header, "|" + " --- |" * 14]
    for r in result["rows"]:
        status = r["status"] + ("" if r["status"] == r["expected"] else f" (expected {r['expected']})")
        lines.append(f"| {r['run_id']} | {r['channel']} | {r['chaos']} | {r['attempt']} | {'yes' if r['passed'] else 'NO'}"
                     f" | {status} | {'yes' if r['cup'] else 'no'} | {r['unexplained']} | "
                     f"{'' if r['refusal_correct'] is None else ('yes' if r['refusal_correct'] else 'NO')} | "
                     f"{'' if r['chaos_fired'] is None else ('yes' if r['chaos_fired'] else 'no')} | "
                     f"{'yes' if r['agreement'] else 'NO: ' + '; '.join(r['disagreement'])} | {r['held']} | "
                     f"{', '.join(r['failure_kinds'])} | {r['seconds']} ({r['verify_seconds']}) |")
    if result["pass_k"]:
        lines += ["", f"## pass^{meta['k']}", ""] + [f"- {k}: {'yes' if v else 'NO'}" for k, v in result["pass_k"].items()]
    lines += ["", "## Adversarial", "", "| Script | Expected stop | Stopped as expected |", "| --- | --- | --- |"]
    lines += [f"| {a['name']} | {a['expected']} | {'yes' if a['passed'] else 'NO: ' + '; '.join(a['problems'])} |"
              for a in result["adversarial"]]
    return "\n".join(lines) + "\n"


# --- the run ---------------------------------------------------------------------------------------------------

async def bench(acme, *, k: int = 1, only: set[str] | None = None, adversarial: bool = True,
                store: RunStore | None = None) -> dict[str, Any]:
    store = store or RunStore(BENCH_STORE)
    rows: list[Row] = []
    for task in tasks.load_all():
        if only and task.id not in only:
            continue
        variants = chaos_variants(task)
        for run in tasks.runs(task):
            for attempt in range(1, k + 1):
                rows.append(row_of(await run_oracle(acme, task, run, oracle_for(run.run_id), store=store),
                                   "api", "off", attempt))
            if (ROOT / "bench" / "oracles" / f"{task.id}_gui.py").is_file():
                rows.append(row_of(await run_oracle(acme, task, run, oracle_for(run.run_id, "gui"), store=store),
                                   "gui", "off", 1))
            for profile, seed in variants:
                o = await run_oracle(acme, task, run, oracle_for(run.run_id), chaos=profile, chaos_seed=seed, store=store)
                rows.append(row_of(o, "api", f"{profile}:{seed}", 1))
    stopped = [{"name": o.name, "expected": o.expected, "passed": o.passed, "problems": o.problems}
               for o in (await run_all(acme, store) if adversarial else [])]
    return {"meta": {"started": datetime.now().astimezone().isoformat(timespec="seconds"), "commit": _commit(), "k": k},
            "rows": [asdict(r) for r in rows], "pass_k": pass_k(rows), "adversarial": stopped,
            "summary": summary(rows, stopped)}


def _commit() -> str:
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
    args = parser.parse_args()
    with serve() as acme:
        result = asyncio.run(bench(acme, k=args.k, only=set(filter(None, args.only.split(","))) or None,
                                   adversarial=not args.no_adversarial))
    path = save(result)
    print(markdown(result))
    print(f"saved {path} and {path.with_suffix('.json')}")
    off_failed = [r for r in result["rows"] if r["chaos"] == "off" and not r["passed"]]
    sys.exit(1 if off_failed or not all(a["passed"] for a in result["adversarial"]) else 0)


if __name__ == "__main__":
    main()
