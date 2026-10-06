"""Scripted agent (Phase A): runs a fixed list of tool calls through `registry.call`, the exact path the LLM
executor will use (validate -> gate -> preconditions -> tool). No LLM, no retries of its own, no judgement: the
oracles (hand-written perfect agents) are these step lists.

A step's args are either a dict or a function of the results so far (keyed by step name), so a later step can
use an id an earlier one returned without the script hard-coding database ids. A step with `when` runs only if
its condition on the results so far holds; that is the only branching a script has.

How a script ends (`ScriptResult.ended`); the run's STATUS still comes only from the verifier:
- `done`: every step ran;
- `asked` / `infeasible`: an ending tool (`ask_user`, `declare_infeasible`) ran, and nothing after it does;
- `paused`: the gate held a call for an action approval; `resume_script` re-runs that same call once the human
  approved it, ends `blocked` if they rejected it, and stays `paused` while it is pending (P.5);
- `blocked`: the gate denied a call, or the approval was rejected;
- `stopped`: any other failed result.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from agent.lifecycle import Run
from agent.tools.ask import ENDING_TOOLS
from agent.tools.registry import ToolResult

Results = dict[str, ToolResult]
Ended = Literal["done", "asked", "infeasible", "paused", "blocked", "stopped"]


@dataclass(frozen=True)
class Step:
    tool: str
    args: Mapping[str, Any] | Callable[[Results], Mapping[str, Any]] = field(default_factory=dict)
    name: str = ""  # the key later steps use for this result; defaults to the tool name
    when: Callable[[Results], bool] | None = None  # run only if this holds (e.g. redo a write a read-back missed)

    @property
    def key(self) -> str:
        return self.name or self.tool


@dataclass
class ScriptResult:
    ended: Ended
    results: Results
    stopped_at: str | None = None      # the key of the step that ended the script early
    next_step: int = 0                 # where `resume_script` continues (the held step itself)
    approval_id: str | None = None     # the pending action approval, when paused
    events: list[dict[str, Any]] = field(default_factory=list)  # the run's event log at the end

    @property
    def ok(self) -> bool:
        """The script ran as written: it was not cut short by an unexpected failure."""
        return self.ended != "stopped"


async def run_script(run: Run, steps: Sequence[Step], start: int = 0, results: Results | None = None) -> ScriptResult:
    results = dict(results or {})
    begun = await run.begin()  # the audit start mark, once per run
    if not begun.ok:
        return _end(run, "stopped", results, "begin", start)
    for index in range(start, len(steps)):
        step = steps[index]
        if step.when is not None and not step.when(results):
            continue
        args = step.args(results) if callable(step.args) else step.args
        results[step.key] = result = await run.call(step.tool, args)
        if result.error_type == "approval_required":
            return _end(run, "paused", results, step.key, index, result.data.get("approval_id"))
        if result.error_type == "policy_denied":
            return _end(run, "blocked", results, step.key, index)
        if not result.ok:
            return _end(run, "stopped", results, step.key, index)
        if step.tool in ENDING_TOOLS:
            return _end(run, ENDING_TOOLS[step.tool], results, None, index + 1)
    return _end(run, "done", results, None, len(steps))


async def resume_script(run: Run, steps: Sequence[Step], paused: ScriptResult) -> ScriptResult:
    """Continue a paused script after the human's decision on its approval."""
    if paused.ended != "paused" or paused.approval_id is None:
        return paused
    approval = run.approvals.get(paused.approval_id)
    if approval.status == "pending":
        return replace(paused, events=run.ctx.store.events(run.run_id))
    if approval.status == "rejected":
        return _end(run, "blocked", paused.results, paused.stopped_at, paused.next_step, paused.approval_id)
    return await run_script(run, steps, start=paused.next_step, results=paused.results)


def _end(run: Run, ended: Ended, results: Results, at: str | None, next_step: int,
         approval_id: str | None = None) -> ScriptResult:
    return ScriptResult(ended, results, at, next_step, approval_id, run.ctx.store.events(run.run_id))
