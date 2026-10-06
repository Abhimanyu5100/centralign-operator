"""Policy gate: decides allow / deny / require_approval for one tool call, before the tool runs.

`check` is a pure function of the call, the policy file and three read-only lookups given to the constructor:
the run's facts (agent/policy/facts.py), the approval store (agent/policy/approvals.py) and the allowlists the
loader validated (`PolicyFile.allowlist`). It writes nothing and logs nothing: `registry.call` builds the
`ToolCall`, asks `check`, logs the `Decision` and acts on it (D-101).

How a decision is made (D-087, D-103, D-126):
1. every rule in policies.yaml is evaluated; a rule matches when ALL its conditions hold;
2. no match: allow;
3. any matching deny: deny, citing every matching rule, strictest first;
4. otherwise every match holds the call: allow only if the approval store has an approved, unconsumed action
   approval for this (run, fingerprint), citing the rules and the approval; else require_approval.
Any exception while deciding is a deny with GATE-ERROR. Rules can only deny or hold, never allow, so a user or
task rule cannot loosen an org rule (P.11).

Each condition is one small function below. It returns None when it does not hold, or a short note saying why it
holds; the notes go into the decision's reason. A value the gate cannot read (a missing argument, a vendor not read
in this run, an unclear recipient, an unknown target) counts as "the rule applies": the gate fails closed.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from typing import Any, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from agent.policy.models import CONDITION_TYPES, MAIL_ALLOWLIST, PolicyFile, Rule
from agent.policy.pathglob import path_matches
from agent.policy.scanner import normalise_value

SideEffect = Literal["read", "reversible_write", "irreversible_write", "external_comms"]
Channel = Literal["api", "code", "gui"]
Effect = Literal["allow", "deny", "require_approval"]

# Reserved id for the fail-closed path (the gate raised, or returned something that is not a Decision).
GATE_ERROR = "GATE-ERROR"
STRICTNESS = {"deny": 0, "require_approval": 1}
LEVEL_ORDER = {"org": 0, "user": 1, "task": 2}
_ADDRESS = re.compile(r"^[^@\s<>,;\"()\[\]\\]+@([^@\s<>,;\"()\[\]\\]+\.[^@\s<>,;\"()\[\]\\]+)$")


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HttpRequest(_Frozen):
    """The HTTP request a call will make, when the tool can say so before running (for `request_matches`)."""
    method: str
    path: str


class Target(_Frozen):
    """The existing record a call changes (an undo tool's invoice, approval, ...), for `target_not_created_by_run`."""
    entity: str
    id: int


class ToolCall(_Frozen):
    """One call as the gate sees it. Built only by the registry: `side_effect`, `channel`, `request`, `target` and
    `trust_sensitive` come from the registered tool spec, never from the caller (N.119)."""
    run_id: str
    now: AwareDatetime
    tool: str
    args: dict[str, Any]          # validated arguments as JSON values, plus a GUI form's fields (D-125)
    side_effect: SideEffect
    channel: Channel
    request: HttpRequest | None = None
    fingerprint: str              # sha256 of tool + business args; an action approval matches on it (D-103)
    sop_id: str | None = None     # the SOP the run follows; None means no SOP matched (ORG-009, D-081)
    trust_sensitive: tuple[str, ...] = ()   # which args are payee, bank details, recipients, amounts (D-131)
    target: Target | None = None


class Decision(_Frozen):
    effect: Effect
    policy_ids: list[str] = Field(default_factory=list)   # every matching rule, strictest first (D-087)
    reason: str = Field(min_length=1)
    approval_id: str | None = None                        # set only when an action approval lets the call run

    @model_validator(mode="after")
    def _blocks_cite_a_policy(self) -> "Decision":
        if self.effect != "allow" and not self.policy_ids:
            raise ValueError(f"a {self.effect} decision must name at least one policy id")
        if self.approval_id and self.effect != "allow":
            raise ValueError("only an allow can rest on an action approval")
        return self


class Approvals(Protocol):
    def usable(self, run_id: str, fingerprint: str) -> str | None: ...


@dataclass
class _View:
    """What a condition may look at: the call, the policy file, and the run's facts (read once, on first use)."""
    call: ToolCall
    policies: PolicyFile
    facts_of: Any

    @cached_property
    def facts(self) -> Any:
        return self.facts_of.of(self.call.run_id)


Note = str | None


def _request_matches(c, call: ToolCall, view: _View) -> Note:
    r = call.request
    if r is None or c.method not in ("*", r.method.upper()):
        return None
    return f"{r.method} {r.path}" if any(path_matches(p, r.path) for p in c.paths) else None


def _tool_in(c, call: ToolCall, view: _View) -> Note:
    return f"tool {call.tool}" if call.tool in c.tools else None


def _side_effect_in(c, call: ToolCall, view: _View) -> Note:
    return call.side_effect if call.side_effect in c.side_effects else None


def _amount_gt(c, call: ToolCall, view: _View) -> Note:
    value = call.args.get(c.arg)
    if not isinstance(value, int) or isinstance(value, bool):
        return f"{c.arg} missing or not an amount in paise"
    return f"{c.arg} {value} above {c.paise}" if value > c.paise else None


def _as_id(value: Any) -> int | None:
    """An id from the API (an integer) or from a GUI form field (its digits as text)."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return int(value) if isinstance(value, str) and value.isdigit() else None


def _vendor_status_not_in(c, call: ToolCall, view: _View) -> Note:
    vendor = _as_id(call.args.get(c.arg))
    if vendor is None:
        return f"{c.arg} missing"
    status = view.facts.vendor_status.get(vendor)
    if status is None:
        return f"vendor {vendor} not read in this run: read it first"
    return f"vendor {vendor} is {status}" if status not in c.statuses else None


def _domain(value: Any) -> str | None:
    match = _ADDRESS.fullmatch(value.strip()) if isinstance(value, str) else None
    return match[1].lower() if match else None


def _recipient_domain_not_in(c, call: ToolCall, view: _View) -> Note:
    domain = _domain(call.args.get(c.arg))
    if domain is None:
        return f"{c.arg} missing or not one plain address"
    return f"recipient domain {domain} not allowlisted" if domain not in view.policies.allowlist(c.allowlist) else None


def _field_source_untrusted(c, call: ToolCall, view: _View) -> Note:
    exempt = {view.policies.internal_domain(MAIL_ALLOWLIST)} if c.exempt_recipient_domains == "internal" else set()
    for arg in call.trust_sensitive:
        if call.args.get(arg) is None or _domain(call.args[arg]) in exempt:
            continue
        value = normalise_value(call.args[arg])
        if value in view.facts.untrusted and value not in view.facts.trusted:
            return f"{arg} seen only in untrusted text"
    return None


def _run_has_no_sop(c, call: ToolCall, view: _View) -> Note:
    return "no SOP for this run" if call.sop_id is None else None


def _target_not_created_by_run(c, call: ToolCall, view: _View) -> Note:
    target = call.target
    if target is None:
        return "no known target record"
    return None if (target.entity, target.id) in view.facts.created else f"{target.entity} {target.id} not created by this run"


CONDITIONS: dict[str, Callable[[Any, ToolCall, _View], Note]] = {
    "request_matches": _request_matches,
    "tool_in": _tool_in,
    "side_effect_in": _side_effect_in,
    "amount_gt": _amount_gt,
    "vendor_status_not_in": _vendor_status_not_in,
    "recipient_domain_not_in": _recipient_domain_not_in,
    "field_source_untrusted": _field_source_untrusted,
    "run_has_no_sop": _run_has_no_sop,
    "target_not_created_by_run": _target_not_created_by_run,
}


class PolicyGate:
    def __init__(self, policies: PolicyFile, facts: Any, approvals: Approvals):
        missing = set(CONDITION_TYPES) - set(CONDITIONS)
        if missing:  # a condition type the schema accepts but nothing evaluates: refuse to start (fail closed)
            raise ValueError(f"the gate has no function for condition types {sorted(missing)}")
        self.policies, self.facts, self.approvals = policies, facts, approvals

    def check(self, call: ToolCall) -> Decision:
        try:
            return self._check(call)
        except Exception as exc:  # noqa: BLE001 - any failure to decide is a deny
            return Decision(effect="deny", policy_ids=[GATE_ERROR], reason=f"gate failed: {type(exc).__name__}: {exc}")

    def _check(self, call: ToolCall) -> Decision:
        view = _View(call, self.policies, self.facts)
        matched: list[tuple[Rule, list[str]]] = []
        for rule in self.policies.rules:
            notes = []
            for cond in rule.when:
                note = CONDITIONS[cond.type](cond, call, view)
                if note is None:
                    break
                notes.append(note)
            else:
                matched.append((rule, notes))
        if not matched:
            return Decision(effect="allow", reason=f"no rule matched ({call.side_effect})")
        matched.sort(key=lambda m: (STRICTNESS[m[0].effect], LEVEL_ORDER[m[0].level], m[0].id))
        ids = [rule.id for rule, _ in matched]
        reason = "; ".join(f"{rule.id} {rule.effect} ({', '.join(notes)}): {rule.message}" for rule, notes in matched)
        if matched[0][0].effect == "deny":
            return Decision(effect="deny", policy_ids=ids, reason=reason)
        approval = self.approvals.usable(call.run_id, call.fingerprint)
        if approval is not None:
            return Decision(effect="allow", policy_ids=ids, reason=f"action approval {approval}; {reason}",
                            approval_id=approval)
        return Decision(effect="require_approval", policy_ids=ids, reason=reason)

