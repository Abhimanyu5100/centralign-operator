"""One request end to end (`make run` is the harness around it): begin -> feasibility gate -> gather -> planner ->
act -> verify -> report, as the oracle harness does. An LLM failure ends the work with an `executor_stop` event;
the verifier still runs and sets the status from the records, never from the agent's words."""

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

import httpx

from agent.config import load_config
from agent.executor import Executor, brief
from agent.feasibility import understand
from agent.lifecycle import Run, start_run
from agent.llm.client import LLMClient, LLMError
from agent.memory.knowledge import load_sops
from agent.planner import make_plan
from agent.report import build_report, write_report
from agent.store import RunStore
from agent.verifier import verify


async def operate(request: str, now: datetime, *, store: RunStore | None = None, config: Mapping[str, str] | None = None,
                  transport: httpx.AsyncBaseTransport | None = None,
                  make_llm: Callable[[Run], Any] | None = None) -> dict[str, Any]:
    config = load_config() if config is None else config
    run = start_run(request, now, store=store, config=config, transport=transport)
    stamp = now.isoformat()
    llm = make_llm(run) if make_llm else LLMClient(
        config, now=stamp, forbidden=(run.run_id,), log=lambda p: run.ctx.store.append(run.run_id, "llm_call", stamp, p))
    try:
        if (await run.begin()).ok:
            try:
                await _work(run, llm, request)
            except LLMError as exc:
                run.ctx.store.append(run.run_id, "executor_stop", stamp, {"reason": f"{type(exc).__name__}: {exc}"[:500]})
        await verify(run)
        report = build_report(run)
        write_report(run, report)
    finally:
        await run.close()
    return report


async def _work(run: Run, llm: Any, request: str) -> None:
    sops = load_sops()
    goal = await understand(run, llm, request, sops)
    run.ctx.store.append(run.run_id, "goal", run.ctx.now.isoformat(), goal.model_dump())
    if goal.decision != "proceed":
        return
    run.ctx = replace(run.ctx, sop_id=goal.sop_id)  # the gate's ORG-009 sees the chosen SOP from now on
    sop = sops.get(goal.sop_id or "")
    executor = Executor(run, llm)
    gathered = await executor.execute(brief(goal, sop), gather=True)
    if gathered.ended != "facts":
        return
    run.plan = await make_plan(run, llm, goal, sop, gathered.facts, executor.fields)
    if run.plan is not None:
        await executor.execute(brief(goal, sop, gathered.facts, run.plan), gather=False)
