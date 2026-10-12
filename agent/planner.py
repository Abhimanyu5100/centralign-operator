"""Planner (author-owned; design approved 2026-10-09: docs/day4-plan.md C with the author's change 1).

One LLM call, no tools. In: the Goal Spec, the SOP, the gathered facts and the API read tools. Out: one
`agent/plan.Plan` (target states, SOP-cited, API-read predicates; the verifier's input, D-131). Code checks the
reply (the Plan model, then `plan_errors`); one retry with the problems listed; failing again gives no plan, so
the run never acts and the verifier says `unverified`.

Replan (docs/day5-plan.md C, approved): the same call and checks plus the plan and its unmet milestones; met ones
come back unchanged, unmet ones change only how rows are found (args, where), never what they assert (N.182)."""

import json
from pathlib import Path
from typing import Any

from agent.goal import Fact, GoalSpec, shown
from agent.memory.knowledge import Sop
from agent.plan import Plan, Ref, plan_problems
from agent.policy.loader import POLICIES_PATH, load_policies
from agent.tools.api import CATALOG_PATH
from agent.tools.registry import _explain

PROMPT_TEXT = """You write the plan a back-office run will be checked against. Reply with one JSON object only, in the
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
6. awaits_business_approval: true on a milestone whose record will wait for a business approval.
7. Every procedure step that writes (its Source names a POST) is the sop_step of a milestone. Only a step whose
   title says "when ..." may instead be a key of not_applicable, with the reason it does not apply here: decide
   from its Target and the facts (amounts are in paise: <LIMIT>) whether its condition
   holds; when it does not, list it in not_applicable or check its "otherwise" state.
8. judge: at most 3 short criteria that no exact predicate can check (tone; whether a text says something in
   words), on a milestone whose predicates find the record. Exact checks stay predicates."""
REPLAN = """

Revise the plan: an independent check found the milestones in `unmet` not met (what each read found is given).
Keep every met milestone exactly as it is. For an unmet milestone keep its target, step and what each predicate
asserts (read, expect, contains, count); correct only how the row is found (args, where), with sourced values. If
the plan was right and the work is missing, send it back unchanged."""


def company_rules(path: Path = POLICIES_PATH) -> list[dict[str, Any]]:
    """The rules Acme enforces itself, each with the constants its code checks (the approval limit), read from the
    policy file at run time (D-217); since D-220 only the limit reaches the planner, inside rule 7's text."""
    return [{"rule": r.message, **({"limits": limits} if (limits := {
        c.ref.rsplit(".", 1)[-1]: c.equals for c in r.acme_check if c.kind == "constant"}) else {})}
        for r in load_policies(path).rules if r.enforced_by == "acme"]


def plan_prompt(path: Path = POLICIES_PATH) -> str:
    """The planner prompt with Acme's approval limit written into rule 7 from the policy file (D-220): the pre-D-217
    wording, whose example the model followed, without the amount living in code."""
    paise = next(v for r in company_rules(path) for v in (r.get("limits") or {}).values())
    return PROMPT_TEXT.replace("<LIMIT>", f"Rs {paise // 100:,} is {paise:,} paise")


PROMPT = plan_prompt()


def read_tools(run, seen: dict[str, list[str]]) -> list[dict[str, Any]]:
    """The API reads with their args and row fields: those seen while gathering, else the entity's written fields."""
    tools = [(spec, run.client.catalog.get(spec.name)) for spec in run.registry.specs()]
    written: dict[str, set[str]] = {}
    for spec, ep in tools:
        if ep is not None and spec.side_effect != "read":  # row field names, as its verify read sees them
            fields = set(ep.verify.fields) if ep.verify and ep.verify.fields else set(spec.args_model.model_fields)
            written.setdefault(ep.entity, set()).update(fields - set(spec.transport_args))
    return [{"read": s.name, "about": s.description, "args": {
        k: v.get("enum") or v.get("type", "any") for k, v in s.args_model.model_json_schema().get("properties", {}).items()},
        "row_fields": seen.get(s.name) or sorted(written.get(ep.entity, set()) | {"id", "status"})}
        for s, ep in tools if ep is not None and s.side_effect == "read" and s.channel == "api"]


