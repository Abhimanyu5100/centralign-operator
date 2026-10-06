"""Browser tool parts that need no browser (Day 2.3): snapshot parsing, the per-call side effect and request the
gate sees for a click (N.126, D-117), the launch env (D-105, N.92), argument rules (N.138)."""

import asyncio

import pytest

from agent.config import BROWSER_ENV_KEYS, browser_env
from agent.policy.gate import Decision
from agent.tools import browser as browser_module
from agent.tools.api import AcmeClient, load_catalog
from agent.tools.browser import MAX_VIEW_CHARS, BrowserSession, Element, parse_line
from agent.tools.registry import build_registry
from tests.agent.agent_fixtures import FixedGate, call, ctx_for, event_types


@pytest.mark.parametrize("line,parsed", [
    ('- link "Acme home":', (0, "link", "Acme home", "", "")),
    ("    - /url: /invoices", (4, "/url", "", "", "/invoices")),
    ("- text: ops-agent (ops_agent)", (0, "text", "", "", "ops-agent (ops_agent)")),
    ('- heading "New invoice" [level=1]', (0, "heading", "New invoice", " [level=1]", "")),
    ('  - textbox "Invoice number": X-1', (2, "textbox", "Invoice number", "", "X-1")),
    ('- option "Choose one" [selected]', (0, "option", "Choose one", " [selected]", "")),
    ("  - 'row \"Mail #4 – a: b 10:30\"':", (2, "row", "Mail #4 – a: b 10:30", "", "")),  # YAML-quoted (colon)
    ("- text: 'Due: tomorrow'", (0, "text", "", "", "Due: tomorrow")),
    ("- 'link \"It''s: x\"'", (0, "link", "It's: x", "", "")),
    ('- button "Say \\"hi\\""', (0, "button", 'Say "hi"', "", "")),
    ("- status: Invoice saved.", (0, "status", "", "", "Invoice saved.")),
    ("not a list item", None),
])
def test_snapshot_lines_parse(line, parsed):
    assert parse_line(line) == parsed


def test_the_view_cap_is_recorded():
    assert MAX_VIEW_CHARS == 8000  # N.127; tests/e2e/test_browser.py measures real pages against it


# --- the launch env (D-105, N.92) ---------------------------------------------------------------------------------

def test_the_browser_env_is_an_allowlist_without_the_admin_token():
    environ = {"ACME_ADMIN_TOKEN": "secret", "GEMINI_API_KEY": "k", "HOME": "/home/x", "PATH": "/bin", "TMPDIR": "/t"}
    assert browser_env(environ) == {"HOME": "/home/x", "PATH": "/bin", "TMPDIR": "/t"}
    assert "ACME_ADMIN_TOKEN" not in BROWSER_ENV_KEYS


def test_chromium_is_launched_with_exactly_that_env(monkeypatch):
    monkeypatch.setenv("ACME_ADMIN_TOKEN", "secret-token")
    seen = {}

    class Fake:  # stands in for Playwright: records the launch, then stops the session there
        async def start(self):
            return self

        @property
        def chromium(self):
            return self

        async def launch(self, **kwargs):
            seen.update(kwargs)
            raise RuntimeError("stop after launch")

    monkeypatch.setattr(browser_module, "async_playwright", Fake)
    session = BrowserSession(AcmeClient({"ACME_URL": "http://acme.test"}, load_catalog()))
    with pytest.raises(RuntimeError, match="stop after launch"):
        asyncio.run(session.page())
    assert seen["env"] == browser_env() and "ACME_ADMIN_TOKEN" not in seen["env"] and seen["headless"] is True


# --- what the gate sees for a click (N.126, D-117) ----------------------------------------------------------------

def _registry_with(elements: dict[str, Element], gate):
    client = AcmeClient({"ACME_URL": "http://acme.test"}, load_catalog())
    session = BrowserSession(client)
    session.elements = elements
    return build_registry(gate, client=client, browser=session)


ELEMENTS = {
    "l1": Element("l1", "link", "Invoices", 0, href="/invoices"),
    "b2": Element("b2", "button", "Request approval", 0, form=("POST", "/invoices/9/request-approval")),
    "b3": Element("b3", "button", "Void invoice", 0, form=("POST", "/invoices/9/void")),
    "b4": Element("b4", "button", "Apply filters", 0, form=("GET", "/invoices")),
    "b5": Element("b5", "button", "Approve", 0, form=("POST", "/approvals/3/decide")),
    "b6": Element("b6", "button", "Sign out", 0, form=("POST", "/logout")),
    "b7": Element("b7", "button", "Send", 0, form=("POST", "/mail/compose")),
}


@pytest.mark.parametrize("ref,effect,request_", [
    ("l1", "read", ("GET", "/invoices")),
    ("b2", "reversible_write", ("POST", "/invoices/9/request-approval")),
    ("b3", "irreversible_write", ("POST", "/invoices/9/void")),
    ("b4", "read", ("GET", "/invoices")),
    ("b5", "irreversible_write", ("POST", "/approvals/3/decide")),  # a form the catalog does not list: worst case
    ("b6", "read", ("POST", "/logout")),
    ("b7", "external_comms", ("POST", "/mail/compose")),  # the declared worst case must allow it (D-122)
    ("b9", "irreversible_write", None),  # an unknown ref: worst case (the click itself then fails)
])
def test_the_gate_sees_each_clicks_own_side_effect_and_request(tmp_path, ref, effect, request_):
    gate = FixedGate(Decision(effect="deny", policy_ids=["TEST-1"], reason="stop before the browser starts"))
    ctx = ctx_for(tmp_path)
    result = call(_registry_with(ELEMENTS, gate), "browser_click", {"ref": ref}, ctx)
    assert result.error_type == "policy_denied"
    seen = gate.seen[0]
    assert seen.side_effect == effect
    assert (None if seen.request is None else (seen.request.method, seen.request.path)) == request_
    logged = next(e for e in ctx.store.events(ctx.run_id) if e["type"] == "tool_call")["payload"]
    assert logged["side_effect"] == effect  # logged as such
    assert event_types(ctx) == ["tool_call", "policy_decision", "tool_result"]


def test_every_ui_form_in_the_catalog_matches_its_api_twin():
    catalog = load_catalog()
    assert catalog.form_effect("/invoices/42/request-approval") == "reversible_write"
    assert catalog.form_effect("/invoices/42/void") == "irreversible_write"
    assert catalog.form_effect("/invoices/42/void/extra") == "irreversible_write"  # unknown shape: worst case
    assert catalog.form_effect("/mail/compose") == "external_comms"


@pytest.mark.parametrize("path", ["https://evil.example/x", "//evil.example/x", "invoices", "/a b", "/x\\y", ""])
def test_open_only_takes_a_path_on_the_site(tmp_path, path):
    result = call(_registry_with({}, FixedGate()), "browser_open", {"path": path}, ctx_for(tmp_path))
    assert result.error_type == "invalid_args"
