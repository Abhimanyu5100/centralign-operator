"""Browser pages and forms (part 3). Risks N.21, N.22, N.26, N.27, N.34, N.36, N.41-N.48, 3.5.

States are built through the service layer only (N.28); pages are exercised through the real app."""

import re

import pytest

from acme import services as s
from acme.models import EmployeeIn
from acme.seed import state_hash
from tests.acme.conftest import make_client
from tests.acme.htmlutil import Page
from tests.acme.test_services import invoice_in

def token_of(html: str) -> str:
    return re.search(r'name="idempotency_token" value="([^"]+)"', html).group(1)


def count(db, table):
    return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


INVOICE_FORM = dict(vendor_id="2", invoice_no="INV-3001", po_number="PO-1", invoice_date="2026-10-01",
                    due_date="2026-10-31", received_date="", amount="18500.00", tax="2822.03")


def pages(world) -> list[str]:
    return ["/", "/invoices", "/invoices/new", "/invoices/1", f"/invoices/{world['over']['id']}", "/approvals",
            f"/approvals/{world['approval']['id']}", "/payments", "/payments/new", f"/payments/{world['payment']['id']}",
            "/vendors", "/vendors/1", "/employees", "/employees/new", f"/employees/{world['employee']['id']}",
            "/it-tickets", "/it-tickets/new", f"/it-tickets/{world['ticket']['id']}",
            "/invoices?status=approved", "/vendors?q=sharma", "/it-tickets?employee=1",
            "/mail", "/mail?folder=outbox", "/mail/compose", "/mail/1", "/mail/9",
            f"/payments/new?invoice_id={world['ok']['id']}"]


# --- every page: access, names, labels ------------------------------------------------------------


@pytest.mark.parametrize("user", ["agent", "meera"])
def test_every_page_renders_for_a_logged_in_user(request, world, user):
    client = request.getfixturevalue(user)
    for path in pages(world):
        assert client.get(path).status_code == 200, path


def test_every_page_redirects_to_login_without_a_cookie(db_file, world):
    client = make_client(db_file, None)
    for path in pages(world):
        r = client.get(path)
        assert r.status_code == 303 and r.headers["location"].startswith("/login"), path


@pytest.mark.parametrize("user", ["agent", "meera"])
def test_no_duplicate_role_and_name_among_links_and_buttons_on_any_page(request, world, user):
    """N.26 / N.48: Day 2 locators use role + accessible name, so a name must be unique within a page."""
    client = request.getfixturevalue(user)
    for path in pages(world):
        page = Page(client.get(path).text)
        for kind, names in (("link", page.links), ("button", page.buttons)):
            dupes = {n for n in names if names.count(n) > 1}
            assert not dupes, f"{path}: duplicate {kind} names {dupes}"
            assert all(names), f"{path}: a {kind} has no accessible name"


@pytest.mark.parametrize("user", ["agent", "meera"])
def test_every_control_has_a_label(request, world, user):
    client = request.getfixturevalue(user)
    for path in pages(world):
        page = Page(client.get(path).text)
        for control in page.controls:
            assert control.get("id") in page.labels_for, f"{path}: {control} has no <label for>"


def test_list_rows_link_with_unique_names_even_for_same_invoice_number(db, agent):
    """Same vendor and number after a void: the (#id) suffix keeps link names unique."""
    first = s.submit_invoice(db, "ops-agent", "api", invoice_in(invoice_no="INV-7777"))
    s.void_invoice(db, "ops-agent", "api", first["id"])
    s.submit_invoice(db, "ops-agent", "api", invoice_in(invoice_no="INV-7777"))
    names = [n for n in Page(agent.get("/invoices").text).links if n.startswith("INV-7777")]
    assert len(names) == 2 and len(set(names)) == 2


def test_submit_button_name_is_save_invoice_by_default(agent):
    assert "Save invoice" in Page(agent.get("/invoices/new").text).buttons


# --- writes: invoice form ---------------------------------------------------------------------


def post_invoice(client, token=None, **overrides):
    token = token or token_of(client.get("/invoices/new").text)
    return client.post("/invoices/new", data={**INVOICE_FORM, **overrides, "idempotency_token": token})


