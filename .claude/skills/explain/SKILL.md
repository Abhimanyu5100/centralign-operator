---
name: explain
description: Interview-ready walkthrough of one module - purpose, design choices with cited reasons, invariants, failure handling with proving tests, likely live changes, and interviewer questions. Read-only.
argument-hint: "<path to a module or package, e.g. agent/policy/>"
disable-model-invocation: true
---

# Explain a module for the interview

Target: $ARGUMENTS

**Read-only: do not edit any file.** Never run `git commit` or `git push`.

## Read

- The target, plus its tests (`tests/` and any `bench/` tests that exercise it) and its direct callers
  and callees.
- `CLAUDE.md` (architecture and key decisions), `docs/research-notes.md`, `docs/failure-register.md`,
  `docs/decisions.md`, and `docs/acme-spec.md` if the module touches Acme.
- Cite only what you find. If a design choice has no source in the docs, say "no recorded reason".

## Output (in this order, as plain prose and short lists)

1. **What it does**, in 3 lines.
2. **Design choices**: each choice with its reason, citing a paper from `research-notes.md`, a
   failure-register ID (e.g. `3.5`), a decision ID (e.g. `D-017`) or a `CLAUDE.md` decision number.
   Point to code as `path:line`.
3. **Invariants** it must keep (e.g. "every tool call passes the gate", "status only from the
   verifier"), and where each is enforced in the code.
4. **How it fails**: each failure mode, how the code handles it, and which test proves the handling
   (file and test name). Flag any failure mode without a test as a gap.
5. **Three most likely live changes** (e.g. "add a policy rule", "add a tool", "add a status"): for
   each, the files to touch, the exact steps, and the test to run afterwards.
6. **Three interviewer questions**, each with a short answer (2–4 sentences) grounded in the code and
   the docs.

Keep it to what the author can say out loud in about five minutes.
