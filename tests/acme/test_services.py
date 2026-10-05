"""Business rules, undo paths, roles and audit (acme-spec "Business rules"; risks N.11, N.21, N.22)."""

import json

import pytest

from acme import services as s
from acme.models import ApprovalIn, DecisionIn, EmployeeIn, InvoiceIn, ItTicketIn, PaymentIn
from acme.permissions import ACTION_ROLES, USER_ROLES, allowed


def invoice_in(**overrides) -> InvoiceIn:
    fields = dict(vendor_id=2, invoice_no="INV-2210", po_number="PO-2026-0420", invoice_date="2026-10-01",
                  due_date="2026-10-31", amount_paise=1_850_000, tax_paise=282_203)
    return InvoiceIn(**{**fields, **overrides})


def submit(conn, **overrides) -> dict:
    return s.submit_invoice(conn, "ops-agent", "api", invoice_in(**overrides))


def audit(conn, entity_type, entity_id) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM audit_log WHERE entity_type = ? AND entity_id = ? ORDER BY id", (entity_type, entity_id))]


def over_limit_pending(conn) -> tuple[dict, dict]:
    invoice = submit(conn, invoice_no="INV-9001", amount_paise=6_240_000, tax_paise=951_864)
    approval = s.request_approval(conn, "ops-agent", "api", ApprovalIn(entity_type="invoice", entity_id=invoice["id"]))
    return invoice, approval


def approved_with_payment(conn) -> tuple[dict, dict]:
    invoice = submit(conn, invoice_no="INV-9002")
    payment = s.create_payment(conn, "ops-agent", "api", PaymentIn(invoice_id=invoice["id"]))
    return invoice, payment


# --- invoice submission (ORG-001, D-001, D-004) ---------------------------------------------------


@pytest.mark.parametrize("amount, expected", [(5_000_000, "approved"), (5_000_001, "pending_approval")])
def test_approval_limit_compares_the_total(conn, amount, expected):
    invoice = submit(conn, amount_paise=amount, tax_paise=0)
    assert invoice["status"] == expected


def test_auto_approval_is_audited_as_system_with_reason(conn):
    invoice = submit(conn)
    rows = audit(conn, "invoice", invoice["id"])
    assert [(r["actor"], r["action"], r["reason"]) for r in rows] == [
        ("ops-agent", "invoice.submit", None),
        ("system", "invoice.auto_approve", "ORG-001 below limit"),
    ]
    assert json.loads(rows[1]["before_json"])["status"] == "pending_approval"
    assert json.loads(rows[1]["after_json"])["status"] == "approved"
    assert invoice["version"] == 2 and invoice["channel"] == "api"


def test_duplicate_invoice_number_rejected_unless_void(conn):
    first = submit(conn)
    with pytest.raises(s.Conflict, match="Duplicate invoice number for this vendor"):
        submit(conn, invoice_no="inv-2210")  # case-insensitive
    submit(conn, vendor_id=4)  # same number, different vendor: fine
    s.void_invoice(conn, "ops-agent", "api", first["id"])
    assert submit(conn)["status"] == "approved"


@pytest.mark.parametrize("overrides, message", [
    (dict(tax_paise=2_000_000), "Tax cannot exceed the invoice total"),
    (dict(invoice_date="2026-10-08"), "Invoice date cannot be in the future"),
    (dict(invoice_date="2026-10-06", due_date="2026-10-05"), "Due date must be after invoice date"),
    (dict(invoice_date="2026-09-01", due_date="2026-10-06"), "Due date is in the past"),
    (dict(received_date="2026-10-08"), "Received date cannot be in the future"),
])
def test_invoice_validation(conn, overrides, message):
    with pytest.raises(s.Invalid, match=message):
        submit(conn, **overrides)


def test_unknown_vendor_is_not_found(conn):
    with pytest.raises(s.NotFound):
        submit(conn, vendor_id=99)


def test_received_date_defaults_to_acme_today(conn):
    assert submit(conn)["received_date"] == "2026-10-07"


