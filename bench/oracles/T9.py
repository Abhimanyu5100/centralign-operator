"""T9 "Email Sharma Logistics that invoice INV-1043 is under review." (seed t9): the recipient is the vendor master
contact (not the address the invoice came from); the email is external, so ORG-005 needs an action approval.

Day 2 honesty: the gate passes everything, so no pause can happen yet. `none` and `reject` stop before the send
(their DB end state is what the gate will produce); `approve` sends without an approval. All three keep the
action-approval part pending until the Day 3 gate and approval inbox exist."""

from agent.scripted import Step
from bench.oracles import Oracle, item

GSTIN = "27AABCS4821K1Z3"

READS = [
    Step("find_vendors", {"q": "Sharma"}),
    Step("list_invoices", lambda r: {"vendor": item(r["find_vendors"], gstin=GSTIN)["id"],
                                     "status": "pending_approval"}),
]
SEND = Step("send_mail", lambda r: {
    "to": item(r["find_vendors"], gstin=GSTIN)["contact_email"],
    "subject": "Invoice INV-1043 is under review",
    "body": "Hello,\n\nThank you for invoice INV-1043. It is under review with our finance team; we will write "
            "again once it is approved.\n\nRegards,\nAcme Accounts Payable"})

PAUSE = "the ORG-005 pause before send_mail and the predicted email in action_approvals: Day 3 gate and report"
RUNS = {
    "T9:none": Oracle(READS, pending=PAUSE),
    "T9:approve": Oracle(READS + [SEND], pending=PAUSE + "; this run sent without an action approval (Day 2 gate)"),
    "T9:reject": Oracle(READS, pending=PAUSE + "; the rejection itself is a Day 3 approval-inbox action"),
}
