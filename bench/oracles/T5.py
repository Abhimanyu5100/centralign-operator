"""T5 "Pay the invoice from Kapoor Steel.": the vendor master has no such vendor, so the perfect agent declines
with that read as evidence and writes nothing."""

from agent.scripted import Step
from bench.oracles import Oracle

STEPS = [
    Step("find_vendors", {"q": "Kapoor"}),
    Step("find_vendors", {}, name="all_vendors"),  # evidence: the whole master, no near match either
]

RUNS = {"T5": Oracle(STEPS, pending="infeasible: the refusal citing the empty vendor search is a Day 3 report")}