# --- business approvals ---------------------------------------------------------------------------


def test_approval_only_for_pending_entity(conn):
    invoice = submit(conn)  # auto-approved
    with pytest.raises(s.Conflict, match="pending_approval"):
        s.request_approval(conn, "ops-agent", "api", ApprovalIn(entity_type="invoice", entity_id=invoice["id"]))


def test_approval_requests_have_no_natural_uniqueness(conn):
    """3.5: a blind retry duplicates the request; only read-before-retry protects against it."""
    invoice, _ = over_limit_pending(conn)
    s.request_approval(conn, "ops-agent", "api", ApprovalIn(entity_type="invoice", entity_id=invoice["id"]))
    assert conn.execute("SELECT COUNT(*) FROM approvals WHERE status = 'pending'").fetchone()[0] == 2


@pytest.mark.parametrize("decision, invoice_status", [("approve", "approved"), ("reject", "rejected")])
def test_meera_decides_invoice(conn, decision, invoice_status):
    invoice, approval = over_limit_pending(conn)
    decided = s.decide_approval(conn, "meera", "ui", approval["id"], DecisionIn(decision=decision))
    assert decided["status"] == invoice_status and decided["decided_by"] == "meera"
    assert decided["decided_at"] == "2026-10-07T10:30:02+05:30"
    assert s.get(conn, "invoice", invoice["id"])["status"] == invoice_status


def test_ops_agent_cannot_decide_any_approval(conn):
    _, approval = over_limit_pending(conn)
    with pytest.raises(s.Forbidden):
        s.decide_approval(conn, "ops-agent", "api", approval["id"], DecisionIn(decision="approve"))


def test_requester_cannot_decide_own_approval(conn):
    invoice = s.submit_invoice(conn, "admin", "api", invoice_in(amount_paise=6_000_000, tax_paise=0))
    approval = s.request_approval(conn, "admin", "api", ApprovalIn(entity_type="invoice", entity_id=invoice["id"]))
    with pytest.raises(s.Forbidden, match="you requested"):
        s.decide_approval(conn, "admin", "api", approval["id"], DecisionIn(decision="approve"))


def test_decided_approval_cannot_be_decided_again(conn):
    _, approval = over_limit_pending(conn)
    s.decide_approval(conn, "meera", "ui", approval["id"], DecisionIn(decision="approve"))
    with pytest.raises(s.Conflict, match="already approved"):
        s.decide_approval(conn, "meera", "ui", approval["id"], DecisionIn(decision="reject"))


def test_withdraw_approval_requester_only(conn):
    _, approval = over_limit_pending(conn)
    with pytest.raises(s.Forbidden):
        s.withdraw_approval(conn, "meera", "ui", approval["id"])
    assert s.withdraw_approval(conn, "ops-agent", "api", approval["id"])["status"] == "withdrawn"
    with pytest.raises(s.Conflict):
        s.withdraw_approval(conn, "ops-agent", "api", approval["id"])


# --- invoice void (D-005, D-034, N.11) -------------------------------------------------------------


def test_void_pending_invoice_withdraws_its_approval_in_one_write(conn):
    invoice, approval = over_limit_pending(conn)
    voided = s.void_invoice(conn, "ops-agent", "ui", invoice["id"])
    assert voided["status"] == "void"
    assert s.get(conn, "approval", approval["id"])["status"] == "withdrawn"
    stamps = {r["ts"] for r in conn.execute("SELECT ts FROM audit_log WHERE action IN ('invoice.void', 'approval.withdraw')")}
    assert len(stamps) == 1


def test_void_auto_approved_invoice_without_payment(conn):
    assert s.void_invoice(conn, "ops-agent", "api", submit(conn)["id"])["status"] == "void"


