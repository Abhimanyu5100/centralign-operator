"""Run lifecycle: start a run (run id, frozen now, run store, the policy gate, a registry bound to this run's own
Acme session), mark where it starts in Acme's audit log, and roll it back (register 7.3, 5.4).

Every run gets the policy gate (agent/policy/gate.py) over the policy file, this run's facts and the approval
store; a test may inject another gate, the operator never does (P.2).

Rollback walks the run's successful writes from its own event log, newest first, and calls each write's undo
tool through `registry.call`, so every compensation passes the gate and is logged like any other call. Undo
arguments come only from this run's write results: a row the run did not create is never touched. Every undo
tool reads back first (`target_state`), so an entity that is already void or cancelled is reported
`already_done` and rolling back twice is safe. Writes with no undo (sent mail) are listed, not hidden.

A browser submit returns a page, not a row, so GUI writes are found in Acme's audit log instead (D-128): rows
INSERTED by the run's account through the `ui` channel since the run's start mark, newest first, each undone by
the undo of the API write that creates that entity. That audit read is logged, so the gate's facts count those rows
as created by the run and ORG-008 lets their undo through. It assumes one run per account at a time (X.7).
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from agent.config import load_config
from agent.plan import Plan
from agent.policy.approvals import ApprovalStore
from agent.policy.facts import RunFacts, inserted
from agent.policy.gate import PolicyGate
from agent.policy.loader import load_policies
from agent.store import RunStore
from agent.tools.api import AcmeClient, load_catalog
from agent.tools.browser import BrowserSession
from agent.tools.registry import Gate, Registry, RunContext, ToolResult, build_registry
from agent.verifier.side_effects import read_audit

WRITES = ("reversible_write", "irreversible_write", "external_comms")


@dataclass
class Run:
    ctx: RunContext
    registry: Registry
    client: AcmeClient
    browser: BrowserSession
    approvals: ApprovalStore
    plan: Plan | None = None

    @property
    def run_id(self) -> str:
        return self.ctx.run_id

    async def call(self, tool: str, args: Mapping[str, Any]) -> ToolResult:
        return await self.registry.call(tool, dict(args), self.ctx)

    async def begin(self) -> ToolResult:
        """Record, once, the last id in Acme's audit log before the run does anything (a `run_start` event). The
        verifier's side-effect check and the gate's `created` facts read the audit log from that mark."""
        events = self.ctx.store.events(self.run_id)
        if any(e["type"] == "run_start" for e in events):
            return ToolResult(ok=True, detail="already started")
        since = 0
        while True:
            page = await self.call("list_audit", {"since": since, "limit": 1000})
            if not page.ok:
                return page
            since = page.data["next_since"]
            if not page.data["has_more"]:
                break
        self.ctx.store.append(self.run_id, "run_start", self.ctx.now.isoformat(), {"audit_since": since})
        return ToolResult(ok=True, detail=f"audit start mark {since}", data={"audit_since": since})

    async def close(self) -> None:
        await self.browser.close()
        await self.client.aclose()


def start_run(request: str, now: datetime, *, store: RunStore | None = None, config: Mapping[str, str] | None = None,
              gate: Gate | None = None, transport: httpx.AsyncBaseTransport | None = None,
              plan: Plan | None = None) -> Run:
    """`now` is the run's frozen business time: the task file's `now` when the harness runs a task, the caller's clock for a live
    request (agent/ never reads the wall clock itself). One HTTP client and one browser context, so one cookie jar
    each, per run; the browser starts only when a browser tool is first called."""
    store = store or RunStore()
    config = load_config() if config is None else config
    catalog = load_catalog()
    client = AcmeClient(config, catalog, transport)
    browser = BrowserSession(client, headed=config.get("HEADED") == "1")
    approvals = ApprovalStore(store)
    gate = gate or PolicyGate(load_policies(), RunFacts(store, catalog), approvals)  # a bad policy file raises here
    ctx = RunContext(run_id=store.start_run(request, now), now=now, store=store, sop_id=plan.sop_id if plan else None)
    registry = build_registry(gate, client=client, browser=browser, approvals=approvals)
    return Run(ctx, registry, client, browser, approvals, plan)


def run_writes(events: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """(tool, result data) of every successful write, in order. Calls run one at a time, so each tool_result
    belongs to the tool_call logged just before it."""
    writes, call = [], None
    for event in events:
        if event["type"] == "tool_call":
            call = event["payload"]
        elif event["type"] == "tool_result" and call is not None:
            if event["payload"]["ok"] and call.get("side_effect") in WRITES:
                writes.append((call["tool"], event["payload"]["data"]))
            call = None
    return writes


@dataclass
class Rollback:
    undone: list[dict[str, Any]] = field(default_factory=list)          # one entry per compensating call
    not_compensable: list[dict[str, Any]] = field(default_factory=list)  # writes with no undo, and why

    @property
    def ok(self) -> bool:
        return all(u["ok"] for u in self.undone)


async def rollback(run: Run) -> Rollback:
    report, seen, gui = Rollback(), set(), False
    undo_tools = {spec.undo for spec in run.registry.specs() if spec.undo}
    for tool, data in reversed(run_writes(run.ctx.store.events(run.run_id))):
        spec = run.registry.get(tool)
        if spec is None or tool in undo_tools:  # an earlier rollback's own compensations
            continue
        if spec.channel == "gui":  # a page, not a row: found in the audit log below (D-128)
            gui = True
            continue
        if spec.side_effect != "reversible_write":
            report.not_compensable.append({"tool": tool, "reason": spec.no_undo_reason, "id": data.get("id")})
            continue
        try:
            undo_tool, args = run.client.catalog.undo_call(tool, data)
        except KeyError as exc:
            report.undone.append({"tool": spec.undo, "ok": False, "detail": f"{tool} result lacks {exc}"})
            continue
        await _undo(run, report, seen, undo_tool, args)
    if gui:
        await _undo_gui_rows(run, report, seen)
    return report


async def _undo(run: Run, report: Rollback, seen: set, undo_tool: str, args: dict[str, Any]) -> None:
    key = (undo_tool, json.dumps(args, sort_keys=True))
    if key in seen:  # the same row written twice (an idempotent replay) is undone once
        return
    seen.add(key)
    result = await run.call(undo_tool, args)
    report.undone.append({"tool": undo_tool, "args": args, "ok": result.ok, "error_type": result.error_type,
                          "already_done": bool(result.data.get("already_done")), "detail": result.detail})


async def _undo_gui_rows(run: Run, report: Rollback, seen: set) -> None:
    catalog = run.client.catalog
    mark = next((e["payload"]["audit_since"] for e in run.ctx.store.events(run.run_id) if e["type"] == "run_start"),
                None)
    if mark is None:
        report.undone.append({"tool": "rollback", "ok": False, "detail": "no start mark: GUI rows cannot be found"})
        return
    rows = await read_audit(run, mark)
    ours = [r for r in rows if r["actor"] == catalog.session.user and r["channel"] == "ui" and inserted(r)]
    for row in reversed(ours):
        creator = next((ep for ep in catalog.tools if ep.entity == row["entity_type"] and ep.side_effect != "read"
                        and not ep.path_params), None)
        if creator is None or creator.undo is None:
            reason = creator.no_undo_reason if creator else "no API tool creates this entity"
            report.not_compensable.append({"tool": f"browser {row['action']}", "reason": reason, "id": row["entity_id"]})
            continue
        undo_tool, args = catalog.undo_call(creator.name, {"id": row["entity_id"]})
        await _undo(run, report, seen, undo_tool, args)
