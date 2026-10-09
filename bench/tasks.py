"""AcmeBench task files (`bench/tasks/*.yaml`): schema and loader (D-096, D-097).

A task file holds data only; `bench/checkers/engine.py` is the one piece of code that judges an end state
against it. A task with `variants` (T9) is several runs, one per scripted approver decision, each with its
own run id (`T9:none`, `T9:approve`, `T9:reject`); a variant replaces the task's outcome, success predicates,
allowed changes and report checks.

Loading is strict (risk N.114): unknown keys, a status outside the canonical list in CLAUDE.md, an unknown
seed or chaos profile, or a `now` without `+05:30` are errors.
"""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from acme import chaos, clock, seed
from acme.db import ENTITY_TABLES
from acme.services import Invalid

TASK_DIR = Path(__file__).parent / "tasks"

# The canonical run statuses (CLAUDE.md, "Approvals and run statuses"); a test keeps the two equal.
Status = Literal["completed", "completed_with_exceptions", "awaiting_business_approval",
                 "paused_for_action_approval", "needs_clarification", "infeasible", "blocked_by_policy",
                 "failed", "rolled_back", "unverified", "unverifiable"]
Approver = Literal["none", "approve", "reject"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Predicate(_Strict):
    """SQL that must return exactly one row with one column equal to 1 (risk N.111)."""
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    sql: str = Field(min_length=10)


class TableChange(_Strict):
    added: int = Field(0, ge=0)              # at most this many new rows (voided ones count too)
    changed: list[str] = Field(default_factory=list)  # columns existing rows may change (`version` comes along)


class ReportCheck(_Strict):
    """One check over the run report (provisional contract, D-098). Exactly one operator."""
    path: str = Field(pattern=r"^[a-z_]+(\[\*\])?(\.[a-z_]+(\[\*\])?)*$")
    equals: str | None = None
    contains_all: list[str] | None = None   # every value appears among the values at `path`
    text_contains: list[str] | None = None  # every phrase appears (case-insensitive) in the text at `path`
    non_empty: bool | None = None

    @model_validator(mode="after")
    def _one_operator(self) -> "ReportCheck":
        given = [op for op in ("equals", "contains_all", "text_contains", "non_empty") if getattr(self, op) is not None]
        if len(given) != 1:
            raise ValueError(f"a report check needs exactly one operator, got {given or 'none'}")
        if self.non_empty is False:
            raise ValueError("non_empty must be true")
        return self


class ChaosVariant(_Strict):
    profile: str
    seed: int = Field(0, ge=0)
    channel: Literal["any", "gui"] = "any"   # gui: run only with a GUI oracle (a UI-only profile, D-161)

    @field_validator("profile")
    @classmethod
    def _known(cls, value: str) -> str:
        try:
            chaos.validate(value)
        except Invalid as exc:
            raise ValueError(exc.message) from exc
        return value

    @model_validator(mode="after")
    def _ui_only_needs_the_gui(self) -> "ChaosVariant":
        if self.profile in chaos.UI_ONLY and self.channel != "gui":
            raise ValueError(f"{self.profile} acts only on pages: mark the variant channel: gui (D-161)")
        return self


AllowedChanges = dict[str, TableChange]


def _check_tables(changes: AllowedChanges) -> AllowedChanges:
    unknown = set(changes) - set(ENTITY_TABLES)
    if unknown:
        raise ValueError(f"allowed_changes names tables that are not entity tables: {sorted(unknown)}")
    if "audit_log" in changes:
        raise ValueError("audit_log additions are always allowed; do not list it")
    return changes


class Variant(_Strict):
    expected_outcome: Status
    success: list[Predicate] = Field(min_length=1)
    allowed_changes: AllowedChanges = Field(default_factory=dict)
    report_checks: list[ReportCheck] = Field(default_factory=list)

    @field_validator("allowed_changes")
    @classmethod
    def _tables(cls, value: AllowedChanges) -> AllowedChanges:
        return _check_tables(value)


class Task(_Strict):
    id: str = Field(pattern=r"^T[0-9]+$")
    request: str = Field(min_length=5)
    category: str
    seed: str
    now: str
    success: list[Predicate] = Field(default_factory=list)
    checkpoints: list[Predicate] = Field(default_factory=list)
    allowed_changes: AllowedChanges = Field(default_factory=dict)
    expected_outcome: Status | None = None
    report_checks: list[ReportCheck] = Field(default_factory=list)
    approver: Approver = "none"
    chaos_variants: list[ChaosVariant] = Field(default_factory=list)
    variants: dict[Approver, Variant] | None = None

    @field_validator("allowed_changes")
    @classmethod
    def _tables(cls, value: AllowedChanges) -> AllowedChanges:
        return _check_tables(value)

    @field_validator("seed")
    @classmethod
    def _known_seed(cls, value: str) -> str:
        if value not in seed.SEEDS:
            raise ValueError(f"unknown seed {value!r}; known: {sorted(seed.SEEDS)}")
        return value

    @field_validator("now")
    @classmethod
    def _frozen_now(cls, value: str) -> str:
        clock.parse_now(value)  # ISO datetime with +05:30, or ValueError
        return value

    @model_validator(mode="after")
    def _single_or_variants(self) -> "Task":
        if self.variants is None:
            if self.expected_outcome is None or not self.success:
                raise ValueError("a task without variants needs expected_outcome and success")
        else:
            if self.expected_outcome is not None or self.success or self.report_checks or self.allowed_changes:
                raise ValueError("with variants, outcome, success, allowed_changes and report_checks live in each variant")
            if set(self.variants) != {"none", "approve", "reject"}:
                raise ValueError("variants must cover the approver decisions none, approve and reject")
        names = [p.name for p in self.success + self.checkpoints]
        if len(names) != len(set(names)):
            raise ValueError("predicate names must be unique within a task")
        return self


class Run(_Strict):
    """One benchmark run of a task: what the engine checks."""
    run_id: str
    task: Task
    approver: Approver
    expected_outcome: Status
    success: list[Predicate]
    checkpoints: list[Predicate]
    allowed_changes: AllowedChanges
    report_checks: list[ReportCheck]


def runs(task: Task) -> list[Run]:
    if task.variants is None:
        return [Run(run_id=task.id, task=task, approver=task.approver, expected_outcome=task.expected_outcome,
                    success=task.success, checkpoints=task.checkpoints, allowed_changes=task.allowed_changes,
                    report_checks=task.report_checks)]
    return [Run(run_id=f"{task.id}:{approver}", task=task, approver=approver, expected_outcome=v.expected_outcome,
                success=v.success, checkpoints=task.checkpoints, allowed_changes=v.allowed_changes,
                report_checks=v.report_checks)
            for approver, v in task.variants.items()]


class _NoDuplicateKeys(yaml.SafeLoader):
    """A repeated key is an error, not "last one wins" (as in the policy loader, N.78)."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        keys = [self.construct_object(k, deep=deep) for k, _ in node.value]
        duplicates = {k for k in keys if keys.count(k) > 1}
        if duplicates:
            raise yaml.constructor.ConstructorError(None, None, f"duplicate keys {sorted(map(str, duplicates))}",
                                                    node.start_mark)
        return super().construct_mapping(node, deep)


def parse(text: str) -> Task:
    data: Any = yaml.load(text, Loader=_NoDuplicateKeys)  # noqa: S506 (a SafeLoader subclass)
    if not isinstance(data, dict):
        raise ValueError("a task file must be a YAML mapping")
    return Task.model_validate(data)


def load(task_id: str) -> Task:
    task = parse((TASK_DIR / f"{task_id}.yaml").read_text())
    if task.id != task_id:
        raise ValueError(f"{task_id}.yaml declares id {task.id!r}")
    return task


def load_all() -> list[Task]:
    return [load(p.stem) for p in sorted(TASK_DIR.glob("T*.yaml"), key=lambda p: int(p.stem[1:]))]


def all_runs() -> list[Run]:
    return [run for task in load_all() for run in runs(task)]


def cassette_scope(run: Run, chaos: str | None = None, chaos_seed: int = 0) -> str:
    """The recording scenario of a live run (D-209, D-211). A chaos run and a rejection share their first requests
    with the plain run but continue differently, so each records its own replies. `none` stops at the held call and
    `approve` continues the plain recording (recorded after `none`, D-203), so a person approving T9 in `make ui`
    during a replay follows it. A fixed name, never the agent's run id or a time."""
    return "|".join([*(["reject"] if run.approver == "reject" else []), *([f"{chaos}:{chaos_seed}"] if chaos else [])])
