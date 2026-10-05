"""ORG-002 for payments inside Acme (D-084, risk N.82a, N.99): no payment request for an invoice whose vendor is
not approved, and no approval of a payment whose vendor stopped being approved. Both channels, nothing written."""

import pytest

from acme import services as s
from acme.models import ApprovalIn, PaymentIn
from tests.acme.test_api import assert_typed_error, count
from tests.acme.test_services import submit
from tests.acme.test_ui import Page, token_of

VENDOR = 2  # Sharma Logistics (approved in the seed)


def block(db, status: str, vendor_id: int = VENDOR) -> None:
    s.set_status(db, "admin", "vendor", vendor_id, status)


@pytest.fixture
def invoice(db):
    """An approved invoice (under the limit) for an approved vendor."""
    row = submit(db, invoice_no="INV-ORG2")
    assert row["status"] == "approved"
    return row


@pytest.fixture
def pending_payment(db, invoice):
    """A payment request with its business approval request, made while the vendor was still approved."""
    payment = s.create_payment(db, "ops-agent", "api", PaymentIn(invoice_id=invoice["id"]))
    approval = s.request_approval(db, "ops-agent", "api", ApprovalIn(entity_type="payment", entity_id=payment["id"]))
    return payment, approval


def snapshot(db):
    return tuple(count(db, t) for t in ("payments", "approvals", "audit_log")) + (
        db.execute("SELECT group_concat(status) FROM payments").fetchone()[0],
        db.execute("SELECT group_concat(status) FROM approvals").fetchone()[0])


# --- creating a payment request ------------------------------------------------------------------


def test_an_approved_vendor_still_gets_its_payment_request(db, agent, invoice):
    r = agent.post("/api/payments", json={"invoice_id": invoice["id"]}, headers={"Idempotency-Key": "k"})
    assert r.status_code == 201


@pytest.mark.parametrize("status", ["blocked", "pending"])
def test_the_api_refuses_a_payment_request_for_a_vendor_that_is_not_approved(db, agent, invoice, status):
    block(db, status)
    before = snapshot(db)
    r = agent.post("/api/payments", json={"invoice_id": invoice["id"]}, headers={"Idempotency-Key": "k"})
    body = assert_typed_error(r, 409, "conflict")
    assert "ORG-002" in body["detail"] and status in body["detail"] and body["data"] == {"field": "invoice_id"}
    assert snapshot(db) == before


@pytest.mark.parametrize("status", ["blocked", "pending"])
def test_the_ui_refuses_it_too_with_an_inline_error(db, agent, invoice, status):
    block(db, status)
    before = snapshot(db)
    r = agent.post("/payments/new", data={"invoice_id": str(invoice["id"]), "idempotency_token": token_of(agent.get("/payments/new").text)})
    assert r.status_code == 409 and "ORG-002" in " ".join(Page(r.text).alerts)
    assert snapshot(db) == before


def test_a_refused_key_is_not_replayed_as_a_success_once_the_vendor_is_approved_again(db, agent, invoice):
    block(db, "blocked")
    assert agent.post("/api/payments", json={"invoice_id": invoice["id"]}, headers={"Idempotency-Key": "k"}).status_code == 409
    block(db, "approved")
    assert agent.post("/api/payments", json={"invoice_id": invoice["id"]}, headers={"Idempotency-Key": "k"}).status_code == 201


def test_the_service_layer_refuses_it_directly(db, invoice):
    block(db, "blocked")
    with pytest.raises(s.Conflict, match="ORG-002"):
        s.create_payment(db, "ops-agent", "api", PaymentIn(invoice_id=invoice["id"]))


# --- deciding the approval of a payment (N.99) ---------------------------------------------------


@pytest.mark.parametrize("status", ["blocked", "pending"])
def test_the_api_refuses_to_approve_a_payment_whose_vendor_is_no_longer_approved(db, meera, pending_payment, status):
    payment, approval = pending_payment
    block(db, status)
    before = snapshot(db)
    r = meera.post(f"/api/approvals/{approval['id']}/decide", json={"decision": "approve"})
    assert "ORG-002" in assert_typed_error(r, 409, "conflict")["detail"]
    assert snapshot(db) == before
    assert s.get(db, "payment", payment["id"])["status"] == "pending_approval"
    assert s.get(db, "approval", approval["id"])["status"] == "pending"


def test_the_ui_refuses_it_too(db, meera, pending_payment):
    payment, approval = pending_payment
    block(db, "blocked")
    before = snapshot(db)
    r = meera.post(f"/approvals/{approval['id']}/decide", data={"decision": "approve", "reason": "ok"})
    assert r.status_code == 409 and "ORG-002" in r.text
    assert snapshot(db) == before


def test_rejecting_such_a_payment_stays_possible_on_both_channels(db, meera, pending_payment, invoice):
    payment, approval = pending_payment
    block(db, "blocked")
    assert meera.post(f"/api/approvals/{approval['id']}/decide", json={"decision": "reject"}).status_code == 200
    assert s.get(db, "payment", payment["id"])["status"] == "rejected"
    # a second payment, rejected through the UI
    block(db, "approved")
    again = s.create_payment(db, "ops-agent", "api", PaymentIn(invoice_id=invoice["id"]))
    second = s.request_approval(db, "ops-agent", "api", ApprovalIn(entity_type="payment", entity_id=again["id"]))
    block(db, "pending")
    assert meera.post(f"/approvals/{second['id']}/decide", data={"decision": "reject"}).status_code == 303
    assert s.get(db, "payment", again["id"])["status"] == "rejected"


def test_an_approved_vendor_payment_is_approved_as_before(db, meera, pending_payment):
    payment, approval = pending_payment
    assert meera.post(f"/api/approvals/{approval['id']}/decide", json={"decision": "approve"}).status_code == 200
    assert s.get(db, "payment", payment["id"])["status"] == "scheduled"


def test_the_check_does_not_touch_invoice_approvals(db, meera, agent):
    """ORG-002's invoice half is a runtime gate rule; Acme still lets meera decide an invoice approval."""
    over = submit(db, invoice_no="INV-OVER", amount_paise=6_240_000)
    approval = s.request_approval(db, "ops-agent", "api", ApprovalIn(entity_type="invoice", entity_id=over["id"]))
    block(db, "blocked")
    assert meera.post(f"/api/approvals/{approval['id']}/decide", json={"decision": "approve"}).status_code == 200
