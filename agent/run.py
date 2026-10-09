"""One request end to end (`make run` is the harness around it): begin -> feasibility gate -> gather -> planner ->
act -> verify -> report, as the oracle harness does. An LLM failure ends the work with an `executor_stop` event;
the verifier still runs and sets the status from the records, never from the agent's words. A hold asks `approver`
(default: pending); a rejection rolls back the run's writes (P.5). A run failed only on unmet critical milestones is
replanned and acted again, at most MAX_REPLANS times, then escalated (docs/day5-plan.md C)."""

from collections.abc import Callable, Mapping
from dataclasses import asdict, replace
from datetime import datetime
from typing import Any

import httpx

from agent.config import load_config
from agent.executor import Executor, brief, pending
from agent.feasibility import understand
from agent.lifecycle import Run, rollback, start_run
from agent.llm.client import LLMClient, LLMError, QuotaBook
from agent.memory.knowledge import load_sops
from agent.planner import make_plan
from agent.report import build_report, write_report
from agent.store import RunStore
from agent.verifier import Verdict, verify

MAX_REPLANS = 3


async def operate(request: str, now: datetime, *, store: RunStore | None = None, config: Mapping[str, str] | None = None,
                  transport: httpx.AsyncBaseTransport | None = None, make_llm: Callable[[Run], Any] | None = None,
                  approver: Callable[[str], Any] = pending, quota: QuotaBook | None = None) -> dict[str, Any]:
    config = load_config() if config is None else config
    run = start_run(request, now, store=store, config=config, transport=transport)
    stamp = now.isoformat()
    llm = make_llm(run) if make_llm else LLMClient(config, now=stamp, forbidden=(run.run_id,), quota=quota,
                                                   log=lambda p: run.ctx.store.append(run.run_id, "llm_call", stamp, p))
    try:
        if (await run.begin()).ok:
            try:
                ended, verified = await _work(run, llm, request, approver)
                if ended == "blocked":
                    undo = await rollback(run)  # a rejected action: compensate what the run wrote before it
                    if undo.undone or undo.not_compensable:
                        run.ctx.store.append(run.run_id, "rollback", stamp, asdict(undo))
            except LLMError as exc:
                verified = False
                run.ctx.store.append(run.run_id, "executor_stop", stamp, {"reason": f"{type(exc).__name__}: {exc}"[:500]})
        else:
            verified = False
        if not verified:
            await verify(run, llm=llm)
        report = build_report(run)
        write_report(run, report)
    finally:
        await run.close()
    return report


def _plan_failed(verdict: Verdict) -> list:
    """The unmet critical milestones, when they are the only reason the run failed (a replan can help)."""
    unmet = [m for m in verdict.milestones if m.critical and not m.ok and not m.unverifiable]
    other = any(not c.ok for c in verdict.postconditions) or (verdict.side_effects and verdict.side_effects.unexplained)
    return unmet if verdict.status == "failed" and not other else []


async def _work(run: Run, llm: Any, request: str, approver: Callable[[str], Any]) -> tuple[str, bool]:
    """How the work ended, and whether the verifier has already checked that ending."""
    sops = load_sops()
    goal = await understand(run, llm, request, sops)
    run.ctx.store.append(run.run_id, "goal", run.ctx.now.isoformat(), goal.model_dump())
    if goal.decision != "proceed":
        return goal.decision, False
    run.ctx = replace(run.ctx, sop_id=goal.sop_id)  # the gate's ORG-009 sees the chosen SOP from now on
    sop = sops.get(goal.sop_id or "")
    executor = Executor(run, llm, sop, approver)
    gathered = await executor.execute(brief(goal, sop), gather=True)
    if gathered.ended != "facts":
        return gathered.ended, False
    await executor.sample()
    run.plan = await make_plan(run, llm, goal, sop, gathered.facts, executor.fields)
    if run.plan is None:
        return "no plan", False
    ended = (await executor.execute(brief(goal, sop, gathered.facts, run.plan), gather=False)).ended
    for replan in range(1, MAX_REPLANS + 2):
        if ended != "":  # paused, blocked, asked, stopped: nothing a new plan can fix
            return ended, False
        unmet = _plan_failed(verdict := await verify(run, llm=llm))
        new = unmet and replan <= MAX_REPLANS and await make_plan(
            run, llm, goal, sop, gathered.facts, executor.fields, current=run.plan, unmet=unmet, replan=replan)
        if not new:
            if unmet:  # out of replans, or the planner could not give a valid one: escalate with the evidence
                run.ctx.store.append(run.run_id, "escalation", run.ctx.now.isoformat(), {
                    "replans": replan - 1, "unmet": [f"{m.id}: {m.target}" for m in unmet], "reasons": verdict.reasons})
            return ended, True
        run.plan, executor.again = new, True
        note = "\n\nAn independent check found these milestones unmet: " + "; ".join(
            f"{m.id} ({'; '.join(c.detail for c in m.checks if not c.ok)})" for m in unmet) + \
            ". Records you already wrote stay: read before you write again."
        ended = (await executor.execute(brief(goal, sop, gathered.facts, new, note), gather=False)).ended
    return ended, False
