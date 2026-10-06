"""The policy gate's evaluator (agent/policy/gate.py) over the real policies.yaml: every rule passes and fails,
the strictest effect wins, every matching id is cited, approvals lift holds once and never denies, and any error
denies with GATE-ERROR. Risks P.2, P.3, P.8, P.11, 1.3, 1.4, 3.9, N.23, N.144 to N.147; D-087, D-103, D-126, D-127.

API calls are built by the real registry from the real catalog (so `request`, `target` and `trust_sensitive` are the
ones a run would produce) with a gate that only records the call; GUI submits are built as the browser tool builds
them (tests/agent/test_browser_unit.py checks that wiring)."""

import ast
from pathlib import Path

import pytest

from agent.policy import gate as gate_module
from agent.policy.facts import Facts
from agent.policy.gate import GATE_ERROR, Decision, HttpRequest, PolicyGate, Target, ToolCall
from agent.policy.loader import load_policies
from agent.policy.models import PolicyFile
from agent.tools.registry import RunContext, build_registry
from agent.store import RunStore
from tests.agent.agent_fixtures import NOW, FixedGate, call

POLICIES = load_policies()
VENDOR_DOMAIN = "sharmalogistics.example"
APPROVED = Facts(vendor_status={3: "approved", 7: "blocked", 9: "pending"})


class StubFacts:
    def __init__(self, facts: Facts = APPROVED, raises: Exception | None = None):
        self.facts, self.raises = facts, raises

    def of(self, run_id: str) -> Facts:
        if self.raises:
            raise self.raises
        return self.facts


class StubApprovals:
    def __init__(self, approved: dict[tuple[str, str], str] | None = None, raises: Exception | None = None):
        self.approved, self.raises = approved or {}, raises

    def usable(self, run_id: str, fingerprint: str) -> str | None:
        if self.raises:
            raise self.raises
        return self.approved.get((run_id, fingerprint))


def decide(tool_call: ToolCall, facts: Facts = APPROVED, approvals: StubApprovals | None = None,
           policies: PolicyFile = POLICIES) -> Decision:
    return PolicyGate(policies, StubFacts(facts), approvals or StubApprovals()).check(tool_call)


@pytest.fixture
def api(tmp_path):
    """api(tool, args, sop_id=...) -> the ToolCall the real registry would hand the gate."""
    store = RunStore(tmp_path / "runs.db")

    def build(tool: str, args: dict, sop_id: str | None = "process-invoice") -> ToolCall:
        recorder = FixedGate(Decision(effect="deny", policy_ids=["TEST-1"], reason="record only"))
        ctx = RunContext(run_id=store.start_run("r", NOW), now=NOW, store=store, sop_id=sop_id)
        result = call(build_registry(recorder), tool, args, ctx)
        assert result.error_type == "policy_denied", result  # validated, described, never run
        return recorder.seen[0]
    yield build
    store.close()


def gui(path: str, side_effect: str, fields: dict | None = None, trust: tuple[str, ...] = (),
        method: str = "POST", sop_id: str | None = "process-invoice", target: Target | None = None) -> ToolCall:
    """A browser_click as the browser tool describes it (D-125, D-155): the form's fields join the args, and a form
    that changes a record names it as the target."""
    return ToolCall(run_id="r1", now=NOW, tool="browser_click", args={"ref": "b1", **(fields or {})},
                    side_effect=side_effect, channel="gui", request=HttpRequest(method=method, path=path),
                    fingerprint="g" * 64, sop_id=sop_id, trust_sensitive=trust, target=target)


def raw(path: str, method: str = "POST", side_effect: str = "irreversible_write", tool: str = "test_only_raw",
        **extra) -> ToolCall:
    return ToolCall(run_id="r1", now=NOW, tool=tool, args=extra.pop("args", {}), side_effect=side_effect,
                    channel="api", request=HttpRequest(method=method, path=path), fingerprint="f" * 64,
                    sop_id=extra.pop("sop_id", "process-invoice"), **extra)


INVOICE = {"vendor_id": 3, "invoice_no": "INV-1", "invoice_date": "2026-10-03", "due_date": "2026-11-02",
           "amount_paise": 6_240_000, "tax_paise": 951_864}
MAIL = {"subject": "Invoice INV-1043 is under review", "body": "Hello"}


