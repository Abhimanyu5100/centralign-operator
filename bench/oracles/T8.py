"""T8 "Schedule payment for Sharma's approved invoice." (seed t8): the payment request for INV-1043 (Acme takes the
amount and payee from its records, ORG-006) and its business approval request (ORG-003)."""

from agent.plan import Milestone, Plan, Predicate, Ref
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

PLAN = Plan(sop_id="schedule-payment", milestones=[
    Milestone(id="M1", target="INV-1043 from Sharma is approved and payable", sop_step="SP-2", predicates=[
        Predicate(read="list_invoices", args={"status": "approved"},
                  where={"invoice_no": "INV-1043", "vendor_name": "Sharma Logistics Pvt Ltd"})]),
    Milestone(id="M2", target="one payment request for its full total, waiting for approval", sop_step="SP-3",
              after=["M1"], predicates=[Predicate(read="list_payments", args={"invoice": Ref(ref="M1")},
                                                   where={"status": "pending_approval"},
                                                   expect={"amount_paise": 6_240_000})]),
    Milestone(id="M3", target="one pending business approval request for that payment", sop_step="SP-4", after=["M2"],
              awaits_business_approval=True, predicates=[
                  Predicate(read="list_approvals", args={"status": "pending"},
                            where={"entity_type": "payment", "entity_id": Ref(ref="M2")},
                            expect={"approver_role": "finance_manager"})]),
])
RUNS = {"T8": Oracle(STEPS, PLAN)}
