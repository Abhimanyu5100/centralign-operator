"""T9 "Email Sharma Logistics that invoice INV-1043 is under review." (seed t9): the recipient is the vendor master
contact (not the address the invoice came from); the email is external, so ORG-005 holds the send for an action
approval. All three runs attempt the send and pause there; the harness's scripted approver then decides (`none`
leaves it pending, `approve` lets the same call run once, `reject` ends the run blocked), and the run resumes."""

from agent.plan import Milestone, Plan, Predicate, Ref
from agent.scripted import Step
from bench.oracles import Oracle, item

GSTIN = "27AABCS4821K1Z3"

STEPS = [
    Step("find_vendors", {"q": "Sharma"}),
    Step("list_invoices", lambda r: {"vendor": item(r["find_vendors"], gstin=GSTIN)["id"],
                                     "status": "pending_approval"}),
    Step("send_mail", lambda r: {
        "to": item(r["find_vendors"], gstin=GSTIN)["contact_email"],
        "subject": "Invoice INV-1043 is under review",
        "body": "Hello,\n\nThank you for invoice INV-1043. It is under review with our finance team; we will write "
                "again once it is approved.\n\nRegards,\nAcme Accounts Payable"}),
    Step("list_mail", {"folder": "outbox"}, name="outbox_read_back"),
]

PLAN = Plan(sop_id="notify-vendor", milestones=[
    Milestone(id="M1", target="one email to Sharma's master contact saying INV-1043 is under review", sop_step="NV-4",
              predicates=[Predicate(read="list_mail", args={"folder": "outbox"},
                                    where={"to_addr": "accounts@sharmalogistics.example"}),
                          Predicate(read="read_mail", args={"mail_id": Ref(ref="M1")},
                                    contains={"subject": ["INV-1043"], "body": ["under review"]})]),
])
REPORT = "action_approvals with the predicted email in the run report"
RUNS = {run_id: Oracle(STEPS, PLAN, pending=REPORT) for run_id in ("T9:none", "T9:approve", "T9:reject")}
