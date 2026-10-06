"""Tool registry (agent/tools/registry.py): the contract, typed results and registry.call.

Risks 3.1 (phantom tool), 3.2 / N.122 (argument validation), 5.2 (typed results), P.2 / N.121 (gate fails closed),
N.119 (side effect from the spec), N.123 (redaction), N.128 (fingerprint), 7.5 / X.8 (every step logged)."""

import json
import sqlite3

import pytest
from pydantic import BaseModel, ConfigDict, Field

from acme.web import ERROR_TYPES as ACME_WEB_ERROR_TYPES
from agent.policy.gate import GATE_ERROR, Decision, HttpRequest, PolicyGate
from agent.tools.registry import (ACME_ERROR_TYPES, AGENT_ERROR_TYPES, ERROR_TYPES, Check, Registry, RegistryError,
                                  RunContext, ToolResult, build_registry, fingerprint)
from tests.agent.agent_fixtures import (INVOICE_ARGS, NOW, FixedGate, call, ctx_for, event_types, invoice_spec,
                                        login_spec, registry_with, spec, void_spec)

# --- the contract: registration fails loudly ------------------------------------------------------------------


class LooseArgs(BaseModel):
    text: str = Field(description="Text")


class UndescribedArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


def sync_fn(args, ctx):
    return ToolResult(ok=True)


BAD_SPECS = {
    "missing schema": dict(args_model=None),
    "schema is not a model": dict(args_model=dict),
    "bad name": dict(name="Echo-Tool"),
    "empty description": dict(description="  "),
    "two-line description": dict(description="Echo.\nAnd more."),
    "long description": dict(description="x" * 121),
    "unknown fields allowed": dict(args_model=LooseArgs),
    "argument without description": dict(args_model=UndescribedArgs),
    "sensitive arg not an argument": dict(sensitive_args=("password",)),
    "transport arg not an argument": dict(transport_args=("idempotency_key",)),
    "sync tool function": dict(fn=sync_fn),
    "read with an undo": dict(undo="void_invoice"),
    "read with a no-undo reason": dict(no_undo_reason="n/a"),
    "reversible write without undo": dict(side_effect="reversible_write"),
    "reversible write with a no-undo reason": dict(side_effect="reversible_write", undo="x", no_undo_reason="n/a"),
    "irreversible write without a reason": dict(side_effect="irreversible_write"),
    "irreversible write with an undo": dict(side_effect="irreversible_write", undo="x", no_undo_reason="n/a"),
    "external comms without a reason": dict(side_effect="external_comms"),
}


@pytest.mark.parametrize("case", BAD_SPECS)
def test_a_spec_that_breaks_the_contract_is_refused(case):
    with pytest.raises(RegistryError):
        Registry(PolicyGate()).register(spec(**BAD_SPECS[case]))


def test_valid_specs_of_every_side_effect_register():
    registry = registry_with(PolicyGate(), spec(), invoice_spec(), void_spec(), login_spec(),
                             spec(name="send_mail", side_effect="external_comms", no_undo_reason="mail cannot be recalled"))
    assert {s.name for s in registry.specs()} == {"echo", "create_invoice", "void_invoice", "login", "send_mail"}


def test_a_duplicate_name_is_refused():
    registry = Registry(PolicyGate())
    registry.register(spec())
    with pytest.raises(RegistryError, match="already registered"):
        registry.register(spec(description="Another echo."))


@pytest.mark.parametrize("undo_target", [None, "read"])
def test_validate_refuses_an_undo_that_is_not_a_registered_write_tool(undo_target):
    registry = Registry(PolicyGate())
    registry.register(invoice_spec())
    if undo_target == "read":
        registry.register(spec(name="void_invoice"))
    with pytest.raises(RegistryError, match="void_invoice"):
        registry.validate()


def test_the_llm_schema_has_name_description_and_described_parameters():
    schema = invoice_spec().llm_schema()
    assert schema["name"] == "create_invoice" and schema["description"] == "Create an invoice in Acme."
    props = schema["parameters"]["properties"]
    assert set(props) == {"vendor_id", "amount_paise", "invoice_date", "idempotency_key"}
    assert all(p["description"] for p in props.values())
    json.dumps(schema)  # JSON-serialisable as is


def test_build_registry_uses_the_policy_gate():
    assert isinstance(build_registry().gate, PolicyGate)


# --- typed results -------------------------------------------------------------------------------------------