# --- ORG-001 / ORG-003 (enforced by Acme): only bypass attempts are denied ------------------------------------------

@pytest.mark.parametrize("path", ["/api/approvals/3/decide", "/approvals/3/decide"])
def test_deciding_an_approval_is_denied_citing_org001_and_org003(path):
    decision = decide(raw(path))
    assert decision.effect == "deny" and decision.policy_ids[:2] == ["ORG-001", "ORG-003"]


def test_entering_an_over_limit_invoice_is_the_normal_action_and_is_allowed(api):
    decision = decide(api("submit_invoice", INVOICE))
    assert decision == Decision(effect="allow", reason="no rule matched (reversible_write)")


def test_requesting_the_business_approval_is_allowed(api):
    assert decide(api("request_approval", {"entity_type": "invoice", "entity_id": 42})).effect == "allow"


# --- ORG-002: vendor status from this run's own trusted reads (D-127) ---------------------------------------------

@pytest.mark.parametrize("vendor, note", [(7, "vendor 7 is blocked"), (9, "vendor 9 is pending"),
                                          (5, "vendor 5 not read in this run")])
def test_org002_denies_a_vendor_that_is_not_approved_or_not_read(api, vendor, note):
    decision = decide(api("submit_invoice", {**INVOICE, "vendor_id": vendor}))
    assert decision.effect == "deny" and decision.policy_ids == ["ORG-002"] and note in decision.reason


def test_org002_uses_the_latest_read_and_allows_an_approved_vendor(api):
    assert decide(api("submit_invoice", INVOICE)).effect == "allow"
    blocked_later = Facts(vendor_status={3: "blocked"})
    assert decide(api("submit_invoice", INVOICE), facts=blocked_later).policy_ids == ["ORG-002"]


@pytest.mark.parametrize("vendor, effect", [("3", "allow"), ("7", "deny"), ("", "deny"), ("3; drop", "deny")])
def test_org002_sees_the_vendor_a_gui_invoice_form_will_submit(vendor, effect):
    decision = decide(gui("/invoices/new", "reversible_write", {"vendor_id": vendor, "invoice_no": "INV-1"}))
    assert decision.effect == effect


def test_a_gui_invoice_form_without_a_vendor_field_is_denied():
    assert decide(gui("/invoices/new", "reversible_write", {})).policy_ids == ["ORG-002"]


# --- ORG-004: admin endpoints, every spelling, as a request and as a GUI form action (D-088, D-092) ---------------

ADMIN_VARIANTS = ["/__admin/reset", "//__admin/reset", "/api/../__admin/reset", "/%5F%5Fadmin/reset",
                  "/__ADMIN/reset", "/__admin/reset?x=1"]


@pytest.mark.parametrize("path", ADMIN_VARIANTS)
@pytest.mark.parametrize("channel", ["api", "gui"])
def test_org004_catches_every_admin_variant(path, channel):
    tool_call = raw(path) if channel == "api" else gui(path, "irreversible_write")
    decision = decide(tool_call)
    assert decision.effect == "deny" and "ORG-004" in decision.policy_ids


@pytest.mark.parametrize("path", ["http://__admin/reset", "http://127.0.0.1:8100/api/approvals/A-1/approve"])
def test_an_off_site_target_is_no_path_and_is_denied(path):
    decision = decide(gui(path, "read", method="GET"))  # how the browser hands over an off-site target (N.145)
    assert decision.effect == "deny" and "ORG-004" in decision.policy_ids


@pytest.mark.parametrize("path", ["/api/invoices", "/__adminx/reset", "/api/admin-notes", "/invoices/__admin"])
def test_org004_near_misses_are_not_admin_paths(path):
    assert "ORG-004" not in decide(raw(path, method="GET", side_effect="read")).policy_ids


# --- ORG-005: external mail is held; the allowlist comes only from PolicyFile.allowlist (D-064, D-082) ------------

def test_mail_to_a_vendor_domain_is_held_for_approval(api):
    decision = decide(api("send_mail", {"to": f"accounts@{VENDOR_DOMAIN}", **MAIL}, sop_id="notify-vendor"))
    assert decision.effect == "require_approval" and decision.policy_ids == ["ORG-005"]
    assert f"recipient domain {VENDOR_DOMAIN} not allowlisted" in decision.reason


