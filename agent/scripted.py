"""Scripted agent (Phase A): runs a fixed list of tool calls through `registry.call`, the exact path the LLM
executor will use (validate -> gate -> preconditions -> tool), and stops at the first result that is not ok.
No LLM, no retries of its own, no judgement: the oracles (hand-written perfect agents) are these step lists.

A step's args are either a dict or a function of the results so far (keyed by step name), so a later step can
use an id an earlier one returned without the script hard-coding database ids. A step with `when` runs only if
its condition on the results so far holds; that is the only branching a script has.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from agent.lifecycle import Run
from agent.tools.registry import ToolResult

Results = dict[str, ToolResult]


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
    ok: bool
    results: Results
    stopped_at: str | None       # the key of the first step that failed
    events: list[dict[str, Any]]  # the run's event log after the last step


async def run_script(run: Run, steps: Sequence[Step]) -> ScriptResult:
    results: Results = {}
    for step in steps:
        if step.when is not None and not step.when(results):
            continue
        args = step.args(results) if callable(step.args) else step.args
        results[step.key] = result = await run.call(step.tool, args)
        if not result.ok:
            return ScriptResult(False, results, step.key, run.ctx.store.events(run.run_id))
    return ScriptResult(True, results, None, run.ctx.store.events(run.run_id))
