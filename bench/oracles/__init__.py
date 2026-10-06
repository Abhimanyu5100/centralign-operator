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


def ref(result: ToolResult, role: str, *, name: str | None = None, contains: str | None = None,
        target: str | None = None) -> str:
    """The ref of the one observed element with this role (and exact name, part of the name, or target such as
    "POST /path"). Zero or two matches is an oracle bug."""
    found = [e for e in result.data["elements"] if e["role"] == role and (name is None or e["name"] == name)
             and (contains is None or contains in e["name"]) and (target is None or e["target"] == target)]
    if len(found) != 1:
        raise LookupError(f"expected one {role} with name={name!r} contains={contains!r} target={target!r}, "
                          f"found {len(found)}")
    return found[0]["ref"]


def shows(result: ToolResult, role: str, contains: str) -> bool:
    return any(e["role"] == role and contains in e["name"] for e in result.data["elements"])


def oracle_for(run_id: str, channel: str = "api") -> Oracle:
    task_id = run_id.partition(":")[0]
    module = task_id if channel == "api" else f"{task_id}_{channel}"
    return importlib.import_module(f"bench.oracles.{module}").RUNS[run_id]
