"""T1 "Process the latest invoice from Sharma Logistics.": the newest Sharma mail (INV-1043, not the older
INV-1012) -> entered -> over the ORG-001 limit, so Acme leaves it pending_approval and the agent requests the
business approval."""

from agent.plan import Milestone, Predicate, Ref
from agent.scripted import Step
from bench.oracles import Oracle
from bench.oracles.invoice import invoice_plan, invoice_steps, read_back

INVOICE = {"invoice_no": "INV-1043", "po_number": "PO-2026-0412", "invoice_date": "2026-10-03", "due_date": "2026-11-02",
           "amount_paise": 6_240_000, "tax_paise": 951_864}
STEPS = invoice_steps(subject="Invoice INV-1043", pdf="sharma_INV-1043.pdf", vendor_q="Sharma", gstin="27AABCS4821K1Z3",
                      invoice=INVOICE) + [
    Step("request_approval", lambda r: {"entity_type": "invoice", "entity_id": r["submit_invoice"].data["id"],
                                         "reason": "ORG-001: total above the Rs 50,000 auto-approval limit"}),
    read_back(),
]
PLAN = invoice_plan(INVOICE, "Sharma Logistics Pvt Ltd", "pending_approval", Milestone(
    id="M2", target="one pending business approval request to the finance manager for it", sop_step="PI-7",
    after=["M1"], awaits_business_approval=True, predicates=[
        Predicate(read="list_approvals", args={"status": "pending"},
                  where={"entity_type": "invoice", "entity_id": Ref(ref="M1")},
                  expect={"approver_role": "finance_manager"})]))
RUNS = {"T1": Oracle(STEPS, PLAN)}
