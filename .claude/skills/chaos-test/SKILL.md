---
name: chaos-test
description: Run an oracle under a named chaos profile and read what happened (fired, the verifier's status, classified failures, no double write), or add a chaos variant to a bench task. Use when the user asks to test recovery under a fault, reproduce a chaos failure, or add a chaos run to AcmeBench.
argument-hint: "<task and profile, e.g. \"T8 commit_then_timeout\">"
---

# Chaos test

Target: $ARGUMENTS

Rules live in `CLAUDE.md` (Build order: oracles under chaos measure detection, not success) and `docs/`
(acme-spec "Chaos profiles", D-094, D-095, D-123, D-161, D-162); this skill only lists the steps. Never run
`git commit` or `git push`.

1. Pick the profile and seed (0 unless reproducing another). A UI-only profile (`acme.chaos.UI_ONLY`) needs the
   task's GUI oracle (`CHANNEL=gui`). Never pair `delayed_write` with T3 or T8 in the bench.
2. Run `make oracle TASK=<task> CHAOS=<profile> CHAOS_SEED=0 [CHANNEL=gui] EVENTS=1`.
3. Read the output in this order:
   - "chaos fired": if it says no, the run measured nothing; find out why before reading anything else;
   - the verifier status and its reasons;
   - the retry lines (`attempts`, `already_done`);
   - the report under `runs/<run_id>/report.md`: failures and their class, side effects (anything unexplained,
     anything claimed but not stored);
   - the checker lines.
4. Check by SQL or the diff that nothing was written twice.
5. To add the run to AcmeBench: add `{profile, seed}` (plus `channel: gui` for a UI-only profile) to the task YAML's
   `chaos_variants`, update `tests/checkers/test_engine.py::test_chaos_variants_follow_d095_and_d161`, then run
   `make bench`. Every chaos run must fire, or the bench fails.
6. Record what you found (risk log, decisions if a rule changed), then run `/checkpoint`.
