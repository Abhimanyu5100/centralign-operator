"""The verifier owns a run's status (CLAUDE.md decision 3; Day 3 plan A3). The agent's own messages never set it.

`verify(run)` reads the run as it ended (its event log, its action approvals), checks Acme through three layers
(predicates.py: postconditions and milestone predicates; side_effects.py: the audit log since the run started),
then `decide_status` turns that evidence into one canonical status. The whole verdict is logged as one
`verifier_result` event, which is the only place the report takes the status from. An exception or a timeout
anywhere gives `unverified`, never `completed` (6.7).
"""

import asyncio
from dataclasses import dataclass, field, replace

from pydantic import BaseModel

from agent.failures import classify
from agent.plan import Plan, coverage_warnings, plan_problems
from agent.policy.facts import calls
from agent.tools.registry import ToolResult
from agent.verifier.predicates import Check, MilestoneCheck, milestones, postconditions
from agent.verifier.side_effects import SideEffects, side_effects

DEFAULT_TIMEOUT_SECONDS = 120.0


class Verdict(BaseModel):
    status: str
    reasons: list[str] = []
    notes: list[str] = []          # worth reporting, not a failure on their own (a write Acme never stored)
    postconditions: list[Check] = []
    milestones: list[MilestoneCheck] = []
    side_effects: SideEffects | None = None


@dataclass(frozen=True)
class Evidence:
    """Everything `decide_status` looks at, all taken from runtime artifacts (never from the agent's words)."""
    asked: bool = False             # an ask_user call ended the run
    infeasible: bool = False        # a declare_infeasible call ended the run
    wrote: bool = False             # the audit log shows the run's account changed something
    rejected: bool = False          # an action approval of this run was rejected
    refused: bool = False           # the run's last call was refused on policy (gate deny, Acme 403 or ORG id)
    pending: bool = False           # an action approval of this run waits in the inbox
    has_milestones: bool = False
    unverifiable: bool = False      # a critical milestone has no readable effect
    failures: list[str] = field(default_factory=list)   # postconditions, critical milestones, side effects
    minor: list[str] = field(default_factory=list)      # non-critical milestones not met
    awaits: bool = False            # a met milestone leaves a record waiting for a business approval


def decide_status(e: Evidence) -> tuple[str, list[str]]:
    """The canonical run status (CLAUDE.md "Run statuses"); the first rule that applies wins."""
    if (e.asked or e.infeasible) and e.wrote:
        return "failed", ["the run asked or declined, yet changed records"]
    if e.rejected or e.refused:
        return "blocked_by_policy", ["an action approval was rejected" if e.rejected else "a call was refused on policy"]
    if e.pending:
        return "paused_for_action_approval", ["an action approval waits in the inbox"]
    if e.asked:
        return "needs_clarification", []
    if e.infeasible:
        return "infeasible", []
    if not e.has_milestones:
        return "unverified", ["the plan has no milestones to check"]
    if e.unverifiable:
        return "unverifiable", ["a milestone's effect cannot be read back; a person must confirm it"]
    if e.failures:
        return "failed", e.failures
    if e.minor:
        return "completed_with_exceptions", e.minor
    if e.awaits:
        return "awaiting_business_approval", []
    return "completed", []


async def verify(run, plan: Plan | None = None, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> Verdict:
    try:
        verdict = await asyncio.wait_for(_verify(run, plan if plan is not None else run.plan), timeout)
    except Exception as exc:  # noqa: BLE001 - a verifier that cannot finish never reports success
        reason = "timed out" if isinstance(exc, TimeoutError) else f"{type(exc).__name__}: {exc}"
        verdict = Verdict(status="unverified", reasons=[f"the verifier could not finish: {reason}"])
    run.ctx.store.append(run.run_id, "verifier_result", run.ctx.now.isoformat(), verdict.model_dump())
    return verdict


async def _verify(run, plan: Plan | None) -> Verdict:
    loop = asyncio.get_running_loop()
    absence_at = loop.time() + run.client.read_lag     # one shared wait for every "must not exist" check
    events = run.ctx.store.events(run.run_id)          # the run as it ended, before the verifier reads anything
    pairs = calls(events)
    if plan is not None and (problems := plan_problems(plan, run.registry)):
        return Verdict(status="unverified", reasons=problems)
    ended = {call["tool"] for call, result in pairs if result.get("ok")}
    approvals = run.approvals.for_run(run.run_id)
    last = ToolResult.model_validate({k: v for k, v in pairs[-1][1].items() if k in ToolResult.model_fields}) \
        if pairs else None
    effects = await side_effects(run, events, pairs)
    writes = [(c, r) for c, r in pairs if r.get("ok") and c.get("side_effect") not in (None, "read")]
    post = await postconditions(run, writes)
    evidence = Evidence(asked="ask_user" in ended, infeasible="declare_infeasible" in ended, wrote=effects.wrote,
                        rejected=any(a.status == "rejected" for a in approvals),
                        refused=last is not None and classify(last).kind == "policy_refusal",
                        pending=any(a.status == "pending" for a in approvals),
                        has_milestones=bool(plan and plan.milestones))
    checked: list[MilestoneCheck] = []
    decided = evidence.asked or evidence.infeasible or evidence.rejected or evidence.refused or evidence.pending
    if not decided and plan is not None:  # the status hangs on the milestones only now (N.153)
        checked = await milestones(run, plan, absence_at)
    failures = [f"postcondition {c.name}: {c.detail}" for c in post if not c.ok]
    failures += [f"milestone {m.id} not met: {m.target}" for m in checked
                 if m.critical and not m.ok and not m.unverifiable]
    failures += [f"unexplained change: {', '.join(r['action'] for r in group)}" for group in effects.unexplained]
    # A write the run thought it made but Acme never stored (a silent drop) is a note, not a failure on its own:
    # if it mattered, its postcondition or a milestone fails; if the run read back and redid it, the run recovered.
    notes = [f"claimed but not in the audit log: {w['tool']}" for w in effects.claimed_not_audited]
    forms = [run.client.catalog.form((c.get("request") or {}).get("path", "")) for c, _ in writes
             if c.get("channel") == "gui"]
    notes += coverage_warnings(plan, run.client.catalog, {f.entity for f in forms if f and f.entity})
    evidence = replace(evidence, failures=failures,
                       unverifiable=any(m.unverifiable and m.critical for m in checked),
                       minor=[f"milestone {m.id} not met: {m.target}" for m in checked if not m.critical and not m.ok],
                       awaits=any(m.ok and m.awaits_business_approval for m in checked))
    status, reasons = decide_status(evidence)
    return Verdict(status=status, reasons=reasons, notes=notes, postconditions=post, milestones=checked,
                   side_effects=effects)