def test_invoice_form_creates_through_the_service_with_channel_ui_and_redirects(db, agent):
    before = count(db, "invoices")
    r = post_invoice(agent)
    assert r.status_code == 303
    invoice = db.execute("SELECT * FROM invoices ORDER BY id DESC LIMIT 1").fetchone()
    assert r.headers["location"] == f"/invoices/{invoice['id']}"
    assert count(db, "invoices") == before + 1
    assert (invoice["channel"], invoice["created_by"], invoice["amount_paise"], invoice["tax_paise"]) == (
        "ui", "ops-agent", 1_850_000, 282_203)
    assert {row["channel"] for row in db.execute(
        "SELECT channel FROM audit_log WHERE entity_type='invoice' AND entity_id=?", (invoice["id"],))} == {"ui"}


def test_toast_is_shown_once_after_the_redirect(agent):
    location = post_invoice(agent).headers["location"]
    assert any("saved with status" in t for t in Page(agent.get(location).text).status)
    assert Page(agent.get(location).text).status == []


def test_comma_amount_gets_the_exact_hint_and_the_form_keeps_what_was_typed(db, agent):
    before = count(db, "invoices")
    r = post_invoice(agent, amount="1,00,000", invoice_no="INV-KEEP")
    assert r.status_code == 422 and count(db, "invoices") == before
    page = Page(r.text)
    assert ("Total including tax: Enter the amount in rupees without commas, for example 12500.00") in page.alerts
    assert 'id="amount-error"' in r.text and 'aria-invalid="true"' in r.text
    assert 'value="INV-KEEP"' in r.text and 'value="1,00,000"' in r.text


def test_service_rejection_is_an_inline_error_with_the_service_message(db, agent):
    r = post_invoice(agent, due_date="2026-09-01")
    assert r.status_code == 422 and "Due date must be after invoice date" in Page(r.text).alerts
    assert 'id="due_date-error"' in r.text
    post_invoice(agent, invoice_no="INV-DUP")
    dup = post_invoice(agent, invoice_no="INV-DUP")
    assert dup.status_code == 409 and "Duplicate invoice number for this vendor" in Page(dup.text).alerts
    assert 'id="invoice_no-error"' in dup.text


def test_every_problem_is_reported_in_one_post(agent):
    r = agent.post("/invoices/new", data={"idempotency_token": "t"})
    assert r.status_code == 422
    for field in ("vendor_id", "invoice_no", "invoice_date", "due_date", "amount", "tax"):
        assert f'id="{field}-error"' in r.text, field


def test_unknown_vendor_is_a_404_page_not_an_inline_error(agent):
    r = post_invoice(agent, vendor_id="999")
    assert r.status_code == 404 and "Vendor 999 not found" in Page(r.text).alerts


def test_same_token_twice_gives_one_row_and_an_unchanged_state_hash(db, agent):
    token = token_of(agent.get("/invoices/new").text)
    first = post_invoice(agent, token)
    after_first, rows = state_hash(db), count(db, "invoices")
    second = post_invoice(agent, token)
    assert (first.status_code, second.status_code) == (303, 303)
    assert second.headers["location"] == first.headers["location"]
    assert count(db, "invoices") == rows and state_hash(db) == after_first
    assert any("already saved" in t for t in Page(agent.get(second.headers["location"]).text).status)


def test_same_token_with_changed_data_is_refused_not_written(db, agent):
    token = token_of(agent.get("/invoices/new").text)
    post_invoice(agent, token)
    rows = count(db, "invoices")
    r = post_invoice(agent, token, invoice_no="INV-OTHER")
    assert r.status_code == 409 and "already used with different data" in " ".join(Page(r.text).alerts)
    assert count(db, "invoices") == rows


def test_a_rejected_submit_keeps_the_token_so_the_corrected_retry_works(db, agent):
    r = post_invoice(agent, amount="abc")
    token = token_of(r.text)
    assert post_invoice(agent, token, amount="18500.00").status_code == 303


def test_missing_token_is_a_form_level_error(agent):
    r = agent.post("/invoices/new", data=INVOICE_FORM)
    assert r.status_code == 422 and "no valid submission token" in " ".join(Page(r.text).alerts)


# --- writes: payments, employees, tickets, approvals ----------------------------------------------


def test_payment_form_double_submit_creates_one_request(db, agent, world):
    form = {"invoice_id": str(world["ok"]["id"]), "scheduled_date": ""}
    # the fixture's payment already exists: cancel it so this form can create a fresh one
    s.cancel_payment(db, "ops-agent", "api", world["payment"]["id"])
    token = token_of(agent.get("/payments/new").text)
    before = count(db, "payments")
    first = agent.post("/payments/new", data={**form, "idempotency_token": token})
    second = agent.post("/payments/new", data={**form, "idempotency_token": token})
    assert (first.status_code, second.status_code) == (303, 303)
    assert first.headers["location"] == second.headers["location"]
    assert count(db, "payments") == before + 1


