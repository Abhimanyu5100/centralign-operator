"""The plan a run follows: the planner's output from Day 4, and the verifier's input (D-131, Day 3 plan A3).

In Phase A each oracle passes a hand-written plan in as data, in exactly this schema.

- `sop_id`: the SOP the run follows; with none (None) every write needs an action approval (ORG-009, D-081).
- `milestones`: 0 to 7 TARGET STATES (register 2.1), each checked by predicates. A predicate is one API read-tool
  call and what its rows must show; it is never SQL (the agent has no database access) and never the write's own
  response (D-134). Rows are found by business keys; a later predicate may use the id of the row an earlier
  milestone found, `{"ref": "M1"}`, so a plan never needs a database id the planner cannot know (N.156).
- A milestone with no readable effect says why in `unverifiable_reason` instead of having predicates.
"""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

MILESTONE_ID = r"^M[1-9]$"
Value = str | int | bool | None


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Ref(_Strict):
    """The id of the row found by the FIRST predicate of milestone `ref` (that predicate must find exactly one)."""
    ref: str = Field(pattern=MILESTONE_ID)


class Predicate(_Strict):
    read: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")      # an API read tool
    args: dict[str, Value | Ref] = Field(default_factory=dict)  # its arguments
    where: dict[str, Value | Ref] = Field(default_factory=dict)  # which rows to pick (data.items, or the one row)
    expect: dict[str, Value] = Field(default_factory=dict)      # exact values on every picked row
    contains: dict[str, list[str]] = Field(default_factory=dict)  # text a field must contain, ignoring case
    count: int = Field(default=1, ge=0)                         # exactly this many picked rows; 0 = must not exist

    def refs(self) -> list[str]:
        return [v.ref for v in [*self.args.values(), *self.where.values()] if isinstance(v, Ref)]


class Milestone(_Strict):
    id: str = Field(pattern=MILESTONE_ID)
    target: str = Field(min_length=1, max_length=200)   # the target state, in words
    sop_step: str | None = None                         # e.g. "PI-4"
    after: list[str] = Field(default_factory=list)      # milestones that must hold first (a small DAG)
    predicates: list[Predicate] = Field(default_factory=list)
    unverifiable_reason: str | None = None              # no read can show this effect; a human must confirm
    critical: bool = True                                # False: unmet gives completed_with_exceptions
    awaits_business_approval: bool = False               # met means the record now waits for a business approval

    @model_validator(mode="after")
    def _checkable(self) -> Self:
        if bool(self.predicates) == bool(self.unverifiable_reason):
            raise ValueError(f"{self.id}: give predicates, or an unverifiable_reason instead, not both or neither")
        return self


class Plan(_Strict):
    sop_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{1,40}$")
    milestones: list[Milestone] = Field(default_factory=list, max_length=7)

    @model_validator(mode="after")
    def _a_small_dag_with_backward_refs(self) -> Self:
        seen: dict[str, Milestone] = {}
        for milestone in self.milestones:
            if milestone.id in seen:
                raise ValueError(f"duplicate milestone id {milestone.id}")
            for before in milestone.after:  # only earlier milestones: the order is a topological order, no cycles
                if before not in seen:
                    raise ValueError(f"{milestone.id}: after {before!r} names no earlier milestone")
            for i, predicate in enumerate(milestone.predicates):
                for ref in predicate.refs():  # an earlier milestone, or this one from its second predicate on
                    target = seen.get(ref) or (milestone if ref == milestone.id and i > 0 else None)
                    if target is None:
                        raise ValueError(f"{milestone.id}: ref {ref!r} must name an earlier milestone's row")
                    if not target.predicates or target.predicates[0].count != 1:
                        raise ValueError(f"{milestone.id}: ref {ref!r} needs a first predicate that finds one row")
            seen[milestone.id] = milestone
        return self


def plan_problems(plan: Plan, registry) -> list[str]:
    """What the registry says about a plan: every predicate reads through a registered API read tool (D-134)."""
    problems = []
    for milestone in plan.milestones:
        for predicate in milestone.predicates:
            spec = registry.get(predicate.read)
            if spec is None or spec.side_effect != "read" or spec.channel != "api":
                problems.append(f"{milestone.id}: {predicate.read!r} is not an API read tool")
    return problems


def coverage_warnings(plan: Plan | None, catalog, entities: set[str]) -> list[str]:
    """Entities the run wrote through the browser that no milestone reads (D-156). A GUI submit returns a page, not a
    row, so only a milestone can show it was stored: without one, a silent drop there would go unnoticed."""
    read = {catalog.get(p.read).entity for m in (plan.milestones if plan else []) for p in m.predicates
            if catalog.get(p.read) is not None}
    return [f"a browser write of {entity} has no milestone reading it: a dropped write would go unnoticed"
            for entity in sorted(entities - read)]