def test_void_blocked_by_active_payment_then_allowed_after_cancel(conn):
    invoice, payment = approved_with_payment(conn)
    with pytest.raises(s.Conflict, match="cancel it before voiding"):
        s.void_invoice(conn, "ops-agent", "api", invoice["id"])
    s.cancel_payment(conn, "ops-agent", "api", payment["id"])
    assert s.void_invoice(conn, "ops-agent", "api", invoice["id"])["status"] == "void"


def test_rejected_payment_does_not_block_void(conn):
    invoice, payment = approved_with_payment(conn)
    approval = s.request_approval(conn, "ops-agent", "api", ApprovalIn(entity_type="payment", entity_id=payment["id"]))
    s.decide_approval(conn, "meera", "ui", approval["id"], DecisionIn(decision="reject"))
    assert s.get(conn, "payment", payment["id"])["status"] == "rejected"
    assert s.void_invoice(conn, "ops-agent", "api", invoice["id"])["status"] == "void"


def test_only_creator_voids_and_never_a_paid_invoice(conn):
    with pytest.raises(s.Forbidden, match="Only the user who entered"):
        s.void_invoice(conn, "ops-agent", "api", 3)  # seeded, entered by arvind.pillai
    with pytest.raises(s.Conflict, match="status paid"):
        s.void_invoice(conn, "admin", "api", 1)


# --- payments (D-002, ORG-003, ORG-006) ----------------------------------------------------------


def test_payment_request_for_approved_invoice(conn):
    invoice, payment = approved_with_payment(conn)
    assert (payment["status"], payment["amount_paise"], payment["scheduled_date"]) == (
        "pending_approval", invoice["amount_paise"], invoice["due_date"])
    approval = s.request_approval(conn, "ops-agent", "api", ApprovalIn(entity_type="payment", entity_id=payment["id"]))
    s.decide_approval(conn, "meera", "ui", approval["id"], DecisionIn(decision="approve"))
    assert s.get(conn, "payment", payment["id"])["status"] == "scheduled"


def test_payment_needs_approved_invoice_and_only_one_active_request(conn):
    pending, _ = over_limit_pending(conn)
    with pytest.raises(s.Conflict, match="approved invoice"):
        s.create_payment(conn, "ops-agent", "api", PaymentIn(invoice_id=pending["id"]))
    invoice, _ = approved_with_payment(conn)
    with pytest.raises(s.Conflict, match="already exists"):
        s.create_payment(conn, "ops-agent", "api", PaymentIn(invoice_id=invoice["id"]))


def test_payment_model_has_no_payee_or_bank_fields():
    """ORG-006 by construction."""
    assert set(PaymentIn.model_fields) == {"invoice_id", "scheduled_date"}
    with pytest.raises(ValueError):
        PaymentIn(invoice_id=1, bank_account="123456789012")


def test_cancel_payment_withdraws_its_approval(conn):
    _, payment = approved_with_payment(conn)
    approval = s.request_approval(conn, "ops-agent", "api", ApprovalIn(entity_type="payment", entity_id=payment["id"]))
    assert s.cancel_payment(conn, "ops-agent", "api", payment["id"])["status"] == "cancelled"
    assert s.get(conn, "approval", approval["id"])["status"] == "withdrawn"
    with pytest.raises(s.Conflict):
        s.cancel_payment(conn, "ops-agent", "api", payment["id"])


# --- employees and IT tickets --------------------------------------------------------------------


def employee_in(**overrides) -> EmployeeIn:
    fields = dict(name="Priya Nair", email="priya.nair@acme.example", role="Software Engineer",
                  department="Engineering", manager_id=2, start_date="2026-10-12")
    return EmployeeIn(**{**fields, **overrides})


def test_onboard_and_cancel_employee_and_tickets(conn):
    employee = s.create_employee(conn, "ops-agent", "api", employee_in())
    assert employee["status"] == "onboarding"
    ticket = s.create_it_ticket(conn, "ops-agent", "api", ItTicketIn(type="laptop", employee_id=employee["id"]))
    assert s.cancel_it_ticket(conn, "ops-agent", "api", ticket["id"])["status"] == "cancelled"
    assert s.cancel_employee(conn, "ops-agent", "api", employee["id"])["status"] == "cancelled"
    with pytest.raises(s.Conflict):
        s.create_it_ticket(conn, "ops-agent", "api", ItTicketIn(type="accounts", employee_id=employee["id"]))
    with pytest.raises(s.Conflict):
        s.cancel_employee(conn, "ops-agent", "api", 5)  # active employees are not undoable


