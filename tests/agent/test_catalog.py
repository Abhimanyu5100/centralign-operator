"""The endpoint catalog (acme/knowledge/api.yaml) and the tools generated from it (D-107, N.134)."""

import copy
import json

import pytest
import yaml
from pydantic import ValidationError

from acme.app import create_app
from agent.tools.api import CATALOG_PATH, AcmeClient, Catalog, CatalogError, api_tools, args_model, load_catalog
from agent.tools.registry import build_registry
from tests.agent.agent_fixtures import AllowAllGate

RAW = yaml.safe_load(CATALOG_PATH.read_text())


def _routes() -> set[tuple[str, str]]:
    """(method, path) of every Acme route, from its OpenAPI schema (as the route-protection test walks it)."""
    return {(m.upper(), path) for path, ops in create_app().openapi()["paths"].items() for m in ops}


def _with(change) -> dict:
    raw = copy.deepcopy(RAW)
    change({t["name"]: t for t in raw["tools"]}, raw)
    return raw


def test_the_real_catalog_loads_and_its_registry_validates():
    catalog = load_catalog()
    registry = build_registry(AllowAllGate())
    assert len(catalog.tools) >= 25 and len(registry.specs()) == len(catalog.tools) + 8  # + extract_pdf_text, five browser and two ask tools
    registry.validate()


def test_every_catalog_entry_is_a_real_acme_route_with_that_method():
    routes = _routes()
    missing = [(e.method, e.path) for e in load_catalog().tools if (e.method, e.path) not in routes]
    session = load_catalog().session
    assert missing == [] and (session.login_method, session.login_path) in routes


def test_every_acme_write_route_the_agent_may_use_is_in_the_catalog():
    # the only API writes left out: the business approver's decision (never the agent's, ORG-003)
    routes = {path for method, path in _routes() if method == "POST" and path.startswith("/api/")}
    session = load_catalog().session
    listed = {e.path for e in load_catalog().tools} | {session.login_path, "/api/logout", "/api/approvals/{approval_id}/decide"}
    assert routes - listed == set()


@pytest.mark.parametrize("change,message", [
    (lambda t, r: t["read_mail"].update(side_effect="peek"), "side_effect"),
    (lambda t, r: t["submit_invoice"]["undo"].update(tool="shred_invoice"), "not a write tool"),
    (lambda t, r: t["submit_invoice"]["undo"].update(tool="get_invoice"), "not a write tool"),
    (lambda t, r: t["submit_invoice"]["undo"]["args"].update(bogus="id"), "not an argument of void_invoice"),
    (lambda t, r: t["get_invoice"].update(path="/api/invoices/{invoice}"), "path parameter 'invoice'"),
    (lambda t, r: t["create_it_ticket"].pop("read_back"), "needs a read_back"),
    (lambda t, r: t["create_it_ticket"]["read_back"].update(tool="create_employee"), "not a read tool"),
    (lambda t, r: t["create_it_ticket"]["read_back"]["match"].update(type="kind"), "refers to 'kind'"),
    (lambda t, r: t["list_files"].update(path="/__admin/reset"), "outside the API prefix"),
    (lambda t, r: t["list_files"].update(path="/__ADMIN/reset"), "outside the API prefix"),
    (lambda t, r: t["list_files"].update(path="/api/%5F%5Fadmin/reset"), "encoded"),
    (lambda t, r: t["list_files"].update(path="/api/../__admin/x"), "normalised"),
    (lambda t, r: t["list_files"].update(path="/api//files"), "normalised"),
    (lambda t, r: r["session"].update(login_path="/__admin/login"), "outside the API prefix"),
    (lambda t, r: t["submit_invoice"].update(transport_args=["trace_id"]), "transport_args"),
    (lambda t, r: t["submit_invoice"]["args"]["vendor_id"].update(type="uuid"), "type"),
    (lambda t, r: t["create_payment"].pop("undo"), "reversible write names its undo"),
    (lambda t, r: t["send_mail"].pop("no_undo_reason"), "no_undo_reason"),
    (lambda t, r: t["list_files"].update(method="POST"), "a read is a GET"),
    (lambda t, r: r["tools"].append(copy.deepcopy(t["list_files"])), "duplicate tool name"),
    (lambda t, r: t["read_mail"].update(untrusted="mail:{message}"), "untrusted origin"),
    (lambda t, r: t["list_files"].update(extra_field=1), "extra"),
    (lambda t, r: r["ui_forms"][0].update(same_as="void_invoice"), "not a tool with the same side effect"),
    (lambda t, r: r["ui_forms"][0].update(path="/api/invoices"), "outside the API prefix"),
    (lambda t, r: r["ui_forms"][0].update(side_effect="maybe"), "side_effect"),
    (lambda t, r: r["ui_forms"][0].pop("entity"), "declares its entity"),
    (lambda t, r: r["ui_forms"][0].update(entity="payment"), "differs from submit_invoice"),
    (lambda t, r: r["ui_forms"][3].update(target_param="id"), "not a path parameter"),
    (lambda t, r: t["submit_invoice"].pop("verify"), "names its postcondition read"),
    (lambda t, r: t["submit_invoice"]["verify"].update(tool="submit_invoice"), "not a read tool"),
    (lambda t, r: t["send_mail"]["verify"]["fields"].update(cc="cc"), "names no argument"),
])
def test_the_validator_rejects_an_inconsistent_catalog(change, message):
    with pytest.raises(ValidationError, match=message):
        Catalog.model_validate(_with(change))


