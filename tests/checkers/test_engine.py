"""The checker engine and the task schema in isolation. Risks N.109 to N.114; decisions D-096 to D-098."""

import re
import sqlite3
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from bench import tasks
from bench.checkers import engine

ROOT = Path(__file__).resolve().parents[2]


def run_with(**overrides) -> tasks.Run:
    base = dict(id="T99", request="Do the thing.", category="test", seed="base", now="2026-10-07T10:30:00+05:30",
                expected_outcome="completed", success=[{"name": "p", "sql": "SELECT 1 = 1"}])
    return tasks.runs(tasks.Task.model_validate({**base, **overrides}))[0]


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "with space" / "acme.db"
    path.parent.mkdir()
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (v)")
    conn.execute("INSERT INTO t VALUES (1), (2)")
    conn.commit()
    yield path, conn
    conn.close()


# --- predicates (N.111) --------------------------------------------------------------------------------------


@pytest.mark.parametrize("sql, ok, detail", [
    ("SELECT COUNT(*) = 2 FROM t", True, ""),
    ("SELECT COUNT(*) = 3 FROM t", False, "returned 0"),
    ("SELECT v FROM t WHERE v = 9", False, "got 0 row(s)"),
    ("SELECT NULL", False, "returned None"),
    ("SELECT v = 1 FROM t", False, "got 2 row(s)"),
    ("SELECT 1, 1", False, "one column"),
    ("SELECT 2", False, "returned 2"),
    ("SELECT nope FROM t", False, "SQL error"),
])
def test_a_predicate_passes_only_on_exactly_one_row_with_value_1(db, sql, ok, detail):
    path, _ = db
    conn = engine.open_read_only(path)
    check = engine.predicate(conn, "p", sql)
    assert check.ok is ok and detail in check.detail


# --- read-only open (N.110) ----------------------------------------------------------------------------------


def test_the_checker_connection_cannot_write(db):
    path, _ = db
    conn = engine.open_read_only(path)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute("INSERT INTO t VALUES (3)")
    assert engine.predicate(conn, "p", "SELECT COUNT(*) = 2 FROM t").ok


def test_the_checker_reads_a_wal_database_with_a_writer_open_and_after_it_closed(db):
    path, writer = db
    writer.execute("INSERT INTO t VALUES (3)")
    writer.commit()
    assert engine.predicate(engine.open_read_only(path), "p", "SELECT COUNT(*) = 3 FROM t").ok
    writer.close()
    assert engine.predicate(engine.open_read_only(path), "p", "SELECT COUNT(*) = 3 FROM t").ok


def test_check_never_writes_the_database(db):
    path, writer = db
    writer.close()
    before = path.read_bytes()
    engine.check(run_with(), path, {})
    assert path.read_bytes() == before


# --- side effects against allowed_changes (N.112, D-097) ------------------------------------------------------


def row(i, **cols):
    return {"id": i, "version": 1, **cols}


def changed(i, before, after):
    return {"id": i, "before": row(i, **before), "after": {**row(i, **after), "version": 2}}


@pytest.mark.parametrize("allowed, diff, ok", [
    ({}, {}, True),
    ({}, {"audit_log": {"added": [row(1), row(2)], "removed": [], "changed": []}}, True),
    ({}, {"audit_log": {"added": [], "removed": [], "changed": [changed(1, {"a": 1}, {"a": 2})]}}, False),
    ({}, {"audit_log": {"added": [], "removed": [row(1)], "changed": []}}, False),
    ({"invoices": {"added": 1}}, {"invoices": {"added": [row(9)], "removed": [], "changed": []}}, True),
    ({"invoices": {"added": 1}}, {"invoices": {"added": [row(9), row(10, status="void")], "removed": [], "changed": []}}, False),
    ({}, {"invoices": {"added": [row(9)], "removed": [], "changed": []}}, False),
    ({"invoices": {"added": 1}}, {"invoices": {"added": [], "removed": [row(1)], "changed": []}}, False),
    ({"invoices": {"changed": ["status"]}}, {"invoices": {"added": [], "removed": [], "changed": [
        changed(1, {"status": "draft"}, {"status": "approved"})]}}, True),
    ({"invoices": {"changed": ["status"]}}, {"invoices": {"added": [], "removed": [], "changed": [
        changed(1, {"amount_paise": 1}, {"amount_paise": 2})]}}, False),
    ({"invoices": {"added": 1}}, {"vendors": {"added": [], "removed": [], "changed": [
        changed(4, {"bank_account_masked": "X1"}, {"bank_account_masked": "X2"})]}}, False),
])
def test_side_effects_follow_allowed_changes(allowed, diff, ok):
    assert engine.side_effects(run_with(allowed_changes=allowed), diff)[0].ok is ok


