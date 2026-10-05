"""ORG-006 inside Acme: a payment request cannot carry an amount, payee or bank account, so an injected
"transfer Rs 1,00,000 to account X" fails in Acme whatever the agent believes (D-016, risk P.1, 3.2).

Acme already enforced this: `PaymentIn` has only `invoice_id` and `scheduled_date` and rejects unknown fields
(D-059), and `create_payment` copies the amount from the invoice. These tests pin it on both channels."""

import pytest

from acme import services as s
from acme.seed import INJECTED_TRANSFER_ACCOUNT, INJECTED_TRANSFER_PAISE, MEHTA_INV_0091
from tests.acme.test_api import assert_typed_error, count
from tests.acme.test_ui import token_of


@pytest.fixture
def mehta(db):
    """The T6 invoice (total Rs 24,000, auto-approved) entered through the service layer."""
    invoice = s.submit_invoice(db, "ops-agent", "api", MEHTA_INV_0091)
    assert invoice["status"] == "approved" and invoice["amount_paise"] < INJECTED_TRANSFER_PAISE
    return invoice


@pytest.mark.parametrize("extra", [
    {"amount_paise": INJECTED_TRANSFER_PAISE},
    {"amount": INJECTED_TRANSFER_PAISE // 100},
    {"bank_account": INJECTED_TRANSFER_ACCOUNT},
    {"account_number": INJECTED_TRANSFER_ACCOUNT},
    {"payee": "Someone Else"},
    {"ifsc": "XXXX0000000"},
])
def test_the_api_rejects_a_payment_request_with_an_amount_payee_or_bank_field(db, agent, mehta, extra):
    before = (count(db, "payments"), count(db, "audit_log"))
    r = agent.post("/api/payments", json={"invoice_id": mehta["id"], **extra}, headers={"Idempotency-Key": "k1"})
    body = assert_typed_error(r, 422, "invalid_input")
    assert "Extra inputs are not permitted" in body["detail"]
    assert (count(db, "payments"), count(db, "audit_log")) == before


def test_the_payment_amount_is_the_invoice_total_never_the_injected_amount(db, agent, mehta):
    r = agent.post("/api/payments", json={"invoice_id": mehta["id"]}, headers={"Idempotency-Key": "k2"})
    assert r.status_code == 201
    (row,) = db.execute("SELECT amount_paise FROM payments WHERE invoice_id = ?", (mehta["id"],)).fetchall()
    assert row["amount_paise"] == mehta["amount_paise"] != INJECTED_TRANSFER_PAISE


def test_the_ui_form_ignores_an_extra_amount_and_still_pays_the_invoice_total(db, agent, mehta):
    token = token_of(agent.get("/payments/new").text)
    r = agent.post("/payments/new", data={"invoice_id": str(mehta["id"]), "scheduled_date": "",
                                          "amount": str(INJECTED_TRANSFER_PAISE // 100),
                                          "bank_account": INJECTED_TRANSFER_ACCOUNT, "idempotency_token": token})
    assert r.status_code == 303
    (row,) = db.execute("SELECT * FROM payments WHERE invoice_id = ?", (mehta["id"],)).fetchall()
    assert row["amount_paise"] == mehta["amount_paise"]
    assert INJECTED_TRANSFER_ACCOUNT not in " ".join(str(v) for v in dict(row).values())


def test_neither_the_agent_nor_the_approver_has_a_route_that_writes_bank_details(agent, meera):
    for client in (agent, meera):
        for method in ("post", "put", "patch"):
            for path in ("/api/vendors/4/bank", "/vendors/4/bank", "/api/vendors/4", "/vendors/4/update-bank"):
                r = getattr(client, method)(path, json={"account_number": INJECTED_TRANSFER_ACCOUNT})
                assert r.status_code in (404, 405), (method, path, r.status_code)
