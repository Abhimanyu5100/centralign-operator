"""Shared fixtures for the agent tests: a fixed `now`, a run context on a temporary run store, small tools."""

import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agent.policy.gate import Decision, ToolCall
from agent.store import RunStore
from agent.tools.registry import Registry, RunContext, ToolResult, ToolSpec

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 10, 7, 10, 30, tzinfo=IST)


class AllowAllGate:
    """No rules at all: for tests of the registry, tools and lifecycle mechanics only. It lives in tests, never in
    agent/; the operator always runs with the policy gate (tests/agent/test_lifecycle.py checks start_run)."""

    def check(self, call: ToolCall) -> Decision:
        return Decision(effect="allow", reason="allow-all test gate: no rules evaluated")


class EchoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(description="Text to echo back")


class InvoiceArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vendor_id: int = Field(description="Vendor id from the vendor master")
    amount_paise: int = Field(description="Total including tax, in paise")
    invoice_date: date = Field(description="Invoice date, ISO format")
    idempotency_key: str = Field(description="Idempotency key for this write")


class LoginArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(description="Acme user name")
    password: str = Field(description="Acme password")
    echo_secret: bool = Field(default=False, description="Test only: the tool returns the password in its result")


async def echo(args: EchoArgs, ctx: RunContext) -> ToolResult:
    return ToolResult(ok=True, detail=f"echo {args.text}", data={"text": args.text})


async def create_invoice(args: InvoiceArgs, ctx: RunContext) -> ToolResult:
    return ToolResult(ok=True, data={"invoice_id": 1, "invoice_date": args.invoice_date.isoformat()})


async def void_invoice(args: EchoArgs, ctx: RunContext) -> ToolResult:
    return ToolResult(ok=True)


async def login(args: LoginArgs, ctx: RunContext) -> ToolResult:
    if args.echo_secret:
        return ToolResult(ok=True, detail=f"logged in with {args.password}",
                          data={"nested": {"list": [f"pw={args.password}"]}, "plain": args.password})
    return ToolResult(ok=True, detail="logged in")


def spec(**overrides) -> ToolSpec:
    """A valid read tool; override any field."""
    fields = dict(name="echo", description="Echo the text back.", args_model=EchoArgs, side_effect="read",
                  channel="api", fn=echo)
    fields.update(overrides)
    return ToolSpec(**fields)


def invoice_spec(**overrides) -> ToolSpec:
    fields = dict(name="create_invoice", description="Create an invoice in Acme.", args_model=InvoiceArgs,
                  side_effect="reversible_write", channel="api", fn=create_invoice, undo="void_invoice",
                  transport_args=("idempotency_key",))
    fields.update(overrides)
    return ToolSpec(**fields)


def void_spec() -> ToolSpec:
    return spec(name="void_invoice", description="Void an invoice.", side_effect="irreversible_write",
                fn=void_invoice, no_undo_reason="a void cannot be reversed")


def login_spec() -> ToolSpec:
    return spec(name="login", description="Log in to Acme.", args_model=LoginArgs, fn=login,
                sensitive_args=("password",))


INVOICE_ARGS = {"vendor_id": 3, "amount_paise": 6_240_000, "invoice_date": "2026-10-03", "idempotency_key": "k1"}


class FixedGate:
    """A stand-in gate that returns one decision (or raises) and records what it saw."""

    def __init__(self, decision=None, raises: Exception | None = None):
        self.decision = decision if decision is not None else Decision(effect="allow", reason="test allow")
        self.raises = raises
        self.seen: list[ToolCall] = []

    def check(self, call: ToolCall):
        self.seen.append(call)
        if self.raises:
            raise self.raises
        return self.decision


def ctx_for(tmp_path: Path) -> RunContext:
    store = RunStore(tmp_path / "runs.db")
    return RunContext(run_id=store.start_run("test request", NOW), now=NOW, store=store)


def registry_with(gate, *specs: ToolSpec) -> Registry:
    registry = Registry(gate)
    for s in specs:
        registry.register(s)
    registry.validate()
    return registry


def call(registry: Registry, name: str, args, ctx: RunContext) -> ToolResult:
    return asyncio.run(registry.call(name, args, ctx))


def event_types(ctx: RunContext) -> list[str]:
    return [e["type"] for e in ctx.store.events(ctx.run_id)]
