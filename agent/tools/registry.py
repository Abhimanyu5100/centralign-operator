"""Tool registry: the uniform tool contract and the one path every tool call takes.

`registry.call(name, args, ctx)`: find the tool -> validate the args -> `gate.check` -> preconditions -> the tool.
Each step is logged in the run store as an event of this call. A bad call never raises: the caller (the scripted
agent now, the LLM executor from Day 4) always gets a typed `ToolResult` back.
"""

import difflib
import hashlib
import inspect
import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


from agent.policy.gate import GATE_ERROR, Channel, Decision, HttpRequest, PolicyGate, SideEffect, ToolCall
from agent.store import RunStore

# Acme's API error types, passed through unchanged (a test keeps this equal to acme/web.py ERROR_TYPES) ...
ACME_ERROR_TYPES = (
    "invalid_request", "invalid_input", "not_found", "forbidden", "conflict", "idempotency_key_required",
    "idempotency_key_reused", "unsupported_media_type", "login_required", "session_expired",
    "invalid_credentials", "server_error",
)
# ... and the agent's own: registry outcomes and transport failures.
AGENT_ERROR_TYPES = (
    "unknown_tool", "invalid_args", "precondition_failed", "policy_denied", "approval_required",
    "timeout", "connection_error", "tool_crashed",
)
ERROR_TYPES = ACME_ERROR_TYPES + AGENT_ERROR_TYPES
SIDE_EFFECTS = get_args(SideEffect)
# Strength of a side effect class, weakest first; external_comms counts as the strongest (it cannot be recalled).
STRENGTH = {"read": 0, "reversible_write": 1, "irreversible_write": 2, "external_comms": 3}


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    error_type: str | None = None
    detail: str = ""
    data: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _typed(self) -> "ToolResult":
        if self.ok != (self.error_type is None):
            raise ValueError("an ok result has no error_type and a failed result must have one")
        if self.error_type is not None and self.error_type not in ERROR_TYPES:
            raise ValueError(f"undeclared error_type {self.error_type!r}")
        return self

    @classmethod
    def fail(cls, error_type: str, detail: str, **data: Any) -> "ToolResult":
        return cls(ok=False, error_type=error_type, detail=detail, data=data)


@dataclass(frozen=True)
class RunContext:
    run_id: str
    now: datetime        # the run's frozen business time; nothing in agent/ reads the wall clock for it
    store: RunStore

    def __post_init__(self) -> None:
        if self.now.tzinfo is None:
            raise ValueError("ctx.now must carry a time zone (+05:30)")


