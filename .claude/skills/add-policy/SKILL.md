---
name: add-policy
description: Add or change a policy rule enforced by the runtime gate - the YAML rule in acme/knowledge/policies.yaml, a new condition type only if no existing one fits, a passing and a failing gate test, and an adversarial script if the rule stops an attack. Use when the user asks for a new policy, or to change what the gate allows, denies or holds for approval.
argument-hint: "<the rule in one sentence, e.g. \"hold every payment request above Rs 2 lakh for an action approval\">"
---

# Add a policy rule

Rule: $ARGUMENTS

Rules live in `CLAUDE.md` (decisions 4 and 7, "Approvals and run statuses") and `docs/`; this skill only lists
the steps. Never run `git commit` or `git push`.

1. Read `acme/knowledge/policies.yaml` (its header), the condition types in `agent/policy/models.py`, the
   evaluator's design in `docs/day3-plan.md` (A1), and the "Policy gate" rows of `docs/failure-register.md`.
2. Run `/risk-check` for the rule.
3. Decide whether existing condition types express it. If they do, it is a YAML edit only. If not, add one
   condition type: a model class plus its name in `CONDITION_TYPES` (`models.py`), one function in the gate's
   `CONDITIONS` table (`gate.py`), and fixtures in `tests/policy/test_schema.py`. The gate refuses to start
   until the function exists.
4. Write the rule: next free id at its level, `enforced_by`, `effect` (`deny` or `require_approval`), `when`,
   and a `message` of at most 300 characters. An `enforced_by: acme` rule also needs `acme_check` entries.
5. In `tests/policy/test_gate.py`, add one test the rule passes and one it fails. Build API calls through the
   `api` fixture (the real catalog) and GUI submits through `gui(...)`.
6. If the rule stops an attack, add a script in `bench/adversarial/` (any fixture tool named `test_only_*`) and
   list it in `bench/adversarial/__init__.py` `NAMES` and in acme-spec's adversarial table.
7. Run `make test`, `make adversarial` and `make bench`. Every oracle must still pass. An oracle that is now held
   or denied means the rule or the oracle is wrong: diagnose it, never loosen a check.
8. Update the acme-spec policy table, add a `docs/decisions.md` row and any new risks, then run `/checkpoint`.