def test_agent_error_types_cover_every_acme_error_type():
    assert set(ACME_WEB_ERROR_TYPES) <= set(ERROR_TYPES)
    assert set(ACME_ERROR_TYPES) == set(ACME_WEB_ERROR_TYPES)  # a new Acme type must be added here on purpose


def test_agent_error_types_include_the_transport_and_gate_outcomes():
    assert {"timeout", "connection_error", "policy_denied", "approval_required"} <= set(AGENT_ERROR_TYPES)
    assert len(set(ERROR_TYPES)) == len(ERROR_TYPES)


@pytest.mark.parametrize("fields", [dict(ok=True, error_type="conflict"), dict(ok=False),
                                    dict(ok=False, error_type="made_up"), dict(ok=True, extra=1)])
def test_a_malformed_result_is_refused(fields):
    with pytest.raises(ValueError):
        ToolResult(**fields)


def test_run_context_needs_an_aware_now(tmp_path):
    ctx = ctx_for(tmp_path)
    with pytest.raises(ValueError):
        RunContext(run_id=ctx.run_id, now=NOW.replace(tzinfo=None), store=ctx.store)


# --- registry.call: the happy path and the event log ---------------------------------------------------------


def test_an_allowed_call_runs_and_logs_call_decision_result_in_order(tmp_path):
    ctx = ctx_for(tmp_path)
    result = call(registry_with(PolicyGate(), spec()), "echo", {"text": "hi"}, ctx)
    assert result == ToolResult(ok=True, detail="echo hi", data={"text": "hi"})
    events = ctx.store.events(ctx.run_id)
    assert [(e["seq"], e["type"]) for e in events] == [(1, "tool_call"), (2, "policy_decision"), (3, "tool_result")]
    assert {e["logical_time"] for e in events} == {NOW.isoformat()}
    tool_call, decision, tool_result = (e["payload"] for e in events)
    assert tool_call["tool"] == "echo" and tool_call["args"] == {"text": "hi"}
    assert tool_call["side_effect"] == "read" and tool_call["channel"] == "api" and len(tool_call["fingerprint"]) == 64
    assert decision == {"tool": "echo", "gate": "PolicyGate", "effect": "allow", "policy_ids": [],
                        "reason": "pass-through gate (Day 2): no rules evaluated"}
    assert tool_result["ok"] is True and isinstance(tool_result["duration_ms"], int)


def test_iso_dates_are_accepted_and_the_tool_gets_typed_values(tmp_path):
    ctx = ctx_for(tmp_path)
    registry = registry_with(PolicyGate(), invoice_spec(), void_spec())
    result = call(registry, "create_invoice", INVOICE_ARGS, ctx)
    assert result.ok and result.data["invoice_date"] == "2026-10-03"


# --- unknown tools and bad arguments: logged, never gated, never run ------------------------------------------


def test_an_unknown_tool_suggests_close_names_and_logs_only_call_and_result(tmp_path):
    ctx, gate = ctx_for(tmp_path), FixedGate()
    result = call(registry_with(gate, spec()), "ecko", {"text": "hi"}, ctx)
    assert result.error_type == "unknown_tool" and "did you mean echo?" in result.detail
    assert result.data["known"] == ["echo"]
    assert event_types(ctx) == ["tool_call", "tool_result"] and gate.seen == []


BAD_ARGS = {
    "string for an int": {**INVOICE_ARGS, "amount_paise": "6240000"},
    "true for an int": {**INVOICE_ARGS, "vendor_id": True},
    "float for an int": {**INVOICE_ARGS, "amount_paise": 62400.5},
    "unknown key": {**INVOICE_ARGS, "note": "x"},
    "caller tries to set the side effect": {**INVOICE_ARGS, "side_effect": "read"},
    "missing key": {k: v for k, v in INVOICE_ARGS.items() if k != "vendor_id"},
    "bad date": {**INVOICE_ARGS, "invoice_date": "03/10/2026"},
    "not an object": ["vendor_id", 3],
    "not JSON at all": {**INVOICE_ARGS, "vendor_id": {1, 2}},
}


@pytest.mark.parametrize("case", BAD_ARGS)
def test_bad_arguments_are_invalid_args_and_neither_gated_nor_run(tmp_path, case):
    ctx, gate = ctx_for(tmp_path), FixedGate()
    ran = []

    async def tool(args, ctx):
        ran.append(args)
        return ToolResult(ok=True)

    registry = registry_with(gate, invoice_spec(fn=tool), void_spec())
    result = call(registry, "create_invoice", BAD_ARGS[case], ctx)
    assert result.error_type == "invalid_args" and result.detail
    assert ran == [] and gate.seen == []
    assert event_types(ctx) == ["tool_call", "tool_result"]


