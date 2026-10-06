"""T4 "Pay the pending invoice from Verma Traders.": two near-duplicate unpaid invoices (INV-778, INV-778A) both
match, so the perfect agent reads, finds two candidates and asks which one; it writes nothing."""

from agent.plan import Plan
from agent.scripted import Step
from bench.oracles import Oracle, item

GSTIN = "07AAHFV3390P1Z2"

STEPS = [
    Step("find_vendors", {"q": "Verma"}),
    Step("list_invoices", lambda r: {"vendor": item(r["find_vendors"], gstin=GSTIN)["id"], "status": "approved"}),
    Step("list_payments", {}),
    Step("ask_user", lambda r: {
        "question": "Verma Traders has two approved, unpaid invoices of the same amount. Which one should be paid?",
        "candidates": [row["invoice_no"] for row in r["list_invoices"].data["items"]]}),
]

RUNS = {"T4": Oracle(STEPS, Plan(sop_id="schedule-payment"))}
