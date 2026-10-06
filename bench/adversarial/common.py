"""What every adversarial script shares: its shape, the runner and fixture tools (D-129).

A script deliberately attempts a forbidden call and passes when it is stopped the expected way: the gate's policy
id, or Acme's own refusal where the rule is `enforced_by: acme` (D-086), and Acme's state shows no change beyond
what the script itself legitimately did (`may_add`). Harness side only; oracles never attempt forbidden calls.

Fixture tools stand in for capabilities the catalog does not have (deciding an approval, writing bank details):
"what if someone added this tool?". Their names start with `test_only_`, and a test proves no such tool is ever in
the real registry, in agent/ or in acme/knowledge/ (tests/agent/test_agent_isolation.py). Each one really sends
its request with the run's own session, so if the gate let it through, Acme would receive it.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from agent.lifecycle import Run, start_run
from agent.plan import Plan
from agent.policy.gate import HttpRequest, Target
from agent.store import RunStore
from agent.tools.registry import ToolResult, ToolSpec

NOW = "2026-10-07T10:30:00+05:30"
TEST_ONLY = "test_only_"


@dataclass(frozen=True)
class Script:
    name: str
    seed: str
    plan: Plan
    expected: str                                       # the stop this script must meet, in words
    attempt: Callable[[Run, Any], Awaitable[list[str]]]  # (run, acme) -> problems; empty means stopped as expected
    may_add: dict[str, int] = field(default_factory=dict)  # rows the script itself may add (e.g. T6's invoice)


@dataclass
class Outcome:
    name: str
    expected: str
    problems: list[str]
    run_id: str

    @property
    def passed(self) -> bool:
        return not self.problems


def fixture_tool(run: Run, name: str, args_model: type[BaseModel], method: str, path: str, *,
                 trust_sensitive: tuple[str, ...] = (), target: Callable[[Any], Target | None] | None = None) -> ToolSpec:
    """Register a `test_only_` irreversible-write tool on this run's registry only. `path` may name args as {arg}."""
    if not name.startswith(TEST_ONLY):
        raise ValueError(f"a fixture tool's name must start with {TEST_ONLY!r}")

    def filled(args: BaseModel) -> str:
        return path.format(**args.model_dump(mode="json"))

    async def fn(args: BaseModel, ctx) -> ToolResult:
        reply = await run.client._authed(method, filled(args), body=args.model_dump(mode="json"))
        return reply.result

    spec = ToolSpec(name=name, description=f"Fixture tool for an adversarial script: {method} {path}.",
                    args_model=args_model, side_effect="irreversible_write", channel="api", fn=fn,
                    no_undo_reason="an adversarial fixture: it must never run",
                    trust_sensitive_args=trust_sensitive, target_of=target,
                    request_of=lambda args: HttpRequest(method=method, path=filled(args)))
    return run.registry.register(spec)


def expect(result: ToolResult, error_type: str, *policy_ids: str) -> list[str]:
    """Problems if `result` is not `error_type` citing every one of `policy_ids`."""
    cited = result.data.get("policy_ids", [])
    problems = [] if result.error_type == error_type else [f"expected {error_type}, got {result.error_type}: "
                                                           f"{result.detail[:200]}"]
    return problems + [f"{p} not cited (cited: {cited})" for p in policy_ids if p not in cited]


async def run_one(acme: Any, script: Script, store: RunStore) -> Outcome:
    acme.admin("POST", "/__admin/reset", seed=script.seed, now=NOW)
    snapshot = acme.admin("POST", "/__admin/snapshot")["snapshot"]
    run = start_run(f"adversarial: {script.name}", datetime.fromisoformat(NOW), store=store,
                    config=acme.agent_config(), plan=script.plan)
    try:
        begun = await run.begin()
        problems = await script.attempt(run, acme) if begun.ok else [f"run could not start: {begun.detail}"]
    except Exception as exc:  # noqa: BLE001 - a crashing script is a failed script, reported with the rest
        problems = [f"script crashed: {type(exc).__name__}: {exc}"]
    finally:
        await run.close()
    diff = acme.admin("GET", "/__admin/diff", since=snapshot)["tables"]
    for table, change in diff.items():
        if table == "audit_log":
            continue
        if change["changed"] or change["removed"]:
            problems.append(f"{table}: existing rows changed or removed")
        if len(change["added"]) > script.may_add.get(table, 0):
            problems.append(f"{table}: {len(change['added'])} row(s) added, at most {script.may_add.get(table, 0)}")
    return Outcome(script.name, script.expected, problems, run.run_id)


def findings(run: Run) -> list[dict[str, Any]]:
    return [e["payload"] for e in run.ctx.store.events(run.run_id) if e["type"] == "security_finding"]


def approvals_filed(run: Run) -> list[dict[str, Any]]:
    return [e["payload"] for e in run.ctx.store.events(run.run_id)
            if e["type"] == "approval" and e["payload"]["action"] == "requested"]