@pytest.mark.parametrize("to", ["priya.nair@acme.example", "someone@partner.example", "Someone@PARTNER.example"])
def test_an_allowlisted_recipient_needs_no_approval(api, to):
    assert decide(api("send_mail", {"to": to, **MAIL}, sop_id="onboard-employee")).effect == "allow"


@pytest.mark.parametrize("to", ["a@acme.example, b@evil.example", "Bob <b@acme.example>", "b@acme.example.evil.example",
                                "not an address"])
def test_an_unclear_recipient_is_held(api, to):
    assert decide(api("send_mail", {"to": to, **MAIL}, sop_id="notify-vendor")).policy_ids == ["ORG-005"]


@pytest.mark.parametrize("fields, held", [({"to": f"a@{VENDOR_DOMAIN}", **MAIL}, True),
                                          ({"to": "a@acme.example", **MAIL}, False), (MAIL, True)])
def test_the_gui_compose_form_is_judged_by_the_recipient_it_will_send_to(fields, held):
    decision = decide(gui("/mail/compose", "external_comms", fields, trust=("to",) if "to" in fields else ()))
    assert (decision.effect == "require_approval") is held and ("ORG-005" in decision.policy_ids) is held


def test_the_gate_reads_no_file():
    """Allowlists come only through PolicyFile.allowlist (D-082): nothing in gate.py opens or reads a file."""
    tree = ast.parse(Path(gate_module.__file__).read_text())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & {"open", "read_text", "read_bytes", "Path", "load_allowlist_domains", "load_policies"}


# --- ORG-006 (enforced by Acme): any bank path is denied as a second line ------------------------------------------

@pytest.mark.parametrize("path", ["/api/vendors/3/bank", "/vendors/3/bank-details", "/api/BANK/x"])
def test_org006_denies_any_bank_path(path):
    decision = decide(raw(path))
    assert decision.effect == "deny" and "ORG-006" in decision.policy_ids


def test_org006_leaves_the_vendor_master_readable(api):
    assert decide(api("find_vendors", {"q": "Sharma"})).effect == "allow"


# --- ORG-007: trust-sensitive values seen only in untrusted text (D-133) --------------------------------------------

def test_a_recipient_copied_from_a_mail_header_is_held_by_org007_too(api):
    facts = Facts(untrusted=frozenset({f"invoices@{VENDOR_DOMAIN}"}), trusted=frozenset({f"accounts@{VENDOR_DOMAIN}"}))
    decision = decide(api("send_mail", {"to": f"invoices@{VENDOR_DOMAIN}", **MAIL}, sop_id="notify-vendor"), facts)
    assert decision.effect == "require_approval" and decision.policy_ids == ["ORG-005", "ORG-007"]
    assert "to seen only in untrusted text" in decision.reason


def test_the_vendor_master_contact_is_trusted_so_only_org005_holds(api):
    facts = Facts(untrusted=frozenset({f"accounts@{VENDOR_DOMAIN}"}), trusted=frozenset({f"accounts@{VENDOR_DOMAIN}"}))
    decision = decide(api("send_mail", {"to": f"accounts@{VENDOR_DOMAIN}", **MAIL}, sop_id="notify-vendor"), facts)
    assert decision.policy_ids == ["ORG-005"]


def test_an_internal_address_seen_only_in_mail_is_exempt(api):
    facts = Facts(untrusted=frozenset({"priya.nair@acme.example"}))
    decision = decide(api("send_mail", {"to": "priya.nair@acme.example", **MAIL}, sop_id="onboard-employee"), facts)
    assert decision.effect == "allow"


def test_a_partner_address_seen_only_in_untrusted_text_still_needs_approval_under_org007(api):
    """D-144: only our own domain is exempt. ORG-005 lets partner mail through, so ORG-007 alone must hold it."""
    facts = Facts(untrusted=frozenset({"orders@partner.example"}))
    decision = decide(api("send_mail", {"to": "orders@partner.example", **MAIL}, sop_id="notify-vendor"), facts)
    assert decision.effect == "require_approval" and decision.policy_ids == ["ORG-007"]
    trusted = Facts(untrusted=facts.untrusted, trusted=frozenset({"orders@partner.example"}))
    assert decide(api("send_mail", {"to": "orders@partner.example", **MAIL}, sop_id="notify-vendor"), trusted).effect == "allow"


