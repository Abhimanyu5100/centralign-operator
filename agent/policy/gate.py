"""Policy gate: decides allow / deny / require_approval for one tool call, before the tool runs.

The gate is a pure function of the call (and, from Day 3, of the policy file and read-only lookups). It does
no I/O and writes no log: `registry.call` builds the `ToolCall`, asks `check`, logs the `Decision` and acts
on it. Day 2 ships a pass-through that always allows. Day 3 replaces the body of `check` (and gives the
constructor the policy file); `ToolCall`, `Decision` and every caller stay as they are (D-101).
"""

from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

SideEffect = Literal["read", "reversible_write", "irreversible_write", "external_comms"]
Channel = Literal["api", "code", "gui"]
Effect = Literal["allow", "deny", "require_approval"]

# Reserved id for the registry's fail-closed path (the gate raised or returned something that is not a Decision).
GATE_ERROR = "GATE-ERROR"


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HttpRequest(_Frozen):
    """The HTTP request a call will make, when the tool can say so before running (for `request_matches`)."""
    method: str
    path: str


class ToolCall(_Frozen):
    """One call as the gate sees it. Built only by the registry: `side_effect`, `channel` and `request` come
    from the registered tool spec, never from the caller (N.119)."""
    run_id: str
    now: AwareDatetime
    tool: str
    args: dict[str, Any]          # validated arguments, as JSON values
    side_effect: SideEffect
    channel: Channel
    request: HttpRequest | None = None
    fingerprint: str              # sha256 of tool + business args; an action approval matches on it (D-103)


class Decision(_Frozen):
    effect: Effect
    policy_ids: list[str] = Field(default_factory=list)   # every matching rule, not just the first (D-087)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def _blocks_cite_a_policy(self) -> "Decision":
        if self.effect != "allow" and not self.policy_ids:
            raise ValueError(f"a {self.effect} decision must name at least one policy id")
        return self


class PolicyGate:
    """Day 2: pass-through. Every call is allowed; the registry still logs the decision."""

    def check(self, call: ToolCall) -> Decision:
        return Decision(effect="allow", policy_ids=[], reason="pass-through gate (Day 2): no rules evaluated")

