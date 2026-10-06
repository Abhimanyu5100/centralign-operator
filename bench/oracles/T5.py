"""T5 "Pay the invoice from Kapoor Steel.": the vendor master has no such vendor, so the perfect agent declines
with that read as evidence and writes nothing."""

from agent.plan import Plan
from agent.scripted import Step
from bench.oracles import Oracle

STEPS = [
    Step("find_vendors", {"q": "Kapoor"}),
    Step("find_vendors", {}, name="all_vendors"),  # evidence: the whole master, no near match either
    Step("declare_infeasible", lambda r: {
        "reason": "There is no vendor called Kapoor Steel in the vendor master, so there is no invoice to pay.",
        "evidence": [f"find_vendors q=Kapoor: {len(r['find_vendors'].data['items'])} match(es)",
                     f"vendor master: {len(r['all_vendors'].data['items'])} vendors, none named Kapoor"]}),
]

RUNS = {"T5": Oracle(STEPS, Plan(sop_id="schedule-payment"),
                     pending="infeasible: the refusal and its evidence in the run report")}
