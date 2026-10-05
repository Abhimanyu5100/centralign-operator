---
description: Flag every risk for the step we are about to build, with handling and proof
argument-hint: [step or component, e.g. "policy gate" or "Day 2 executor loop"]
---
We are about to work on: $ARGUMENTS

1. Read `docs/failure-register.md`, `docs/risk-log.md` and, if relevant, `docs/model-plan.md`.
2. List every risk that applies to this step as a table:
   | # | Problem | How it shows up | How we handle it | How we prove it |
   Reuse register IDs where they apply. Think beyond the register: name new risks specific to the
   code we are about to write (edge cases, concurrency, free-tier limits, testability, interview
   explainability).
3. Append any NEW risks to `docs/risk-log.md` with status `open`.
4. Say which risks the planned implementation covers, which it defers, and why.
5. Do not start implementing until I confirm.
