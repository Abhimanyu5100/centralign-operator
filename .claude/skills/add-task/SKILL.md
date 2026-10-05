---
name: add-task
description: Create a new AcmeBench benchmark task from a one-line request - task YAML, SQL checker with a passing-state and a failing-state test, oracle, and an adversarial script if the task tests a policy. Use when the user asks for a new benchmark task.
argument-hint: "<one-line request, e.g. \"Process the invoice from Gupta Metals\">"
---

# Add a benchmark task

Request: $ARGUMENTS

Rules live in `CLAUDE.md` and `docs/`; this skill only lists the steps. Never run `git commit` or
`git push`.

## 1. Read first

- `docs/acme-spec.md`: "Tasks" (YAML schema, default `now`), "Business rules", the policy table, and
  "Checkers, oracles and adversarial scripts".
- `CLAUDE.md`: "Approvals and run statuses". `expected_outcome` must be one of those statuses. Also
  decision 11 (`agent/` never reads `bench/`).
- The existing `bench/tasks/`, `bench/checkers/`, `bench/oracles/` and `bench/adversarial/`, for
  conventions. Pick the next free task ID.

## 2. Risk table, then confirm

Output the risk table required by the standing rule in `CLAUDE.md`. If the task needs new Acme seed
data, PDFs, inbox messages or SOP text, list them and **wait for confirmation before editing anything
under `acme/`**.

## 3. Write

1. `bench/tasks/<id>.yaml` with every schema field: `id`, `request`, `category`, `seed`, `now` (frozen,
   `+05:30`), `success`, `checkpoints`, `allowed_changes`, `expected_outcome`, `report_checks` (if the
   outcome must be visible in the run report), `approver` (if an action approval is involved),
   `chaos_variants`.
2. `bench/checkers/<id>.py`, plus tests with one hand-made passing state and at least one failing state.
   The failing state should be the most plausible wrong end state (wrong amount, PO number used as the
   invoice number, duplicate row, missing approval request, write on an ask/infeasible task).
3. `bench/oracles/<id>.py`: the perfect agent, calling `registry.call(...)` in the correct order. It
   ends with ask / infeasible when that is the expected outcome, and never attempts a forbidden call.
4. If the task tests a policy: `bench/adversarial/<id>_<attempt>.py`, which attempts the forbidden call.
   It passes when the call is stopped with the expected policy ID and Acme state is unchanged.
5. Add a row for the task to the task table in `docs/acme-spec.md`.

## 4. Verify and report

- `pytest bench/checkers -k <id> -q` (paste the summary line).
- If Acme and the registry exist: run the oracle with chaos off (`make oracle TASK=<id>` once it
  exists), then run the checker on that end state.
- Report the files written, test results, and anything not run, with the reason.

## 5. Finish

Run `/checkpoint`.
