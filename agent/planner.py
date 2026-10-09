"""Planner (author-owned; design approved 2026-10-09: docs/day4-plan.md C with the author's change 1).

One LLM call, no tools. In: the Goal Spec, the SOP, the gathered facts and the API read tools. Out: one
`agent/plan.Plan` (target states, SOP-cited, API-read predicates; the verifier's input, D-131). Code checks the
reply (the Plan model, then `plan_errors`); one retry with the problems listed; failing again gives no plan, so
the run never acts and the verifier says `unverified`."""

import json
from typing import Any

from agent.goal import Fact, GoalSpec
from agent.memory.knowledge import Sop
from agent.plan import Plan, Ref, plan_problems
from agent.tools.api import CATALOG_PATH
from agent.tools.registry import _explain

PROMPT = """You write the plan a back-office run will be checked against. Reply with one JSON object only, in the
schema given. Rules:
1. 1 to 7 milestones (aim for 3 to 7). Each is a TARGET STATE of a record the run creates or changes, or must leave
   unchanged, in words; never a click, a tool call, or finding or reading something. Each names its sop_step;
   every record the run will write is read by some milestone. Use only the args and row_fields of the tool list.
2. Each milestone is checked by predicates: one API read tool call (read, args) whose rows are picked by `where`
   and must show `expect` (exact values) or `contains`; `count` is how many rows match (0 = must not exist).
3. Find rows by business keys (numbers, names, statuses), never a database id: {"ref": "M1"} is the id of the row
   that milestone M1's first predicate found (that predicate must find exactly one row).
4. Every value comes from the facts, the goal, the procedure or the tool list. Never invent one.
5. The procedure's "leave everything else unchanged" step becomes a count 0 predicate.
6. awaits_business_approval: true on a milestone whose record will wait for a business approval."""


def read_tools(run, seen: dict[str, list[str]]) -> list[dict[str, Any]]:
    """The API reads with their args and row fields: those seen while gathering, else the entity's written fields."""
    tools = [(spec, run.client.catalog.get(spec.name)) for spec in run.registry.specs()]
    written: dict[str, set[str]] = {}
    for spec, ep in tools:
        if ep is not None and spec.side_effect != "read":
            written.setdefault(ep.entity, set()).update(set(spec.args_model.model_fields) - set(spec.transport_args))
    return [{"read": s.name, "about": s.description, "args": {
        k: v.get("enum") or v.get("type", "any") for k, v in s.args_model.model_json_schema().get("properties", {}).items()},
        "row_fields": seen.get(s.name) or sorted(written.get(ep.entity, set()) | {"id", "status"})}
        for s, ep in tools if ep is not None and s.side_effect == "read" and s.channel == "api"]


def plan_errors(plan: Plan, run, goal: GoalSpec, sop: Sop | None, facts: list[Fact],
                seen: dict[str, list[str]] | None = None) -> list[str]:
    problems = plan_problems(plan, run.registry) + ([] if plan.milestones else ["give 1 to 7 milestones"])
    sourced = {str(v).lower() for f in facts for v in (f.value, f.raw)} | {f.value.lower() for f in goal.fields}
    text = ((sop.text if sop else "") + CATALOG_PATH.read_text(encoding="utf-8")).lower()
    for m in plan.milestones:
        if sop and m.sop_step not in sop.steps:
            problems.append(f"{m.id}: sop_step {m.sop_step!r} is not a step of {sop.id}")
        for p in m.predicates:
            spec, known = run.registry.get(p.read), (seen or {}).get(p.read, [])  # only fields actually seen
            try:  # the args as the registry would validate them, a ref standing in as an id
                spec and spec.args_model.model_validate_json(json.dumps(
                    {k: 1 if isinstance(v, Ref) else v for k, v in p.args.items()}), strict=True)
            except ValueError as exc:
                problems.append(f"{m.id}: {p.read} args: {_explain(exc)}")
            problems += [f"{m.id}: {p.read} rows have no field {k!r}; they have {', '.join(known)}"
                         for k in [*p.where, *p.expect, *p.contains] if known and k not in known]
            problems += [f"{m.id}: {v!r} is not from the facts, the goal, the procedure or the tools"
                         for v in [*p.args.values(), *p.where.values(), *p.expect.values()]
                         if isinstance(v, (str, int)) and not isinstance(v, bool) and str(v).lower() not in sourced
                         and not (isinstance(v, str) and v.lower() in text)]
    return problems


async def make_plan(run, llm, goal: GoalSpec, sop: Sop | None, facts: list[Fact],
                    seen: dict[str, list[str]]) -> Plan | None:
    brief = {"goal": goal.model_dump(exclude={"decision", "question", "candidates", "reason"}),
             "facts": {f.name: f.value for f in facts}, "sop_id": goal.sop_id,
             "read_tools": read_tools(run, seen), "schema": Plan.model_json_schema()}
    messages = [{"role": "system", "content": PROMPT}, {"role": "user", "content": json.dumps(
        brief, ensure_ascii=False) + (f"\n\nProcedure:\n{sop.text}" if sop else "")}]
    for attempt in (1, 2):
        reply = await llm.chat("reason", messages)
        content = reply.content or ""
        try:
            plan = Plan.model_validate({**json.loads(content[content.index("{"):content.rindex("}") + 1]),
                                        "sop_id": goal.sop_id})  # the gate's SOP, whatever the reply says
            problems = plan_errors(plan, run, goal, sop, facts, seen)
        except ValueError as exc:  # no JSON object, bad JSON, or the Plan model's own checks (a ValidationError)
            plan, problems = None, [str(exc)[:600]]
        run.ctx.store.append(run.run_id, "plan", run.ctx.now.isoformat(), {
            "attempt": attempt, "plan": plan.model_dump() if plan else None, "problems": problems})
        if not problems:
            return plan
        messages += [reply.message, {"role": "user", "content": "Fix these problems and send the whole plan again:\n- "
                                     + "\n- ".join(problems)}]
    return None