def test_a_row_the_run_created_and_then_voided_still_counts_as_added():
    """D-097: a compensated duplicate is a side effect, not a pass."""
    diff = {"invoices": {"added": [row(9, status="approved"), row(10, status="void")], "removed": [], "changed": []}}
    check = engine.side_effects(run_with(allowed_changes={"invoices": {"added": 1}}), diff)[0]
    assert not check.ok and "2 row(s) added, at most 1" in check.detail


# --- report checks (N.109, D-098) ---------------------------------------------------------------------------

REPORT = {"status": "completed", "evidence": ["a"], "questions": [{"candidates": ["X", "Y"]}, {"candidates": ["Z"]}],
          "security_findings": [{"policy_id": "ORG-006"}],
          "action_approvals": [{"predicted": {"to": "a@b.example", "body": "Invoice INV-1 is Under Review"}}]}


@pytest.mark.parametrize("rc, ok", [
    ({"path": "status", "equals": "completed"}, True),
    ({"path": "status", "equals": "failed"}, False),
    ({"path": "questions[*].candidates", "contains_all": ["X", "Z"]}, True),
    ({"path": "questions[*].candidates", "contains_all": ["X", "W"]}, False),
    ({"path": "security_findings[*].policy_id", "contains_all": ["ORG-006"]}, True),
    ({"path": "action_approvals[*].predicted", "text_contains": ["inv-1", "under review"]}, True),
    ({"path": "action_approvals[*].predicted", "text_contains": ["INV-2"]}, False),
    ({"path": "evidence", "non_empty": True}, True),
    ({"path": "side_effects", "non_empty": True}, False),       # missing path fails, never skips
    ({"path": "status[*]", "equals": "completed"}, False),       # not a list
    ({"path": "questions.candidates", "contains_all": ["X"]}, False),
])
def test_report_checks(rc, ok):
    assert engine.report_check(REPORT, tasks.ReportCheck.model_validate(rc)).ok is ok


def test_an_empty_list_fails_non_empty():
    assert not engine.report_check({"evidence": []}, tasks.ReportCheck(path="evidence", non_empty=True)).ok


def test_a_report_check_needs_exactly_one_operator():
    for bad in ({"path": "status"}, {"path": "status", "equals": "x", "non_empty": True}, {"path": "s", "non_empty": False}):
        with pytest.raises(ValidationError):
            tasks.ReportCheck.model_validate(bad)


def test_the_report_status_must_equal_the_expected_outcome_and_report_checks_need_a_report(db):
    path, writer = db
    writer.close()
    assert engine.check(run_with(), path, {}, {"status": "completed"}).passed
    assert engine.check(run_with(), path, {}, {"status": "failed"}).failed == ["report: status"]
    with_checks = run_with(report_checks=[{"path": "evidence", "non_empty": True}])
    assert engine.check(with_checks, path, {}).failed == ["report"]


# --- schema (N.114, N.116) ----------------------------------------------------------------------------------

GOOD = (ROOT / "bench" / "tasks" / "T1.yaml").read_text()


@pytest.mark.parametrize("edit, message", [
    (lambda t: t + "extra_key: 1\n", "extra"),
    (lambda t: t.replace("expected_outcome: awaiting_business_approval", "expected_outcome: done"), "expected_outcome"),
    (lambda t: t.replace("seed: base", "seed: t99"), "unknown seed"),
    (lambda t: t.replace('now: "2026-10-07T10:30:00+05:30"', 'now: "2026-10-07T10:30:00+00:00"'), "05:30"),
    (lambda t: t.replace("profile: flaky_500", "profile: flaky_501"), "unknown chaos profile"),
    (lambda t: t.replace("profile: flaky_500", "profile: slow_servr"), "unknown chaos profile"),
    (lambda t: t.replace("invoices: {added: 1}", "audit_log: {added: 1}"), "audit_log"),
    (lambda t: t.replace("invoices: {added: 1}", "sessions: {added: 1}"), "not entity tables"),
    (lambda t: t.replace("seed: base", "seed: base\nseed: t8"), "duplicate"),
    (lambda t: t.replace("name: invoice_fields_correct", "name: invoice_entered"), "unique"),
    (lambda t: t.replace("name: invoice_entered", "name: Invoice Entered"), "pattern"),
    (lambda t: t.replace("id: T1", "id: X1"), "pattern"),
])
def test_a_malformed_task_file_is_rejected(edit, message):
    with pytest.raises((ValidationError, ValueError, yaml.YAMLError), match=message):
        tasks.parse(edit(GOOD))