def test_the_invalid_args_detail_names_the_field(tmp_path):
    ctx = ctx_for(tmp_path)
    result = call(registry_with(PolicyGate(), invoice_spec(), void_spec()), "create_invoice",
                  BAD_ARGS["string for an int"], ctx)
    assert result.detail.startswith("amount_paise:")


# --- the gate's decision is obeyed; the gate fails closed ----------------------------------------------------


def _counting_tool():
    ran = []

    async def tool(args, ctx):
        ran.append(args)
        return ToolResult(ok=True)
    return ran, tool


def test_a_deny_returns_policy_denied_and_the_tool_does_not_run(tmp_path):
    ctx, (ran, tool) = ctx_for(tmp_path), _counting_tool()
    gate = FixedGate(Decision(effect="deny", policy_ids=["ORG-004", "ORG-006"], reason="no admin paths"))
    result = call(registry_with(gate, spec(fn=tool)), "echo", {"text": "hi"}, ctx)
    assert result.error_type == "policy_denied" and result.data == {"policy_ids": ["ORG-004", "ORG-006"]}
    assert "ORG-004, ORG-006" in result.detail and ran == []
    assert event_types(ctx) == ["tool_call", "policy_decision", "tool_result"]


def test_require_approval_returns_the_fingerprint_and_the_tool_does_not_run(tmp_path):
    ctx, (ran, tool) = ctx_for(tmp_path), _counting_tool()
    gate = FixedGate(Decision(effect="require_approval", policy_ids=["ORG-005"], reason="external email"))
    result = call(registry_with(gate, invoice_spec(fn=tool), void_spec()), "create_invoice", INVOICE_ARGS, ctx)
    assert result.error_type == "approval_required" and ran == []
    expected = fingerprint("create_invoice", {**INVOICE_ARGS}, ("idempotency_key",))
    assert result.data == {"policy_ids": ["ORG-005"], "fingerprint": expected}


@pytest.mark.parametrize("gate", [FixedGate(raises=RuntimeError("rules file vanished")), FixedGate(decision="allow"),
                                  FixedGate(decision={"effect": "allow"})], ids=["raises", "string", "dict"])
def test_a_broken_gate_denies_with_gate_error_and_the_tool_does_not_run(tmp_path, gate):
    ctx, (ran, tool) = ctx_for(tmp_path), _counting_tool()
    result = call(registry_with(gate, spec(fn=tool)), "echo", {"text": "hi"}, ctx)
    assert result.error_type == "policy_denied" and result.data == {"policy_ids": [GATE_ERROR]} and ran == []
    decision = ctx.store.events(ctx.run_id)[1]["payload"]
    assert decision["effect"] == "deny" and decision["policy_ids"] == [GATE_ERROR]


def test_the_gate_sees_side_effect_channel_and_request_from_the_spec(tmp_path):
    ctx, gate = ctx_for(tmp_path), FixedGate()
    registry = registry_with(gate, invoice_spec(request_of=lambda a: HttpRequest(method="POST", path="/api/invoices")),
                             void_spec())
    call(registry, "create_invoice", INVOICE_ARGS, ctx)
    (seen,) = gate.seen
    assert (seen.side_effect, seen.channel, seen.run_id, seen.now) == ("reversible_write", "api", ctx.run_id, NOW)
    assert seen.request == HttpRequest(method="POST", path="/api/invoices")
    assert seen.args == INVOICE_ARGS


def test_request_of_rejecting_the_args_is_invalid_args_and_a_crash_is_tool_crashed(tmp_path):
    def rejects(args):
        raise ValueError("path must start with /api/")

    def crashes(args):
        raise RuntimeError("bug")

    for request_of, expected in [(rejects, "invalid_args"), (crashes, "tool_crashed")]:
        ctx, gate = ctx_for(tmp_path / expected), FixedGate()
        registry = registry_with(gate, spec(request_of=request_of))
        assert call(registry, "echo", {"text": "hi"}, ctx).error_type == expected and gate.seen == []


# --- the tool itself fails: typed, never raised --------------------------------------------------------------


async def _raises(args, ctx):
    raise KeyError("boom")


async def _times_out(args, ctx):
    raise TimeoutError("read timed out")


async def _returns_junk(args, ctx):
    return {"ok": True}


@pytest.mark.parametrize("fn,error_type", [(_raises, "tool_crashed"), (_times_out, "timeout"),
                                           (_returns_junk, "tool_crashed")])
