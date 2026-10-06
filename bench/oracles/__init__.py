"""AcmeBench oracles: one hand-written perfect agent per run, as a step list for the scripted agent.

Each module `T<n>.py` defines `RUNS = {run_id: Oracle(...)}` (T9 has three runs, `T9:none/approve/reject`).
Oracles go through the API channel and `registry.call` only, look rows up by business key (never by a database
id, N.113), and never attempt a forbidden call (gate tests live in `bench/adversarial/`, Day 3). An oracle whose
end state fails its checker means the checker is wrong: diagnose it, never loosen it.
"""

import importlib
from dataclasses import dataclass, field
from typing import Any

from agent.scripted import Step
from agent.tools.registry import ToolResult


@dataclass(frozen=True)
class Oracle:
    steps: list[Step]
    pending: str = ""  # expected behaviour only the Day 3 gate or report can show (never counted as passed)
    notes: list[str] = field(default_factory=list)


def item(result: ToolResult, **fields: Any) -> dict[str, Any]:
    """The one item of a list result whose fields equal `fields`. Zero or two matches is an oracle bug."""
    found = [row for row in result.data["items"] if all(row.get(k) == v for k, v in fields.items())]
    if len(found) != 1:
        raise LookupError(f"expected exactly one item with {fields}, found {len(found)}")
    return found[0]


def oracle_for(run_id: str) -> Oracle:
    task_id = run_id.partition(":")[0]
    return importlib.import_module(f"bench.oracles.{task_id}").RUNS[run_id]