@dataclass(frozen=True)
class Check:
    """A precondition `fn(args, ctx)` (run by the registry before the tool) or a postcondition
    `fn(args, result, ctx)` (run by the verifier, Day 3). Returns a ToolResult; ok means the condition holds."""
    description: str
    fn: Callable[..., Awaitable[ToolResult]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str                                  # one line, shown to the LLM
    args_model: type[BaseModel]                       # the JSON schema the LLM sees comes from this model
    side_effect: SideEffect
    channel: Channel
    fn: Callable[[Any, RunContext], Awaitable[ToolResult]]
    undo: str | None = None                           # compensating tool, required for reversible writes
    no_undo_reason: str | None = None                 # required for irreversible writes and external comms
    preconditions: tuple[Check, ...] = ()
    postconditions: tuple[Check, ...] = ()
    sensitive_args: tuple[str, ...] = ()              # shown as *** in logs and results (N.123)
    transport_args: tuple[str, ...] = ()              # e.g. an idempotency key: left out of the fingerprint
    request_of: Callable[[Any], HttpRequest] | None = None   # the HTTP request the call will make, if known
    # A tool whose effect depends on its target (a GUI click: a link reads, a form submit writes) names it per call;
    # `side_effect` is then the declared worst case: a stronger answer fails closed, the tool does not run (D-117).
    side_effect_of: Callable[[Any], SideEffect] | None = None

    def llm_schema(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "parameters": self.args_model.model_json_schema()}


class RegistryError(ValueError):
    """A tool spec breaks the contract. Raised when tools are registered, never during a run."""


_NAME = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


def _contract_problems(spec: ToolSpec) -> list[str]:
    model = spec.args_model
    if not (isinstance(model, type) and issubclass(model, BaseModel)):
        return ["args_model must be a pydantic model (it is the tool's JSON schema)"]
    problems = []
    if not _NAME.fullmatch(spec.name):
        problems.append("name must be lower_snake_case")
    if not spec.description.strip() or "\n" in spec.description or len(spec.description) > 120:
        problems.append("description must be one non-empty line of at most 120 characters")
    if model.model_config.get("extra") != "forbid":
        problems.append("args_model must forbid unknown fields")
    for prop, schema in model.model_json_schema().get("properties", {}).items():
        if not schema.get("description"):
            problems.append(f"argument {prop!r} has no description")
    for arg in spec.sensitive_args + spec.transport_args:
        if arg not in model.model_fields:
            problems.append(f"{arg!r} is listed as sensitive or transport but is not an argument")
    if not inspect.iscoroutinefunction(spec.fn):
        problems.append("fn must be an async function")
    if spec.side_effect == "read" and (spec.undo or spec.no_undo_reason):
        problems.append("a read has no undo")
    if spec.side_effect == "reversible_write" and (not spec.undo or spec.no_undo_reason):
        problems.append("a reversible write must name its undo tool")
    if spec.side_effect in ("irreversible_write", "external_comms") and (spec.undo or not spec.no_undo_reason):
        problems.append(f"an {spec.side_effect} has no undo and must say why in no_undo_reason")
    return problems


def fingerprint(tool: str, args: dict[str, Any], transport_args: tuple[str, ...] = ()) -> str:
    """Identity of a call for action approvals (D-103): same tool and business args, same fingerprint."""
    business = {k: v for k, v in args.items() if k not in transport_args}
    text = json.dumps({"tool": tool, "args": business}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()


def _secret_values(spec: ToolSpec, args: Any) -> list[str]:
    """The caller's values for the spec's sensitive args, as text (a password may arrive as a number)."""
    if not isinstance(args, dict):
        return []
    return [str(v) for k, v in args.items() if k in spec.sensitive_args
            and isinstance(v, (str, int, float)) and not isinstance(v, bool) and str(v)]


MIN_SUBSTRING_SECRET = 4  # a shorter secret ("ab") is replaced only as a whole value, never inside other text


def _redact(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and str(value) in secrets:
        return "***"
    if isinstance(value, str):
        if value in secrets:
            return "***"
        for secret in secrets:
            if len(secret) >= MIN_SUBSTRING_SECRET:
                value = value.replace(secret, "***")
        return value
    if isinstance(value, dict):
        return {k: _redact(v, secrets) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(v, secrets) for v in value]
    return value


def _explain(exc: Exception) -> str:
    if isinstance(exc, ValidationError):  # without input values, which may hold a secret
        return "; ".join(f"{'.'.join(map(str, e['loc'])) or 'args'}: {e['msg']}"
                         for e in exc.errors(include_url=False, include_input=False))
    return f"arguments must be a JSON object: {exc}"


class Registry:
    def __init__(self, gate: PolicyGate):
        self.gate = gate
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> ToolSpec:
        problems = _contract_problems(spec)
        if spec.name in self._tools:
            problems.append("a tool with this name is already registered")
        if problems:
            raise RegistryError(f"{spec.name}: " + "; ".join(problems))
        self._tools[spec.name] = spec
        return spec

    def validate(self) -> None:
        """After all tools are registered: every undo names a registered write tool."""
        for spec in self._tools.values():
            target = self._tools.get(spec.undo) if spec.undo else None
            if spec.undo and (target is None or target.side_effect == "read"):
                raise RegistryError(f"{spec.name}: undo {spec.undo!r} is not a registered write tool")

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def specs(self) -> list[ToolSpec]:
        return list(self._tools.values())

    async def call(self, name: str, args: dict[str, Any], ctx: RunContext) -> ToolResult:
        started = time.perf_counter()  # duration only, never business time
        spec = self._tools.get(name)
        if spec is None:
            close = difflib.get_close_matches(name, list(self._tools), n=3)
            hint = f"; did you mean {', '.join(close)}?" if close else ""
            result = ToolResult.fail("unknown_tool", f"no tool named {name!r}{hint}", known=sorted(self._tools))
            return self._log_attempt(ctx, name, args, [], result, started)

        secrets = _secret_values(spec, args)
        try:  # validated as JSON, like Acme's API: ISO dates are fine, "62400" for an int is not (N.122)
            parsed = spec.args_model.model_validate_json(json.dumps(args), strict=True)
            request = spec.request_of(parsed) if spec.request_of else None
            side_effect = spec.side_effect_of(parsed) if spec.side_effect_of else spec.side_effect
            if side_effect not in SIDE_EFFECTS:
                raise RuntimeError(f"side_effect_of returned {side_effect!r}")
            if STRENGTH[side_effect] > STRENGTH[spec.side_effect]:  # fail closed: never stronger than declared
                raise RuntimeError(f"side_effect_of returned {side_effect!r}, stronger than the declared worst "
                                   f"case {spec.side_effect!r}")
        except (TypeError, ValueError) as exc:  # ValidationError is a ValueError
            return self._log_attempt(ctx, name, args, secrets, ToolResult.fail("invalid_args", _explain(exc)), started)
        except Exception as exc:  # a bug in the spec's request_of
            result = ToolResult.fail("tool_crashed", f"request_of / side_effect_of: {type(exc).__name__}: {exc}")
            return self._log_attempt(ctx, name, args, secrets, result, started)

        clean = parsed.model_dump(mode="json")
        call = ToolCall(run_id=ctx.run_id, now=ctx.now, tool=name, args=clean, side_effect=side_effect,
                        channel=spec.channel, request=request,
                        fingerprint=fingerprint(name, clean, spec.transport_args))
        self._log(ctx, "tool_call", call.model_dump(mode="json", exclude={"run_id", "now"}), secrets)

        decision = self._decide(call)
        self._log(ctx, "policy_decision", {"tool": name, "gate": type(self.gate).__name__,
                                           **decision.model_dump()}, secrets)
        if decision.effect == "deny":
            result = ToolResult.fail("policy_denied", f"{', '.join(decision.policy_ids)}: {decision.reason}",
                                     policy_ids=decision.policy_ids)
        elif decision.effect == "require_approval":
            result = ToolResult.fail("approval_required", f"{', '.join(decision.policy_ids)}: {decision.reason}",
                                     policy_ids=decision.policy_ids, fingerprint=call.fingerprint)
        else:
            result = await self._run(spec, parsed, ctx, secrets)
        return self._finish(ctx, name, result, secrets, started)

    def _decide(self, call: ToolCall) -> Decision:
        """Fail closed: a gate that raises or returns anything but a Decision denies the call (N.121)."""
        try:
            decision = self.gate.check(call)
            if not isinstance(decision, Decision):
                raise TypeError(f"gate returned {type(decision).__name__}, not a Decision")
            return decision
        except Exception as exc:
            return Decision(effect="deny", policy_ids=[GATE_ERROR], reason=f"gate failed: {type(exc).__name__}: {exc}")

    async def _run(self, spec: ToolSpec, parsed: BaseModel, ctx: RunContext, secrets: list[str]) -> ToolResult:
        for check in spec.preconditions:  # reads, logged as events of this call
            try:
                held = await check.fn(parsed, ctx)
                if not isinstance(held, ToolResult):
                    raise TypeError(f"returned {type(held).__name__}, not a ToolResult")
            except Exception as exc:
                return ToolResult.fail("tool_crashed", f"precondition {check.description!r}: {type(exc).__name__}: {exc}")
            self._log(ctx, "precondition", {"tool": spec.name, "check": check.description,
                                            **held.model_dump()}, secrets)
            if not held.ok:
                return ToolResult.fail("precondition_failed", f"{check.description}: {held.detail}")
        try:
            result = await spec.fn(parsed, ctx)
        except TimeoutError as exc:
            return ToolResult.fail("timeout", f"{spec.name} timed out: {exc}")
        except Exception as exc:
            return ToolResult.fail("tool_crashed", f"{type(exc).__name__}: {exc}")
        if not isinstance(result, ToolResult):
            return ToolResult.fail("tool_crashed", f"{spec.name} returned {type(result).__name__}, not a ToolResult")
        return result

    def _log_attempt(self, ctx: RunContext, name: str, args: Any, secrets: list[str], result: ToolResult,
                     started: float) -> ToolResult:
        """Unknown tool or invalid args: tool_call and tool_result only, no policy decision (nothing could run)."""
        self._log(ctx, "tool_call", {"tool": name, "args": args}, secrets)
        return self._finish(ctx, name, result, secrets, started)

    def _finish(self, ctx: RunContext, name: str, result: ToolResult, secrets: list[str], started: float) -> ToolResult:
        result = ToolResult.model_validate(_redact(result.model_dump(), secrets))  # the caller never sees a secret
        self._log(ctx, "tool_result", {"tool": name, **result.model_dump(),
                                       "duration_ms": round((time.perf_counter() - started) * 1000)}, [])
        return result

    def _log(self, ctx: RunContext, type: str, payload: dict[str, Any], secrets: list[str]) -> None:
        # A failed write to the log propagates: the tool_call event is written before the tool runs,
        # so nothing ever acts unlogged.
        ctx.store.append(ctx.run_id, type, ctx.now.isoformat(), _redact(payload, secrets))


def build_registry(gate: PolicyGate | None = None, client: Any = None, browser: Any = None) -> Registry:
    """The operator's registry for one run: the API tools from the endpoint catalog bound to `client` (that run's
    AcmeClient; a fresh one from config when None), the local file tools, and the browser tools bound to `browser`
    (that run's BrowserSession). Nothing does I/O until a tool is called."""
    from agent.config import load_config  # imported here: the tool modules import this one
    from agent.tools.api import AcmeClient, api_tools, load_catalog
    from agent.tools.browser import BrowserSession, browser_tools
    from agent.tools.files import file_tools

    registry = Registry(gate or PolicyGate())
    client = client or AcmeClient(load_config(), load_catalog())
    for spec in [*api_tools(client), *file_tools(), *browser_tools(browser or BrowserSession(client))]:
        registry.register(spec)
    registry.validate()
    return registry