def test_a_failing_tool_gives_a_typed_result(tmp_path, fn, error_type):
    ctx = ctx_for(tmp_path)
    result = call(registry_with(PolicyGate(), spec(fn=fn)), "echo", {"text": "hi"}, ctx)
    assert result.error_type == error_type
    assert event_types(ctx) == ["tool_call", "policy_decision", "tool_result"]


# --- preconditions: after the gate, before the tool, logged as events of the call ----------------------------


def _precondition(ok: bool, seen: list):
    async def check(args, ctx):
        seen.append(args.text)
        return ToolResult(ok=True, data={"found": 1}) if ok else ToolResult.fail("conflict", "already entered")
    return Check(description="invoice not entered yet", fn=check)


def test_a_holding_precondition_is_logged_and_the_tool_runs(tmp_path):
    ctx, seen, (ran, tool) = ctx_for(tmp_path), [], _counting_tool()
    result = call(registry_with(PolicyGate(), spec(fn=tool, preconditions=(_precondition(True, seen),))),
                  "echo", {"text": "hi"}, ctx)
    assert result.ok and seen == ["hi"] and len(ran) == 1
    events = ctx.store.events(ctx.run_id)
    assert [e["type"] for e in events] == ["tool_call", "policy_decision", "precondition", "tool_result"]
    assert events[2]["payload"]["check"] == "invoice not entered yet" and events[2]["payload"]["data"] == {"found": 1}


def test_a_failing_precondition_stops_the_tool(tmp_path):
    ctx, seen, (ran, tool) = ctx_for(tmp_path), [], _counting_tool()
    result = call(registry_with(PolicyGate(), spec(fn=tool, preconditions=(_precondition(False, seen),))),
                  "echo", {"text": "hi"}, ctx)
    assert result.error_type == "precondition_failed" and "already entered" in result.detail and ran == []
    assert event_types(ctx) == ["tool_call", "policy_decision", "precondition", "tool_result"]


def test_a_denied_call_runs_no_precondition(tmp_path):
    ctx, seen = ctx_for(tmp_path), []
    gate = FixedGate(Decision(effect="deny", policy_ids=["ORG-004"], reason="no"))
    call(registry_with(gate, spec(preconditions=(_precondition(True, seen),))), "echo", {"text": "hi"}, ctx)
    assert seen == []


def test_a_crashing_precondition_is_tool_crashed(tmp_path):
    ctx, (ran, tool) = ctx_for(tmp_path), _counting_tool()
    result = call(registry_with(PolicyGate(), spec(fn=tool, preconditions=(Check("x", _raises),))),
                  "echo", {"text": "hi"}, ctx)
    assert result.error_type == "tool_crashed" and ran == []


# --- redaction: a sensitive argument never reaches the log or the caller (N.123) ------------------------------

SECRET = "s3cret-Pa55word"


def _raw_log(ctx: RunContext) -> str:
    db = sqlite3.connect(ctx.store.path)
    return json.dumps(db.execute("SELECT * FROM events").fetchall())


def test_a_sensitive_argument_is_redacted_in_the_logged_args(tmp_path):
    ctx = ctx_for(tmp_path)
    result = call(registry_with(PolicyGate(), login_spec()), "login", {"username": "ops-agent", "password": SECRET}, ctx)
    assert result.ok
    assert SECRET not in _raw_log(ctx)
    assert ctx.store.events(ctx.run_id)[0]["payload"]["args"]["password"] == "***"


def test_a_secret_echoed_in_the_result_is_redacted_in_the_log_and_for_the_caller(tmp_path):
    ctx = ctx_for(tmp_path)
    args = {"username": "ops-agent", "password": SECRET, "echo_secret": True}
    result = call(registry_with(PolicyGate(), login_spec()), "login", args, ctx)
    assert SECRET not in result.model_dump_json() and SECRET not in _raw_log(ctx)
    assert result.detail == "logged in with ***" and result.data == {"nested": {"list": ["pw=***"]}, "plain": "***"}


def test_a_secret_in_invalid_args_or_a_gate_reason_is_redacted(tmp_path):
    ctx = ctx_for(tmp_path)
    call(registry_with(PolicyGate(), login_spec()), "login", {"username": 7, "password": SECRET}, ctx)
    gate = FixedGate(Decision(effect="deny", policy_ids=["ORG-004"], reason=f"saw {SECRET}"))
    result = call(registry_with(gate, login_spec()), "login", {"username": "u", "password": SECRET}, ctx)
    assert SECRET not in _raw_log(ctx) and SECRET not in result.detail