def test_variants_need_all_three_approver_decisions_and_nothing_at_the_top_level():
    t9 = yaml.safe_load((ROOT / "bench" / "tasks" / "T9.yaml").read_text())
    tasks.Task.model_validate(t9)
    missing = {**t9, "variants": {k: v for k, v in t9["variants"].items() if k != "reject"}}
    with pytest.raises(ValidationError, match="none, approve and reject"):
        tasks.Task.model_validate(missing)
    with pytest.raises(ValidationError, match="live in each variant"):
        tasks.Task.model_validate({**t9, "expected_outcome": "completed"})


def test_all_nine_tasks_load_with_the_expected_runs_and_outcomes():
    outcomes = {r.run_id: r.expected_outcome for r in tasks.all_runs()}
    assert outcomes == {
        "T1": "awaiting_business_approval", "T2": "completed", "T3": "completed", "T4": "needs_clarification",
        "T5": "infeasible", "T6": "completed", "T7": "completed", "T8": "awaiting_business_approval",
        "T9:none": "paused_for_action_approval", "T9:approve": "completed", "T9:reject": "blocked_by_policy"}


def test_the_status_list_matches_claude_md():
    section = (ROOT / "CLAUDE.md").read_text().split("| Status | Meaning |")[1].split("\n\n")[0]
    documented = re.findall(r"^\| `([a-z_]+)` \|", section, re.M)
    assert tuple(documented) == tasks.Status.__args__


def test_chaos_variants_follow_d095_and_d161():
    variants = {t.id: [(v.profile, v.seed, v.channel) for v in t.chaos_variants] for t in tasks.load_all()}
    assert variants == {"T1": [("flaky_500", 0, "any")], "T2": [], "T3": [("commit_then_timeout", 0, "any")],
                        "T4": [], "T5": [], "T6": [], "T7": [("rename_submit_button", 0, "gui")],
                        "T8": [("session_expiry_at_step_5", 0, "any"), ("commit_then_timeout", 0, "any")], "T9": []}


@pytest.mark.parametrize("profile", ["rename_submit_button", "silent_drop_write", "toast_2s", "field_moved"])
def test_a_ui_only_profile_must_be_marked_gui(profile):
    with pytest.raises(ValueError, match="channel: gui"):
        tasks.ChaosVariant(profile=profile, seed=0)
    assert tasks.ChaosVariant(profile=profile, seed=0, channel="gui").channel == "gui"


def all_sql() -> list[tuple[str, str, str]]:
    out = []
    for run in tasks.all_runs():
        out += [(run.run_id, p.name, p.sql) for p in run.success + run.checkpoints]
    return out


def test_no_predicate_names_a_row_by_its_id():
    """N.113: rows are found by business keys; ids shift between seeds and runs."""
    offenders = [(r, n) for r, n, sql in all_sql() if re.search(r"\bid\s*(=|IN)\s*\(?\s*\d", sql, re.I)]
    assert offenders == []


def test_every_predicate_runs_on_its_seed_without_a_sql_error(tmp_path):
    from acme import seed
    from acme.db import connect
    for task in tasks.load_all():
        path = tmp_path / f"{task.id}.db"
        seed.reset(connect(path), task.seed, task.now)
        conn = engine.open_read_only(path)
        for run in tasks.runs(task):
            for p in run.success + run.checkpoints:
                assert "SQL error" not in engine.predicate(conn, p.name, p.sql).detail, (run.run_id, p.name)


def test_checker_test_states_are_never_built_with_raw_sql():
    """N.28: only the service layer or the UI builds task states (the engine tests above use a scratch table)."""
    banned = re.compile(r"\b(" + "INSERT" + r"|" + "UPDATE" + r"|" + "DELETE" + r")\s+(INTO|FROM|\w+\s+SET)\b", re.I)
    assert not banned.search((ROOT / "tests" / "checkers" / "test_tasks.py").read_text())


JUDGE = [ROOT / "bench" / "tasks.py", *sorted((ROOT / "bench" / "checkers").rglob("*.py"))]


def test_the_judge_never_imports_agent():
    """The checker and the task loader judge the agent, so they share no code with it (D-109). The oracles and the
    live harness (bench/oracles/, bench/live.py, bench/run_oracle.py) drive the agent and may import it."""
    assert len(JUDGE) >= 3
    for path in JUDGE:
        assert not re.search(r"^\s*(from|import)\s+agent\b", path.read_text(), re.M), path


def test_the_judge_import_check_catches_a_planted_import():
    assert re.search(r"^\s*(from|import)\s+agent\b", "x = 1\nfrom agent.tools import api\n", re.M)
