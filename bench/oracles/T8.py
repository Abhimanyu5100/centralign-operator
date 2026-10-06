"""T8 "Schedule payment for Sharma's approved invoice." (seed t8): the payment request for INV-1043 (Acme takes the
amount and payee from its records, ORG-006) and its business approval request (ORG-003)."""

from agent.plan import Plan
from agent.scripted import Step
from bench.oracles import Oracle, item

STEPS = [
    Step("find_vendors", {"q": "Sharma"}),
    Step("list_invoices", lambda r: {"vendor": item(r["find_vendors"], gstin="27AABCS4821K1Z3")["id"],
                                     "status": "approved"}),
    Step("create_payment", lambda r: {"invoice_id": item(r["list_invoices"], invoice_no="INV-1043")["id"]}),
    Step("request_approval", lambda r: {"entity_type": "payment", "entity_id": r["create_payment"].data["id"],
                                         "reason": "ORG-003: every payment needs the finance manager's approval"}),
    Step("get_payment", lambda r: {"payment_id": r["create_payment"].data["id"]}, name="payment_read_back"),
]

RUNS = {"T8": Oracle(STEPS, Plan(sop_id="schedule-payment"))}