def test_payment_for_a_payment_already_requested_is_a_409_inline_error(agent, world):
    r = agent.post("/payments/new", data={"invoice_id": str(world["ok"]["id"]), "idempotency_token": "t1"})
    assert r.status_code == 409 and "already exists for this invoice" in " ".join(Page(r.text).alerts)
    assert 'id="invoice_id-error"' in r.text


def test_employee_form_creates_and_validates(db, agent):
    form = dict(name="New Hire", email="new.hire@acme.example", role="Analyst", department="Finance",
                manager_id="1", start_date="2026-10-12")
    bad = agent.post("/employees/new", data={**form, "email": "x@gmail.com"})
    assert bad.status_code == 422 and "Employee email must be an @acme.example address" in Page(bad.text).alerts
    ok = agent.post("/employees/new", data=form)
    assert ok.status_code == 303
    assert db.execute("SELECT status FROM employees WHERE email='new.hire@acme.example'").fetchone()[0] == "onboarding"


def test_it_ticket_form_has_no_token_so_a_double_submit_makes_two_tickets(db, agent, world):
    """Deliberate (register 3.5): read-before-retry is the only protection for IT tickets."""
    before = count(db, "it_tickets")
    data = {"type": "accounts", "employee_id": str(world["employee"]["id"])}
    assert agent.post("/it-tickets/new", data=data).status_code == 303
    assert agent.post("/it-tickets/new", data=data).status_code == 303
    assert count(db, "it_tickets") == before + 2


def test_request_approval_from_the_invoice_page(db, agent):
    invoice = s.submit_invoice(db, "ops-agent", "api", invoice_in(invoice_no="INV-9100", amount_paise=7_000_000))
    page = Page(agent.get(f"/invoices/{invoice['id']}").text)
    assert "Request approval" in page.buttons
    r = agent.post(f"/invoices/{invoice['id']}/request-approval", data={"reason": "over limit"})
    assert r.status_code == 303
    row = db.execute("SELECT * FROM approvals ORDER BY id DESC LIMIT 1").fetchone()
    assert (row["entity_id"], row["status"], row["requested_by"]) == (invoice["id"], "pending", "ops-agent")
    assert db.execute("SELECT channel FROM audit_log WHERE entity_type='approval' ORDER BY id DESC").fetchone()[0] == "ui"


# --- roles and identity (N.22, N.34, N.43) --------------------------------------------------------


def test_ops_agent_sees_no_approve_or_reject_and_meera_does(agent, meera, world):
    path = f"/approvals/{world['approval']['id']}"
    agent_buttons = Page(agent.get(path).text).buttons
    assert "Approve" not in agent_buttons and "Reject" not in agent_buttons
    assert "Withdraw approval request" in agent_buttons
    meera_buttons = Page(meera.get(path).text).buttons
    assert {"Approve", "Reject"} <= set(meera_buttons) and "Withdraw approval request" not in meera_buttons


def test_ops_agent_posting_a_decision_directly_gets_403_and_nothing_changes(db, agent, world):
    before = state_hash(db)
    r = agent.post(f"/approvals/{world['approval']['id']}/decide", data={"decision": "approve"})
    assert r.status_code == 403
    assert state_hash(db) == before


def test_spoofed_actor_in_form_query_or_header_is_ignored(db, agent, world):
    before = state_hash(db)
    r = agent.post(f"/approvals/{world['approval']['id']}/decide?actor=meera",
                   data={"decision": "approve", "actor": "meera", "decided_by": "meera"},
                   headers={"X-User": "meera", "X-Actor": "meera"})
    assert r.status_code == 403 and state_hash(db) == before


def test_meera_approves_through_the_ui_and_the_audit_says_meera_via_ui(db, meera, world):
    r = meera.post(f"/approvals/{world['approval']['id']}/decide", data={"decision": "approve", "reason": "ok"})
    assert r.status_code == 303
    assert db.execute("SELECT status FROM invoices WHERE id=?", (world["over"]["id"],)).fetchone()[0] == "approved"
    rows = db.execute("SELECT actor, channel FROM audit_log WHERE action IN ('invoice.approve', 'approval.decide')").fetchall()
    assert {(r["actor"], r["channel"]) for r in rows} == {("meera", "ui")}


