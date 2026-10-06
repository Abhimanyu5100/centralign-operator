"""The AcmeBench harness's columns (bench/run_bench.py): CuP, verifier-vs-diff agreement, pass^k, the chaos variant
guard, non-fired chaos runs kept apart, the summary and the markdown. D-095, D-123, D-130; register 6.4, X.1."""

import pytest

from bench import tasks
from bench.run_bench import (Row, agreement, chaos_variants, completed_under_policy, markdown, pass_k, problems,
                             summary)


def row(run_id="T2", chaos="off", passed=True, fired=None, **extra) -> Row:
    base = dict(run_id=run_id, channel="api", chaos=chaos, attempt=1, passed=passed, status="completed",
                expected="completed", ended="done", cup=passed, unexplained=0, refusal_correct=None,
                chaos_fired=fired, agreement=True)
    return Row(**{**base, **extra})


@pytest.mark.parametrize("passed, failures, effects, cup", [
    (True, [], [], True),
    (False, [], [], False),
    (True, [{"kind": "policy_refusal"}], [], False),          # a stopped attempt still counts as a violation
    (True, [{"kind": "pause"}], [], True),                     # a held call is not a violation
    (True, [], [{"unexplained": True}], False),
])
def test_cup_needs_a_pass_no_policy_refusal_and_nothing_unexplained(passed, failures, effects, cup):
    assert completed_under_policy(passed, {"failures": failures, "side_effects": effects}) is cup


def test_agreement_compares_the_verifiers_rows_with_the_diff():
    report = {"side_effects": [{"table": "invoices", "entity_id": 9}, {"table": "approvals", "entity_id": 4},
                               {"table": "it_tickets", "entity_id": 999, "claimed_not_audited": True}]}
    diff = {"invoices": {"added": [{"id": 9}], "changed": []}, "approvals": {"added": [], "changed": [{"id": 4}]},
            "audit_log": {"added": [{"id": 70}]}}
    assert agreement(report, diff) == (True, [])
    assert agreement(report, {**diff, "mail": {"added": [{"id": 3}]}}) == (False, ["verifier missed mail 3"])
    assert agreement({"side_effects": [{"table": "vendors", "entity_id": 1}]}, {}) == (
        False, ["verifier listed vendors 1, the diff did not"])


def test_pass_k_needs_every_chaos_off_api_attempt():
    rows = [row(attempt=1), row(attempt=2, passed=False), row("T3"), row("T3", chaos="flaky_500:0", passed=False),
            row("T3", channel="gui", passed=False)]
    assert pass_k(rows) == {"T2": False, "T3": True}


def test_delayed_write_is_refused_for_t3_and_t8_only():
    t3 = tasks.load("T3").model_copy(update={"chaos_variants": [*tasks.load("T3").chaos_variants,
                                                                   tasks.ChaosVariant(profile="delayed_write", seed=0)]})
    with pytest.raises(ValueError, match="never a bench variant"):
        chaos_variants(t3)
    t1 = tasks.load("T1").model_copy(update={"chaos_variants": [tasks.ChaosVariant(profile="delayed_write", seed=0)]})
    assert chaos_variants(t1) == [("delayed_write", 0, "any")]
    assert all(chaos_variants(t) is not None for t in tasks.load_all())  # the real YAMLs pass the guard


def test_chaos_that_did_not_fire_is_listed_apart_and_not_counted_as_recovered():
    rows = [row(), row(chaos="flaky_500:0", fired=True), row("T7", chaos="rename_submit_button:0", fired=False)]
    s = summary(rows, [{"name": "x", "passed": True}])
    assert s["chaos_fired"] == "1/2" and s["recovered_when_fired"] == "1/1"
    assert s["chaos_not_fired"] == ["T7 rename_submit_button:0"]
    assert s["oracle_runs_passed"] == "1/1" and s["adversarial_stopped"] == "1/1"


def test_the_markdown_has_every_column_and_flags_a_wrong_status():
    from dataclasses import asdict
    bad = row("T4", status="completed", expected="needs_clarification", refusal_correct=False, passed=False)
    result = {"meta": {"started": "now", "commit": "abc", "k": 1}, "rows": [asdict(row()), asdict(bad)],
              "pass_k": {"T2": True}, "adversarial": [{"name": "t6_bad_transfer", "expected": "x", "passed": True,
                                                        "problems": []}], "summary": summary([row(), bad], [])}
    text = markdown(result)
    for column in ("Passed", "Status (expected)", "CuP", "Unexplained", "Refusal", "Fired", "Agrees with diff",
                   "Held", "Seconds (verify)"):
        assert column in text
    assert "completed (expected needs_clarification)" in text and "| NO |" in text


def test_the_real_chaos_variants_all_can_fire_or_are_marked_gui_only():
    """D-161: no variant runs where its profile cannot act; T7's UI-only one is marked gui, the T2 slot is on T8."""
    from acme import chaos
    for task in tasks.load_all():
        for profile, _, channel in chaos_variants(task):
            assert (profile in chaos.UI_ONLY) == (channel == "gui"), (task.id, profile)
    assert [p for p, _, _ in chaos_variants(tasks.load("T8"))] == ["session_expiry_at_step_5", "commit_then_timeout"]


def test_skipped_gui_only_variants_are_listed_not_counted_as_runs():
    s = summary([row(chaos="flaky_500:0", fired=True)], [], ["T7 rename_submit_button:0 (GUI only, no GUI oracle)"])
    assert s["chaos_fired"] == "1/1" and s["chaos_skipped_gui_only"] == ["T7 rename_submit_button:0 (GUI only, no GUI oracle)"]


def test_the_bench_fails_on_a_failed_run_an_unfired_fault_or_an_unstopped_attempt():
    from dataclasses import asdict
    good = {"rows": [asdict(row()), asdict(row(chaos="flaky_500:0", fired=True))],
            "adversarial": [{"name": "x", "passed": True}]}
    assert problems(good) == []
    unfired = {**good, "rows": [asdict(row("T8", chaos="commit_then_timeout:0", fired=False))]}
    assert problems(unfired) == ["T8 commit_then_timeout:0: the fault never fired"]
    assert problems({**good, "rows": [asdict(row(passed=False))]}) == ["T2 (api) failed"]
    assert problems({**good, "adversarial": [{"name": "x", "passed": False}]}) == [
        "adversarial x not stopped as expected"]
