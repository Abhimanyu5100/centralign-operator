"""The AcmeBench harness's columns (bench/run_bench.py): CuP, verifier-vs-diff agreement, pass^k, the chaos variant
guard, non-fired chaos runs kept apart, the summary and the markdown. D-095, D-123, D-130; register 6.4, X.1."""

import pytest

from bench import tasks
from bench.run_bench import Row, agreement, chaos_variants, completed_under_policy, markdown, pass_k, summary


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
    assert chaos_variants(t1) == [("delayed_write", 0)]
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