# --- fingerprint (N.128, D-103) ------------------------------------------------------------------------------


def test_fingerprint_ignores_key_order_and_transport_args_but_not_business_args():
    transport = ("idempotency_key",)
    base = fingerprint("create_invoice", INVOICE_ARGS, transport)
    assert fingerprint("create_invoice", dict(reversed(list(INVOICE_ARGS.items()))), transport) == base
    assert fingerprint("create_invoice", {**INVOICE_ARGS, "idempotency_key": "k2"}, transport) == base
    assert fingerprint("create_invoice", {**INVOICE_ARGS, "amount_paise": 6_240_001}, transport) != base
    assert fingerprint("create_invoice", {**INVOICE_ARGS, "vendor_id": 4}, transport) != base
    assert fingerprint("void_invoice", INVOICE_ARGS, transport) != base
    assert fingerprint("create_invoice", INVOICE_ARGS) != base  # without the transport list the key counts


def test_through_the_registry_a_new_idempotency_key_keeps_the_fingerprint_and_a_new_amount_changes_it(tmp_path):
    ctx = ctx_for(tmp_path)
    registry = registry_with(PolicyGate(), invoice_spec(), void_spec())
    for args in [INVOICE_ARGS, {**INVOICE_ARGS, "idempotency_key": "k2"}, {**INVOICE_ARGS, "amount_paise": 100}]:
        call(registry, "create_invoice", args, ctx)
    prints = [e["payload"]["fingerprint"] for e in ctx.store.events(ctx.run_id) if e["type"] == "tool_call"]
    assert prints[0] == prints[1] != prints[2]



def test_a_sensitive_argument_of_the_wrong_type_is_redacted_too(tmp_path):
    ctx = ctx_for(tmp_path)
    result = call(registry_with(PolicyGate(), login_spec()), "login", {"username": "u", "password": 98765432}, ctx)
    assert result.error_type == "invalid_args" and result.detail.startswith("password:")
    assert "98765432" not in _raw_log(ctx) and "98765432" not in result.detail


def test_a_short_secret_is_redacted_only_as_a_whole_value(tmp_path):
    # a 1-3 character secret would otherwise erase every matching substring of every logged string (Day 2.2)
    ctx = ctx_for(tmp_path)
    result = call(registry_with(PolicyGate(), login_spec()), "login",
                  {"username": "cab driver", "password": "ab", "echo_secret": True}, ctx)
    assert result.data["plain"] == "***"
    assert result.data["nested"] == {"list": ["pw=ab"]}  # inside other text: left alone
    assert "cab driver" in _raw_log(ctx)


def test_a_four_character_secret_is_still_redacted_inside_text(tmp_path):
    ctx = ctx_for(tmp_path)
    result = call(registry_with(PolicyGate(), login_spec()), "login",
                  {"username": "u", "password": "abcd", "echo_secret": True}, ctx)
    assert result.data["nested"] == {"list": ["pw=***"]} and "abcd" not in _raw_log(ctx)


# --- per-call side effect never exceeds the declared worst case (Day 2.R) --------------------------------------

@pytest.mark.parametrize("declared,per_call,runs", [
    ("read", "reversible_write", False), ("reversible_write", "irreversible_write", False),
    ("irreversible_write", "external_comms", False), ("irreversible_write", "irreversible_write", True),
    ("external_comms", "read", True), ("irreversible_write", "reversible_write", True),
])
def test_a_per_call_side_effect_stronger_than_declared_fails_closed(tmp_path, declared, per_call, runs):
    ran = []

    async def tool(args, ctx):
        ran.append(args.text)
        return ToolResult(ok=True)
    extra = {"no_undo_reason": "test"} if declared in ("irreversible_write", "external_comms") else {}
    extra |= {"undo": "void_invoice"} if declared == "reversible_write" else {}
    stub = spec(name="stub", side_effect=declared, fn=tool, side_effect_of=lambda a: per_call, **extra)
    gate, ctx = FixedGate(), ctx_for(tmp_path)
    result = call(registry_with(gate, spec(), void_spec(), stub), "stub", {"text": "x"}, ctx)
    if runs:
        assert result.ok and ran == ["x"] and gate.seen[0].side_effect == per_call
    else:
        assert result.error_type == "tool_crashed" and "stronger than the declared worst case" in result.detail
        assert ran == [] and gate.seen == []  # not gated, not run
        assert event_types(ctx) == ["tool_call", "tool_result"]