def test_an_unreadable_catalog_fails_at_load_time(tmp_path):
    bad = tmp_path / "api.yaml"
    bad.write_text("tools: [")
    with pytest.raises(CatalogError):
        load_catalog(bad)


def test_args_models_are_strict_and_fill_the_path():
    tools = {s.name: s for s in api_tools(AcmeClient({}, load_catalog()))}
    model = tools["void_invoice"].args_model
    assert tools["void_invoice"].request_of(model(invoice_id=7)).path == "/api/invoices/7/void"
    with pytest.raises(ValidationError):
        args_model(load_catalog().get("submit_invoice")).model_validate_json('{"vendor_id": 1, "extra": 2}')
    schema = tools["create_it_ticket"].llm_schema()["parameters"]
    assert schema["properties"]["type"]["enum"] == ["laptop", "accounts"] and schema["required"] == ["type", "employee_id"]
    assert tools["submit_invoice"].transport_args == ("idempotency_key",)


def test_every_write_says_how_a_retry_stays_safe():
    for entry in load_catalog().tools:
        if entry.side_effect != "read":
            assert entry.read_back or "idempotency_key" in entry.transport_args, entry.name


def test_no_tool_or_path_names_the_admin_routes_or_the_database():
    text = json.dumps(RAW).lower()
    assert "__admin" not in text and "acme.db" not in text and "acme/data" not in text


def test_every_ui_post_route_except_the_approvers_is_classified():
    pages = {path for method, path in _routes() if method == "POST" and not path.startswith(("/api/", "/__admin"))}
    listed = {f.path.replace("{", "").replace("}", "") for f in load_catalog().ui_forms}
    unlisted = {p for p in pages if p.replace("{", "").replace("}", "") not in listed}
    assert unlisted == {"/approvals/{approval_id}/decide"}  # never the agent's: unknown, so an irreversible write


@pytest.mark.parametrize("path, target", [
    ("/invoices/42/attach-source", ("invoice", 42)), ("/invoices/42/void", ("invoice", 42)),
    ("/approvals/7/withdraw", ("approval", 7)), ("/payments/3/cancel", ("payment", 3)),
    ("/employees/9/cancel", ("employee", 9)), ("/it-tickets/5/cancel", ("it_ticket", 5)),
    ("/invoices/new", None), ("/invoices/42/request-approval", None), ("/invoices/x/void", None),
])
def test_a_form_that_changes_a_record_names_it_from_its_path(path, target):
    """D-155: the gate's ORG-008 and the verifier's layer 3 read the record a GUI submit changes from its path."""
    form = load_catalog().form(path)
    assert (None if form.target_id(path) is None else (form.entity, form.target_id(path))) == target
