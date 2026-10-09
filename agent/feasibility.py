"""Understand + feasibility gate (register 1.1-1.10): one LLM call between deterministic steps, not an agent.
Code finds the candidate SOPs (trigger words; only these may be chosen, decision 5) and the names in the request,
and probes the vendor and employee masters through the registry. The model judges proceed / ask / decline. Code
drops an SOP outside the candidates and a field seen in neither the request nor a probe (1.2); a decline stands
only if some named party matched nothing in any master, else the run asks (1.6). Ask and decline end the run
through the registry, the decline's evidence being the probe lines written by code."""

import json
import re

from agent.goal import GoalSpec
from agent.memory.knowledge import Sop, match_sops

NAME = re.compile(r"\b[A-Z][a-z]+(?: [A-Z][a-z]+)*")
NOT_NAMES = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "Today", "Tomorrow"}
PROMPT = """You are the intake step of a company's back-office operator. Decide whether the request can be done,
must be clarified, or is impossible, using only the request, the candidate procedures and the lookups below.
- proceed: the procedure fits and every named party was found exactly once (or is new, e.g. a new hire).
- ask: a required value is missing, or a named party matches two or more records.
- decline: a named party the request depends on does not exist in the company's records.
Choose sop_id only from the candidates ("" if none fits). fields: the values you rely on (vendor name as found,
dates, numbers), each with source "request" or "probe". success: short checkable statements of the end state."""
TEXT, TEXTS = {"type": "string"}, {"type": "array", "items": {"type": "string"}}
FIELD = {"type": "object", "required": ["name", "value", "source"], "properties": dict.fromkeys(("name", "value", "source"), TEXT)}
SCHEMA = {"type": "object", "required": ["decision", "sop_id", "fields", "success", "question", "candidates", "reason"],
          "properties": {"decision": {"type": "string", "enum": ["proceed", "ask", "decline"]}, "sop_id": TEXT,
                         "question": TEXT, "reason": TEXT, "candidates": TEXTS, "success": TEXTS,
                         "fields": {"type": "array", "items": FIELD}}}


def names_in(request: str) -> list[str]:
    rest = request.split(" ", 1)[1] if " " in request else ""  # the first word is the verb ("Process", "Pay")
    return [n for n in dict.fromkeys(NAME.findall(rest)) if n not in NOT_NAMES]


async def probe(run, request: str) -> tuple[list[str], list[str]]:
    """Evidence lines, and the names no master knows. A multi-word name with no match is tried by its first word."""
    lines, unknown = [], []
    for name in names_in(request):
        found = 0
        for tool in ("find_vendors", "find_employees"):
            for q in dict.fromkeys([name, name.split()[0]]):
                result = await run.call(tool, {"q": q})
                items = result.data.get("items", []) if result.ok else []
                shown = ", ".join(f"{r.get('name')} (id {r.get('id')}, {r.get('status', '')})" for r in items[:5])
                lines.append(f"{tool} q={q!r}: {len(items)} match(es){': ' + shown if shown else ''}")
                found += len(items)
                if items:
                    break
        unknown += [] if found else [name]
    return lines, unknown


async def understand(run, llm, request: str, sops: dict[str, Sop]) -> GoalSpec:
    candidates = match_sops(request, sops)
    lookups, unknown = await probe(run, request)
    brief = {"request": request, "lookups": lookups,
             "candidate_procedures": [{"id": s, "title": sops[s].title} for s in candidates]}
    reply = await llm.chat("reason", [{"role": "system", "content": PROMPT},
                                      {"role": "user", "content": json.dumps(brief, ensure_ascii=False)}], schema=SCHEMA)
    goal = GoalSpec.model_validate({**json.loads(reply.content or "{}"), "request": request})
    seen = (request + " " + " ".join(lookups)).lower()
    goal.sop_id = goal.sop_id if goal.sop_id in candidates else None
    goal.fields = [f for f in goal.fields if f.value.lower() in seen]
    if goal.decision == "decline" and not unknown:
        goal.decision, goal.question = "ask", goal.question or goal.reason
    if goal.decision == "decline":
        await run.call("declare_infeasible", {"reason": goal.reason[:500] or "the request cannot be done",
                                              "evidence": lookups[:10]})
    elif goal.decision == "ask":
        await run.call("ask_user", {"question": (goal.question or "Please clarify the request.")[:500],
                                    "candidates": goal.candidates[:10]})
    return goal
