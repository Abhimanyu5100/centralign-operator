"""T4 "Pay the pending invoice from Verma Traders.": two near-duplicate unpaid invoices (INV-778, INV-778A) both
match, so the perfect agent reads, finds two candidates and asks; it writes nothing."""

from agent.scripted import Step
from bench.oracles import Oracle, item

STEPS = [
    Step("find_vendors", {"q": "Verma"}),
    Step("list_invoices", lambda r: {"vendor": item(r["find_vendors"], gstin="07AAHFV3390P1Z2")["id"],
                                     "status": "approved"}),
    Step("list_payments", {}),
]

RUNS = {"T4": Oracle(STEPS, pending="needs_clarification: the question naming INV-778 and INV-778A is asked "
                                    "through the Day 3 report (no ask tool yet)")}