def plan_errors(plan: Plan, run, goal: GoalSpec, sop: Sop | None, facts: list[Fact],
                seen: dict[str, list[str]] | None = None) -> list[str]:
    problems = plan_problems(plan, run.registry) + ([] if plan.milestones else ["give 1 to 7 milestones"])
    sourced = {str(v).lower() for f in facts for v in (f.value, f.raw)} | {f.value.lower() for f in goal.fields}
    text = ((sop.text if sop else "") + CATALOG_PATH.read_text(encoding="utf-8")).lower()
    cited = {m.sop_step for m in plan.milestones}
    optional = sop.write_steps(optional=True) if sop else []
    problems += [f"write step {s} needs a milestone" + (" or a not_applicable reason" if s in optional else
                 ": the procedure does not make it optional") for s in (sop.write_steps() if sop else [])
                 if s not in cited and not (s in optional and plan.not_applicable.get(s, "").strip())]
    exists = {(p.read, json.dumps(p.where, default=str)) for m in plan.milestones for p in m.predicates if p.count}
    for m in plan.milestones:  # rule 1 in code: a state the run writes, or a "must not exist" check
        if sop and m.sop_step not in sop.write_steps() and any(p.count for p in m.predicates):
            problems.append(f"{m.id}: {m.sop_step} writes nothing; only a count 0 check may cite it (rule 1)")
        problems += [f"{m.id}: count 0 on {p.read} rows another milestone expects to exist" for p in m.predicates
                     if not p.count and (p.read, json.dumps(p.where, default=str)) in exists]
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
            enums = enum_args(spec)  # a row field that is also an enum arg of the read: only those values
            problems += [f"{m.id}: {k}={v!r} is not one of {enums[k]}" for k, v in [*p.where.items(), *p.expect.items()]
                         if k in enums and v not in enums[k]]
            problems += [f"{m.id}: {v!r} is not from the facts, the goal, the procedure or the tools"
                         for v in [*p.args.values(), *p.where.values(), *p.expect.values()]
                         if isinstance(v, (str, int)) and not isinstance(v, bool) and str(v).lower() not in sourced
                         and not (isinstance(v, str) and v.lower() in text)]
            problems += [f"{m.id}: contains {v!r} is in no fact, the goal, the request, the procedure or the tools"
                         for v in (v for vs in p.contains.values() for v in vs)  # a part of one, or holding one
                         if not any(v.lower() in s for s in [*sourced, text, goal.request.lower()])  # (D-217)
                         and not any(len(s) >= 4 and s in v.lower() for s in sourced)]
    return problems


def enum_args(spec) -> dict[str, list]:
    return {k: e for k, v in (spec.args_model.model_json_schema()["properties"] if spec else {}).items()
            for e in [v.get("enum") or next((a["enum"] for a in v.get("anyOf", []) if "enum" in a), None)] if e}


def tidy(data: dict[str, Any], sop: Sop | None, registry=None) -> list[str]:
    """What the model gets wrong every time, fixed in code and logged (D-200): an arg of "any" or null is no filter,
    `contains` takes a list, a ref in `expect` is a lookup (moved to `where`), a step id given as a milestone's `sop_id` is
its `sop_step`, and a milestone that expects rows
for a step that writes nothing (rule 1) is dropped. A `where` value for an enum arg of the read (a mail `folder`) is
also passed as that arg, or the read returns the default set and never sees the row (D-215)."""
    notes, keep = [], []
    for m in [m for m in data.get("milestones") or [] if isinstance(m, dict)]:
        preds = [p for p in m.get("predicates") or [] if isinstance(p, dict)]
        if sop and "sop_step" not in m and m.get("sop_id") in sop.steps:
            m["sop_step"] = m.pop("sop_id")
            notes.append(f"{m.get('id')}: sop_id {m['sop_step']} read as its sop_step")
        if sop and m.get("sop_step") in set(sop.steps) - set(sop.write_steps()) and any(p.get("count", 1) for p in preds):
            notes.append(f"dropped {m.get('id')}: {m.get('sop_step')} writes nothing")
            continue
        keep.append(m)
        m["target"] = str(m.get("target", ""))[:200]
        for p in preds:
            for part in ("args", "where"):  # "any" is no filter
                p[part] = {k: v for k, v in (p.get(part) or {}).items() if v not in ("any", "all", None)}
            p["expect"] = {k: int(v) if k.endswith("_paise") and str(v).isdigit() else v
                           for k, v in (p.get("expect") or {}).items()}
            p["contains"] = {k: v if isinstance(v, list) else [v] for k, v in (p.get("contains") or {}).items()}
            refs = {k: v for k, v in (p.get("expect") or {}).items() if isinstance(v, dict) and "ref" in v}
            p["where"] = {**(p.get("where") or {}), **refs}
            p["expect"] = {k: v for k, v in (p.get("expect") or {}).items() if k not in refs}
            spec = registry.get(p.get("read")) if registry else None
            for k, allowed in enum_args(spec).items():
                if k in p["where"] and k not in p["args"] and p["where"][k] in allowed:
                    p["args"][k] = p["where"][k]
                    notes.append(f"{m.get('id')}: {p.get('read')} where {k}={p['where'][k]!r} also passed as its arg")
    data["milestones"] = [{**m, "after": [a for a in m.get("after") or [] if a in {k.get("id") for k in keep}]}
                          for m in keep]
    return notes