def test_an_account_number_from_a_document_on_a_payee_tool_is_held():
    tool_call = raw("/api/vendors/3/payee", args={"account_number": "1234 5678 9012"}, trust_sensitive=("account_number",),
                    side_effect="reversible_write")
    facts = Facts(untrusted=frozenset({"123456789012"}))
    assert decide(tool_call, facts).policy_ids == ["ORG-007"]
    assert decide(tool_call, Facts()).effect == "allow"  # the same call with nothing untrusted seen


# --- ORG-008: irreversible changes to records this run did not create (D-126) --------------------------------------

def test_undoing_a_row_the_run_created_is_not_held(api):
    facts = Facts(vendor_status=APPROVED.vendor_status, created=frozenset({("invoice", 42)}))
    assert decide(api("void_invoice", {"invoice_id": 42}), facts).effect == "allow"


@pytest.mark.parametrize("tool, args, note", [("void_invoice", {"invoice_id": 4}, "invoice 4 not created by this run"),
                                              ("cancel_it_ticket", {"ticket_id": 1}, "it_ticket 1 not created"),
                                              ("cancel_employee", {"employee_id": 7}, "employee 7 not created")])
def test_undoing_a_row_the_run_did_not_create_is_held(api, tool, args, note):
    decision = decide(api(tool, args))
    assert decision.effect == "require_approval" and decision.policy_ids == ["ORG-008"] and note in decision.reason


def test_an_unknown_browser_form_is_held():
    decision = decide(gui("/some/unknown/form", "irreversible_write"))
    assert decision.policy_ids == ["ORG-008"] and "no known target record" in decision.reason


@pytest.mark.parametrize("path", ["/invoices/42/attach-source", "/invoices/42/void"])
def test_attaching_to_or_voiding_the_runs_own_invoice_through_the_browser_is_not_held(path):
    """N.166, D-155: the PI-6 attach (and a GUI void) on an invoice this run entered passes ORG-008."""
    own = Facts(vendor_status=APPROVED.vendor_status, created=frozenset({("invoice", 42)}))
    decision = decide(gui(path, "irreversible_write", {"source_file": "x.pdf"}, target=Target(entity="invoice", id=42)),
                      own)
    assert decision.effect == "allow"


@pytest.mark.parametrize("path", ["/invoices/3/attach-source", "/invoices/3/void"])
def test_attaching_to_or_voiding_a_pre_existing_invoice_through_the_browser_is_held(path):
    decision = decide(gui(path, "irreversible_write", target=Target(entity="invoice", id=3)),
                      Facts(created=frozenset({("invoice", 42)})))
    assert decision.policy_ids == ["ORG-008"] and "invoice 3 not created by this run" in decision.reason


def test_internal_mail_and_reversible_writes_are_not_held_by_org008(api):
    assert decide(api("create_it_ticket", {"type": "laptop", "employee_id": 7}, sop_id="onboard-employee")).effect == "allow"


# --- ORG-009: with no SOP every write needs an action approval (D-081) ---------------------------------------------

@pytest.mark.parametrize("tool, args", [("create_it_ticket", {"type": "laptop", "employee_id": 7}),
                                        ("send_mail", {"to": "a@acme.example", **MAIL})])
def test_with_no_sop_every_write_is_held(api, tool, args):
    decision = decide(api(tool, args, sop_id=None))
    assert decision.effect == "require_approval" and "ORG-009" in decision.policy_ids


def test_with_no_sop_reads_still_run(api):
    assert decide(api("find_vendors", {}, sop_id=None)).effect == "allow"


# --- combining: strictest wins, every id cited, approvals, hierarchy (D-087, D-103, P.11) --------------------------

def test_a_deny_beats_a_hold_and_every_matching_id_is_cited_deny_first():
    tool_call = raw("/__admin/reset", side_effect="irreversible_write", sop_id=None)  # ORG-004 + ORG-008 + ORG-009
    decision = decide(tool_call)
    assert decision.effect == "deny"
    assert decision.policy_ids[0] == "ORG-004" and {"ORG-008", "ORG-009"} <= set(decision.policy_ids)
    assert decision.policy_ids.index("ORG-004") < decision.policy_ids.index("ORG-008")