def test_bad_decision_value_is_an_error_page(db, meera, world):
    r = meera.post(f"/approvals/{world['approval']['id']}/decide", data={"decision": "maybe"})
    assert r.status_code == 422 and "Decision must be one of: approve, reject" in " ".join(Page(r.text).alerts)


def test_void_button_only_for_the_creator_and_direct_post_by_others_is_403(db, agent, meera, world):
    assert "Void invoice" in Page(agent.get(f"/invoices/{world['ok']['id']}").text).buttons
    assert "Void invoice" not in Page(agent.get("/invoices/3").text).buttons  # entered by the human clerk
    assert agent.post("/invoices/3/void").status_code == 403
    assert db.execute("SELECT status FROM invoices WHERE id=3").fetchone()[0] == "approved"


def test_cancel_and_void_actions_work_and_are_ui_audited(db, agent, world):
    assert agent.post(f"/payments/{world['payment']['id']}/cancel").status_code == 303
    assert agent.post(f"/invoices/{world['ok']['id']}/void").status_code == 303
    assert agent.post(f"/it-tickets/{world['ticket']['id']}/cancel").status_code == 303
    assert agent.post(f"/employees/{world['employee']['id']}/cancel").status_code == 303
    channels = {r[0] for r in db.execute("SELECT channel FROM audit_log WHERE actor='ops-agent' AND action LIKE '%.void' "
                                         "OR action LIKE '%.cancel'")}
    assert channels == {"ui"}


# --- state-changing paths: POST only, PRG (N.44) --------------------------------------------------

ACTION_PATHS = ["/invoices/{o}/void", "/invoices/{o}/request-approval", "/approvals/{a}/decide",
                "/approvals/{a}/withdraw", "/payments/{p}/cancel", "/payments/{p}/request-approval",
                "/employees/{e}/cancel", "/it-tickets/{t}/cancel", "/logout"]


@pytest.mark.parametrize("template", ACTION_PATHS)
def test_get_on_an_action_path_is_405_and_writes_nothing(db, agent, world, template):
    path = template.format(o=world["over"]["id"], a=world["approval"]["id"], p=world["payment"]["id"],
                           e=world["employee"]["id"], t=world["ticket"]["id"])
    before, audit = state_hash(db), count(db, "audit_log")
    assert agent.get(path).status_code == 405
    assert state_hash(db) == before and count(db, "audit_log") == audit


def test_reloading_the_page_after_a_post_writes_nothing(db, agent):
    location = post_invoice(agent).headers["location"]
    audit = count(db, "audit_log")
    agent.get(location)
    agent.get(location)
    assert count(db, "audit_log") == audit


def test_logout_redirects_to_login_and_kills_the_session(agent):
    r = agent.post("/logout")
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert agent.get("/invoices").status_code == 303


# --- escaping (N.42) ------------------------------------------------------------------------------


def test_script_in_stored_text_is_rendered_escaped(db, agent):
    xss = "<script>alert(1)</script>"
    invoice = s.submit_invoice(db, "ops-agent", "api", invoice_in(invoice_no="<b>x</b>"))
    employee = s.create_employee(db, "ops-agent", "api", EmployeeIn(
        name=xss, email="xss@acme.example", role="r", department="d", manager_id=1, start_date="2026-10-12"))
    for path in ("/invoices", f"/invoices/{invoice['id']}", "/employees", f"/employees/{employee['id']}",
                 "/it-tickets/new", "/employees/new"):
        html = agent.get(path).text
        assert xss not in html and "<b>x</b>" not in html, path
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in agent.get("/employees").text


def test_script_in_a_failed_form_is_echoed_escaped(agent):
    r = post_invoice(agent, invoice_no='"><script>alert(1)</script>', amount="bad")
    assert "<script>alert(1)</script>" not in r.text and "&lt;script&gt;" in r.text


def test_bad_path_and_filter_values_are_error_pages_not_json_or_500(agent):
    for path, status in (("/invoices/abc", 422), ("/invoices/9999", 404), ("/invoices?status=nope", 422),
                         ("/invoices?vendor=abc", 422), ("/it-tickets?employee=x", 422)):
        r = agent.get(path)
        assert r.status_code == status and r.headers["content-type"].startswith("text/html"), path