def replan_errors(old: Plan, new: Plan, unmet: set[str]) -> list[str]:
    now, problems = {m.id: m for m in new.milestones}, []
    for m in old.milestones:
        n = now.get(m.id)
        if n is None or m.id not in unmet and n != m:
            problems.append(f"{m.id} {'was dropped' if n is None else 'is met'}: keep it exactly as it was")
        elif m.id in unmet and not (n.model_dump(exclude={"predicates"}) == m.model_dump(exclude={"predicates"})
                                    and len(n.predicates) == len(m.predicates) and all(
                a.model_dump(exclude={"args", "where"}) == b.model_dump(exclude={"args", "where"})
                for a, b in zip(m.predicates, n.predicates))):
            problems.append(f"{m.id}: correct only how its rows are found (args, where), never what it asserts")
    return problems


async def make_plan(run, llm, goal: GoalSpec, sop: Sop | None, facts: list[Fact], seen: dict[str, list[str]],
                    current: Plan | None = None, unmet: list = (), replan: int = 0) -> Plan | None:
    brief = {"goal": goal.model_dump(exclude={"decision", "question", "candidates", "reason", "lookups"}),
             "facts": shown(facts), "sop_id": goal.sop_id,
             "read_tools": read_tools(run, seen), "schema": Plan.model_json_schema()}
    if current is not None:
        brief |= {"current_plan": current.model_dump(exclude_defaults=True),
                  "unmet": {c.id: [x.detail for x in c.checks if not x.ok] for c in unmet}}
    messages = [{"role": "system", "content": PROMPT + (REPLAN if current else "")}, {"role": "user", "content": json.dumps(
        brief, ensure_ascii=False) + (f"\n\nProcedure:\n{sop.text}" if sop else "")}]
    for attempt in (1, 2, 3):  # two retries (D-207)
        reply = await llm.chat("reason", messages)  # Gemini: gpt-oss-120b planned reads and pre-states (D-193)
        content, tidied = reply.content or "", []
        try:
            data = json.loads(content[content.index("{"):content.rindex("}") + 1])
            tidied = tidy(data, sop, run.registry) if isinstance(data, dict) else []
            plan = Plan.model_validate({**data, "sop_id": goal.sop_id})  # the gate's SOP, whatever the reply says
            if current:  # met milestones are frozen (2.6): kept as they were, whatever the reply says (D-215)
                old, unmet_ids = {m.id: m for m in current.milestones}, {c.id for c in unmet}
                plan = plan.model_copy(update={"milestones": [
                    old[m.id] if m.id in old and m.id not in unmet_ids else m for m in plan.milestones]})
            problems = plan_errors(plan, run, goal, sop, facts, seen)
            problems += replan_errors(current, plan, {c.id for c in unmet}) if current else []
        except ValueError as exc:  # no JSON object, bad JSON, or the Plan model's own checks (a ValidationError)
            plan, problems = None, [str(exc)[:600]]
        run.ctx.store.append(run.run_id, "plan", run.ctx.now.isoformat(), {
            "attempt": attempt, "plan": plan.model_dump() if plan else None, "problems": problems, "tidied": tidied, **({
                "replan": replan, "reasons": [f"{c.id} not met: {c.target}" for c in unmet],
                "changed": [m.id for m in plan.milestones if m not in current.milestones] if plan else []}
                if current else {})})
        if not problems:
            return plan
        messages += [reply.message, {"role": "user", "content": "Fix these problems and send the whole plan again:\n- "
                                     + "\n- ".join(problems)}]
    return None