def test_an_approval_lets_the_held_call_run_and_is_cited(api):
    tool_call = api("send_mail", {"to": f"accounts@{VENDOR_DOMAIN}", **MAIL}, sop_id="notify-vendor")
    decision = decide(tool_call, approvals=StubApprovals({(tool_call.run_id, tool_call.fingerprint): "A-1"}))
    assert (decision.effect, decision.policy_ids, decision.approval_id) == ("allow", ["ORG-005"], "A-1")
    assert decision.reason.startswith("action approval A-1")


def test_an_approval_for_another_call_does_not_apply(api):
    tool_call = api("send_mail", {"to": f"accounts@{VENDOR_DOMAIN}", **MAIL}, sop_id="notify-vendor")
    other = StubApprovals({(tool_call.run_id, "0" * 64): "A-1", ("other-run", tool_call.fingerprint): "A-2"})
    assert decide(tool_call, approvals=other).effect == "require_approval"


def test_an_approval_never_lifts_a_deny():
    tool_call = raw("/api/approvals/3/decide")
    decision = decide(tool_call, approvals=StubApprovals({(tool_call.run_id, tool_call.fingerprint): "A-1"}))
    assert decision.effect == "deny" and decision.approval_id is None


def _policy(*rules: dict) -> PolicyFile:
    policies = PolicyFile.model_validate({"schema_version": 0, "rules": list(rules)})
    policies.attach_allowlists({})
    return policies


def _rule(id_: str, level: str, effect: str) -> dict:
    return {"id": id_, "level": level, "enforced_by": "runtime", "effect": effect, "message": f"{id_} says so",
            "when": [{"type": "tool_in", "tools": ["test_only_raw"]}]}


def test_a_task_rule_cannot_loosen_an_org_rule():
    policies = _policy(_rule("TSK-001", "task", "require_approval"), _rule("ORG-901", "org", "deny"))
    decision = decide(raw("/x"), policies=policies)
    assert decision.effect == "deny" and decision.policy_ids == ["ORG-901", "TSK-001"]


def test_among_equal_effects_org_comes_before_user_before_task():
    policies = _policy(_rule("TSK-001", "task", "require_approval"), _rule("USR-001", "user", "require_approval"),
                       _rule("ORG-901", "org", "require_approval"))
    assert decide(raw("/x"), policies=policies).policy_ids == ["ORG-901", "USR-001", "TSK-001"]


# --- fail closed ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("which", ["facts", "approvals"])
def test_a_lookup_that_fails_denies_with_gate_error(api, which):
    tool_call = api("submit_invoice", INVOICE) if which == "facts" else api(
        "send_mail", {"to": f"a@{VENDOR_DOMAIN}", **MAIL}, sop_id="notify-vendor")
    facts = StubFacts(raises=OSError("run store gone")) if which == "facts" else StubFacts()
    approvals = StubApprovals(raises=OSError("run store gone")) if which == "approvals" else StubApprovals()
    decision = PolicyGate(POLICIES, facts, approvals).check(tool_call)
    assert decision.effect == "deny" and decision.policy_ids == [GATE_ERROR] and "run store gone" in decision.reason


def test_a_condition_type_without_a_function_stops_the_gate_from_starting(monkeypatch):
    monkeypatch.setattr(gate_module, "CONDITIONS", {k: v for k, v in gate_module.CONDITIONS.items()
                                                    if k != "run_has_no_sop"})
    with pytest.raises(ValueError, match="run_has_no_sop"):
        PolicyGate(POLICIES, StubFacts(), StubApprovals())


def test_every_condition_type_has_exactly_one_function():
    from agent.policy.models import CONDITION_TYPES
    assert set(gate_module.CONDITIONS) == set(CONDITION_TYPES)


def test_a_call_with_no_request_never_matches_a_request_rule():
    local = ToolCall(run_id="r1", now=NOW, tool="extract_pdf_text", args={"name": "x.pdf"}, side_effect="read",
                     channel="code", fingerprint="e" * 64, sop_id="process-invoice")
    assert decide(local).effect == "allow"


def test_target_model_is_what_api_undo_tools_report(api):
    assert api("void_invoice", {"invoice_id": 42}).target == Target(entity="invoice", id=42)
    assert api("submit_invoice", INVOICE).target is None  # creating a row changes no existing record
    assert api("send_mail", {"to": "a@acme.example", **MAIL}).trust_sensitive == ("to",)