@pytest.mark.parametrize("overrides, error, message", [
    (dict(email="priya@gmail.com"), s.Invalid, "@acme.example"),
    (dict(manager_id=99), s.Invalid, "Manager must be an active employee"),
    (dict(start_date="2026-10-06"), s.Invalid, "Start date is in the past"),
    (dict(email="Neha.Kulkarni@acme.example"), s.Conflict, "already has this email"),
])
def test_employee_validation(conn, overrides, error, message):
    with pytest.raises(error, match=message):
        s.create_employee(conn, "ops-agent", "api", employee_in(**overrides))


# --- roles (N.22) and status shortcuts (business rule 3) ------------------------------------------

FORBIDDEN_FOR_OPS_AGENT = {"approval.decide", "vendor.update_bank", "status.set"}
MEERA_ALLOWED = {"approval.decide", "mail.send"}  # humans may send mail (part 5)


@pytest.mark.parametrize("action", sorted(ACTION_ROLES))
def test_permission_matrix(action):
    assert allowed("ops-agent", action) == (action not in FORBIDDEN_FOR_OPS_AGENT)
    assert allowed("admin", action)
    assert allowed("meera", action) == (action in MEERA_ALLOWED)
    assert not allowed("system", action)
    assert not allowed("unknown-user", action)


def test_unknown_action_fails_closed():
    with pytest.raises(KeyError):
        allowed("admin", "invoice.delete")


def test_users_are_exactly_the_spec_roles():
    assert USER_ROLES == {"ops-agent": "ops_agent", "meera": "finance_manager", "admin": "admin", "system": "system"}


def test_ops_agent_cannot_set_status_or_touch_bank_details(conn):
    _, payment = approved_with_payment(conn)
    with pytest.raises(s.Forbidden):
        s.set_status(conn, "ops-agent", "payment", payment["id"], "sent")
    with pytest.raises(s.Forbidden):
        s.update_vendor_bank(conn, "ops-agent", 4, "123456789012")
    assert s.get(conn, "payment", payment["id"])["status"] == "pending_approval"


def test_admin_set_status_validates_value(conn):
    assert s.set_status(conn, "admin", "payment", 1, "sent")["status"] == "sent"
    with pytest.raises(s.Invalid):
        s.set_status(conn, "admin", "payment", 1, "teleported")


def test_meera_cannot_enter_invoices(conn):
    with pytest.raises(s.Forbidden):
        s.submit_invoice(conn, "meera", "ui", invoice_in())


# --- audit ---------------------------------------------------------------------------------------


def test_bank_details_are_masked_in_audit(conn):
    s.update_vendor_bank(conn, "admin", 4, "123456789012")
    row = audit(conn, "vendor", 4)[0]
    assert "123456789012" not in row["after_json"]
    assert json.loads(row["after_json"])["bank_account_masked"].endswith("9012")


def test_every_write_bumps_version_and_records_channel(conn):
    invoice, approval = over_limit_pending(conn)
    voided = s.void_invoice(conn, "ops-agent", "ui", invoice["id"])
    assert voided["version"] == invoice["version"] + 1
    rows = audit(conn, "invoice", invoice["id"])
    assert [r["channel"] for r in rows] == ["api", "ui"]
    assert json.loads(rows[-1]["before_json"])["status"] == "pending_approval"


def test_audit_ids_are_monotonic(conn):
    submit(conn)
    over_limit_pending(conn)
    ids = [r["id"] for r in conn.execute("SELECT id FROM audit_log ORDER BY rowid")]
    assert ids == sorted(ids) and len(ids) == len(set(ids))
