"""Verifier layers 1 and 2: independent reads of what the run wrote (D-134), polled through the read lag (N.141).

Layer 1, postconditions: for every successful API write, the catalog's `verify` read of the row it wrote (its id
from the write's result, its fields compared with the write's arguments, an undo's target status).
Layer 2, milestone predicates: the plan's target states, each a read-tool call plus the rows it must show.

Every read goes through `registry.call`, so it is gated, logged and becomes evidence. A check that does not hold
is read again every POLL_SECONDS until the read lag has passed; a `count: 0` check (must not exist) is read only
once that window is over, because read lag fakes exactly that (absence).
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field

from agent.plan import Milestone, Plan, Predicate, Ref

POLL_SECONDS = 0.25


class Check(BaseModel):
    name: str
    ok: bool
    detail: str = ""
    reads: int = 1          # how many times it was read before the answer


class MilestoneCheck(BaseModel):
    id: str
    target: str
    ok: bool
    critical: bool
    awaits_business_approval: bool
    unverifiable: bool = False
    checks: list[Check] = []
    rows: list[tuple[str, dict[str, Any]]] = Field(default=[], exclude=True)  # (read, row) its reads picked: for the judge


def _rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = data.get("items")
    return [r for r in items if isinstance(r, dict)] if isinstance(items, list) else [data]


async def until_held(check: Callable[[], Awaitable[Check]], window: float) -> Check:
    """Run `check` until it holds or `window` seconds have passed; the last answer, with how many reads it took."""
    loop = asyncio.get_running_loop()
    deadline, reads = loop.time() + window, 0
    while True:
        result = await check()
        reads += 1
        if result.ok or loop.time() >= deadline:
            return result.model_copy(update={"reads": reads})
        await asyncio.sleep(POLL_SECONDS)


# --- layer 1: postconditions of each write -------------------------------------------------------------------------

async def postconditions(run, writes: list[tuple[dict[str, Any], dict[str, Any]]]) -> list[Check]:
    """`writes`: (tool_call payload, tool_result payload) of every successful write, in order."""
    checks = []
    for call, result in writes:
        ep = run.client.catalog.get(call["tool"])
        if ep is None or ep.verify is None:  # a GUI submit returns a page, not a row: layer 2 covers it
            continue
        spec, data, given = ep.verify, result.get("data") or {}, call.get("args") or {}
        name = f"{call['tool']} -> {spec.tool}"
        if any(field not in data for field in spec.args.values()):
            checks.append(Check(name=name, ok=False, detail="the write's result names no row to read back"))
            continue
        args = {arg: data[field] for arg, field in spec.args.items()}

        async def check(spec=spec, args=args, given=given, name=name) -> Check:
            read = await run.call(spec.tool, args)
            if not read.ok:
                return Check(name=name, ok=False, detail=f"{spec.tool} failed: {read.error_type}: {read.detail[:120]}")
            row = read.data
            wrong = [f"{f}={row.get(f)!r}, wrote {given[a]!r}" for f, a in spec.fields.items()
                     if given.get(a) is not None and row.get(f) != given[a]]
            wrong += [f"{f}={row.get(f)!r}, expected {v!r}" for f, v in spec.expect.items() if row.get(f) != v]
            return Check(name=name, ok=not wrong, detail="; ".join(wrong))
        checks.append(await until_held(check, run.client.read_lag))
    return checks


# --- layer 2: milestone predicates ---------------------------------------------------------------------------------

def _resolve(values: dict[str, Any], found: dict[str, int]) -> dict[str, Any]:
    return {k: found[v.ref] if isinstance(v, Ref) else v for k, v in values.items()}  # KeyError: ref found no row


def _problems(row: dict[str, Any], predicate: Predicate) -> list[str]:
    wrong = [f"{f}={row.get(f)!r}, expected {v!r}" for f, v in predicate.expect.items() if row.get(f) != v]
    for f, parts in predicate.contains.items():
        text = str(row.get(f) or "").lower()
        wrong += [f"{f} lacks {p!r}" for p in parts if p.lower() not in text]
    return wrong


async def _predicate(run, predicate: Predicate, found: dict[str, int], absence_at: float) -> tuple[Check, list]:
    name = f"{predicate.read}({', '.join(f'{k}={v}' for k, v in predicate.args.items())})"
    try:
        args, where = _resolve(predicate.args, found), _resolve(predicate.where, found)
    except KeyError as missing:
        return Check(name=name, ok=False, detail=f"{missing} found no row to refer to"), []
    picked_rows: list[dict[str, Any]] = []

    async def check() -> Check:
        read = await run.call(predicate.read, args)
        if not read.ok:
            return Check(name=name, ok=False, detail=f"{predicate.read} failed: {read.error_type}: {read.detail[:120]}")
        picked = [row for row in _rows(read.data) if all(row.get(k) == v for k, v in where.items())]
        wrong = [] if len(picked) == predicate.count else [f"{len(picked)} matching row(s), expected {predicate.count}"]
        wrong += [p for row in picked for p in _problems(row, predicate)]
        picked_rows[:] = picked
        return Check(name=name, ok=not wrong, detail="; ".join(wrong)[:300])

    if predicate.count == 0:  # absence: only believed once the read-lag window is over
        loop = asyncio.get_running_loop()
        await asyncio.sleep(max(0.0, absence_at - loop.time()))
        result = await check()
    else:
        result = await until_held(check, run.client.read_lag)
    return result, picked_rows if result.ok else []


async def milestones(run, plan: Plan, absence_at: float) -> list[MilestoneCheck]:
    found: dict[str, int] = {}   # milestone id -> the id of the row its first predicate found (for refs)
    results: dict[str, MilestoneCheck] = {}
    for m in plan.milestones:
        results[m.id] = await _milestone(run, m, found, results, absence_at)
    return list(results.values())


async def _milestone(run, m: Milestone, found: dict[str, int], earlier: dict[str, MilestoneCheck],
                     absence_at: float) -> MilestoneCheck:
    head = dict(id=m.id, target=m.target, critical=m.critical, awaits_business_approval=m.awaits_business_approval)
    if m.unverifiable_reason:
        return MilestoneCheck(**head, ok=False, unverifiable=True,
                              checks=[Check(name="unverifiable", ok=False, detail=m.unverifiable_reason)])
    unmet = [b for b in m.after if not earlier[b].ok]
    if unmet:
        return MilestoneCheck(**head, ok=False, checks=[Check(name="after", ok=False,
                                                                 detail=f"needs {', '.join(unmet)} first")])
    checks, rows = [], []
    for i, predicate in enumerate(m.predicates):
        check, picked = await _predicate(run, predicate, found, absence_at)
        if i == 0 and predicate.count == 1 and picked:
            found[m.id] = picked[0].get("id")
        checks.append(check)
        rows += [(predicate.read, row) for row in picked]
    return MilestoneCheck(**head, ok=all(c.ok for c in checks), checks=checks, rows=rows)
