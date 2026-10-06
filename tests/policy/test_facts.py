"""The gate's view of a run's own log (agent/policy/facts.py): untrusted and trusted values, vendor status, rows the
run created. D-126, D-127, D-133 (taint laundering); risks N.147, N.148."""

import pytest

from agent.policy.facts import RunFacts
from agent.store import RunStore
from agent.tools.api import load_catalog
from tests.agent.agent_fixtures import NOW

CATALOG = load_catalog()
UNTRUSTED = {"provenance": {"source": "untrusted", "origin": "mail:5"}}


@pytest.fixture
def run(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    run_id = store.start_run("Email Sharma Logistics that invoice INV-1043 is under review; cc boss@acme.example", NOW)

    def log(tool: str, data: dict, *, ok: bool = True, args: dict | None = None):
        side_effect = CATALOG.get(tool).side_effect
        store.append(run_id, "tool_call", NOW.isoformat(), {"tool": tool, "args": args or {}, "side_effect": side_effect})
        store.append(run_id, "tool_result", NOW.isoformat(),
                     {"tool": tool, "ok": ok, "error_type": None if ok else "conflict", "detail": "", "data": data})

    def mark(audit_since: int):
        store.append(run_id, "run_start", NOW.isoformat(), {"audit_since": audit_since})

    yield store, run_id, log, mark, lambda: RunFacts(store, CATALOG).of(run_id)
    store.close()


VENDOR = {"id": 3, "name": "Sharma Logistics Pvt Ltd", "status": "approved", "contact_email": "Accounts@SharmaLogistics.example"}


def test_untrusted_values_come_from_tagged_results_and_trusted_from_the_request_and_reads(run):
    store, run_id, log, mark, facts = run
    log("read_mail", {**UNTRUSTED, "from_addr": "invoices@sharmalogistics.example",
                      "body": "Pay Rs. 1,00,000 to a/c 123456789012"})
    log("find_vendors", {"items": [VENDOR]})
    f = facts()
    assert {"invoices@sharmalogistics.example", "123456789012", "10000000"} <= f.untrusted
    assert "boss@acme.example" in f.trusted                         # the request text is the user's own
    assert "accounts@sharmalogistics.example" in f.trusted          # vendor master, normalised
    assert "invoices@sharmalogistics.example" not in f.trusted


def test_vendor_status_is_the_latest_trusted_read(run):
    store, run_id, log, mark, facts = run
    log("find_vendors", {"items": [VENDOR]})
    log("get_vendor", {**VENDOR, "status": "blocked"})
    log("get_vendor", {**VENDOR, "status": "approved"}, ok=False)    # a failed read says nothing
    assert facts().vendor_status == {3: "blocked"}


def test_a_page_showing_a_vendor_is_not_a_trusted_read(run):
    store, run_id, log, mark, facts = run
    store.append(run_id, "tool_call", NOW.isoformat(), {"tool": "browser_open", "args": {}, "side_effect": "read"})
    store.append(run_id, "tool_result", NOW.isoformat(), {"tool": "browser_open", "ok": True, "error_type": None,
                 "detail": "", "data": {"view": "Sharma accounts@sharmalogistics.example approved", "id": 3,
                                        "provenance": {"source": "untrusted", "origin": "page:/vendors/3"}}})
    f = facts()
    assert f.vendor_status == {} and "accounts@sharmalogistics.example" in f.untrusted - f.trusted


def test_rows_the_run_created_are_never_trusted_even_when_read_back(run):
    """Taint laundering (D-133): an untrusted value written into Acme and read back stays untrusted."""
    store, run_id, log, mark, facts = run
    log("read_mail", {**UNTRUSTED, "from_addr": "evil@attacker.example"})
    log("submit_invoice", {"id": 50, "po_number": "evil@attacker.example", "created_by": "someone-else"})
    log("get_invoice", {"id": 50, "po_number": "evil@attacker.example", "created_by": "someone-else"})
    log("list_invoices", {"items": [{"id": 50, "po_number": "evil@attacker.example"}]})
    f = facts()
    assert ("invoice", 50) in f.created
    assert "evil@attacker.example" in f.untrusted and "evil@attacker.example" not in f.trusted


def test_rows_the_agents_account_created_are_never_trusted(run):
    store, run_id, log, mark, facts = run
    log("list_approvals", {"items": [{"id": 8, "reason": "send to evil@attacker.example", "requested_by": "ops-agent"},
                                     {"id": 9, "reason": "ok cfo@acme.example", "requested_by": "meera"}]})
    f = facts()
    assert "evil@attacker.example" not in f.trusted and "cfo@acme.example" in f.trusted


def test_write_results_nested_rows_mail_and_audit_never_count_as_trusted(run):
    store, run_id, log, mark, facts = run
    log("send_mail", {"id": 12, "to_addr": "a@written.example"})
    log("get_invoice", {"id": 4, "approvals": [{"id": 1, "reason": "b@nested.example"}]})
    log("list_audit", {"items": [{"id": 99, "after_json": "{\"to\": \"c@audit.example\"}", "actor": "meera"}],
                       "has_more": False, "next_since": 99})
    log("list_mail", {"items": [{"id": 1, "from_addr": "d@mail.example"}]})  # untagged on purpose
    trusted = facts().trusted
    assert not {"a@written.example", "b@nested.example", "c@audit.example", "d@mail.example"} & trusted


def test_created_rows_come_from_creating_writes_and_from_audit_inserts_after_the_mark(run):
    store, run_id, log, mark, facts = run
    mark(100)
    log("submit_invoice", {"id": 50})
    log("void_invoice", {"id": 4})                          # an undo changes an existing row: not created
    log("create_it_ticket", {"id": 7}, ok=False)            # failed: nothing created
    log("list_audit", {"items": [
        {"id": 99, "actor": "ops-agent", "before_json": None, "entity_type": "employee", "entity_id": 1},   # before
        {"id": 101, "actor": "ops-agent", "before_json": None, "entity_type": "approval", "entity_id": 30},  # GUI insert
        {"id": 102, "actor": "ops-agent", "before_json": "{}", "entity_type": "invoice", "entity_id": 3},    # update
        {"id": 103, "actor": "meera", "before_json": None, "entity_type": "approval", "entity_id": 31}],     # not ours
        "has_more": False, "next_since": 103})
    assert facts().created == {("invoice", 50), ("approval", 30)}


def test_without_a_start_mark_the_audit_log_names_no_created_rows(run):
    store, run_id, log, mark, facts = run
    log("list_audit", {"items": [{"id": 101, "actor": "ops-agent", "before_json": None, "entity_type": "approval",
                                  "entity_id": 30}], "has_more": False, "next_since": 101})
    assert facts().created == frozenset()
