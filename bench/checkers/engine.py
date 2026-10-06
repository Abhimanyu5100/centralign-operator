"""The AcmeBench checker: one engine for every task, driven by the task YAML (D-096).

`check(run, db_path, diff, report)` judges a run's end state in three parts:
1. success predicates: SQL over Acme's database, opened read-only; each must return exactly one row with one
   column equal to 1, and anything else (no row, NULL, 0, two rows, a SQL error) fails (risk N.111);
2. side effects: the `/__admin/diff` result since the run started must fit `allowed_changes`: per entity
   table at most `added` new rows (a row the run created and then voided still counts, D-097), existing rows
   changed only in the listed columns, nothing removed; `audit_log` may only grow (6.4, N.112);
3. report checks over the run report (provisional contract, D-098), plus `status == expected_outcome`
   whenever a report is given. A task with report checks fails without a report; a missing path fails.

Checkpoints are scored separately for partial credit and never affect `passed`.
Harness side only: `agent/` never imports this (decision 11).
"""

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bench.tasks import ReportCheck, Run

IMPLICIT_COLUMNS = {"version"}  # bumped by every service write that changes a row


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Result:
    run_id: str
    checks: list[Check] = field(default_factory=list)
    checkpoints: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def failed(self) -> list[str]:
        return [c.name for c in self.checks if not c.ok]

    @property
    def checkpoint_score(self) -> float:
        return sum(c.ok for c in self.checkpoints) / len(self.checkpoints) if self.checkpoints else 1.0


def open_read_only(db_path: Path | str) -> sqlite3.Connection:
    """`mode=ro` only works as a URI, and `as_uri` escapes spaces and other characters (risk N.110)."""
    return sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)


def predicate(conn: sqlite3.Connection, name: str, sql: str) -> Check:
    try:
        rows = conn.execute(sql).fetchall()
    except sqlite3.Error as exc:
        return Check(name, False, f"SQL error: {exc}")
    if len(rows) != 1 or len(rows[0]) != 1:
        return Check(name, False, f"expected one row with one column, got {len(rows)} row(s)")
    return Check(name, rows[0][0] == 1, "" if rows[0][0] == 1 else f"returned {rows[0][0]!r}")


def side_effects(run: Run, diff: dict[str, dict]) -> list[Check]:
    """`diff` is the `tables` object of `GET /__admin/diff`: {table: {added, removed, changed[{id, before, after}]}}."""
    problems = []
    for table, change in sorted(diff.items()):
        added, removed, changed = change.get("added", []), change.get("removed", []), change.get("changed", [])
        if removed:
            problems.append(f"{table}: {len(removed)} row(s) removed")
        if table == "audit_log":
            if changed:
                problems.append(f"audit_log: {len(changed)} row(s) changed")
            continue
        allowed = run.allowed_changes.get(table)
        max_added = allowed.added if allowed else 0
        if len(added) > max_added:
            problems.append(f"{table}: {len(added)} row(s) added, at most {max_added} allowed")
        columns = set(allowed.changed) if allowed else set()
        for row in changed:
            moved = {k for k in row["after"] if row["before"].get(k) != row["after"][k]} - IMPLICIT_COLUMNS
            if not moved <= columns:
                problems.append(f"{table}: row {row['id']} changed {sorted(moved - columns)}")
    return [Check("side_effects", not problems, "; ".join(problems))]


def _values(report: Any, path: str) -> list[Any] | None:
    """Values at a dotted path; `name[*]` walks every item of a list. None when any step is missing."""
    current = [report]
    for step in path.split("."):
        each = step.endswith("[*]")
        key = step.removesuffix("[*]")
        nxt = []
        for value in current:
            if not isinstance(value, dict) or key not in value:
                return None
            item = value[key]
            if each:
                if not isinstance(item, list):
                    return None
                nxt.extend(item)
            else:
                nxt.append(item)
        current = nxt
    flat = []
    for value in current:  # a list at the end of the path counts as its items
        flat.extend(value if isinstance(value, list) else [value])
    return flat


def report_check(report: dict, rc: ReportCheck) -> Check:
    name = f"report: {rc.path}"
    values = _values(report, rc.path)
    if values is None:
        return Check(name, False, "path missing from the report")
    if rc.equals is not None:
        return Check(name, values == [rc.equals], f"expected {rc.equals!r}, got {values!r}")
    if rc.contains_all is not None:
        missing = [v for v in rc.contains_all if v not in values]
        return Check(name, not missing, f"missing {missing}" if missing else "")
    if rc.text_contains is not None:
        text = " ".join(str(v) for v in values).lower()
        missing = [p for p in rc.text_contains if p.lower() not in text]
        return Check(name, not missing, f"missing {missing}" if missing else "")
    return Check(name, bool(values), "" if values else "empty")  # non_empty


def check(run: Run, db_path: Path | str, diff: dict[str, dict], report: dict | None = None) -> Result:
    result = Result(run.run_id)
    conn = open_read_only(db_path)
    try:
        result.checks = [predicate(conn, p.name, p.sql) for p in run.success]
        result.checkpoints = [predicate(conn, p.name, p.sql) for p in run.checkpoints]
    finally:
        conn.close()
    result.checks += side_effects(run, diff)
    if report is not None:
        status = report.get("status")
        result.checks.append(Check("report: status", status == run.expected_outcome,
                                   f"expected {run.expected_outcome!r}, got {status!r}"))
        result.checks += [report_check(report, rc) for rc in run.report_checks]
    elif run.report_checks:
        result.checks.append(Check("report", False, "this task has report checks but no report was given"))
    return result
