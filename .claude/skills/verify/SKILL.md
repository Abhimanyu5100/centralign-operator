---
name: verify
description: Verify one committed build part in a separate git worktree - run Acme on port 8001, derive checks from the part's Done-log row and risk rows, run them with curl, run make test (concurrency tests 5 times) and the ship-check steps, then report pass/fail and whether it is ready to push. Strictly read-only.
argument-hint: "<day.part, e.g. 1.5>"
disable-model-invocation: true
---

# Verify a committed part

Part: $ARGUMENTS

Rules live in `CLAUDE.md` ("Git and commits", "Never"). This skill is **strictly read-only**:

- No edits to code, tests or docs; no `/checkpoint`; never `git commit` or `git push`; never open `.env`.
- Acme runs on **port 8001**, never 8000 (the author may have `make acme` running there).
- Parse every id from responses (`python3 -c 'import json,sys; ...'`); never hard-code ids.
- Stop only the server this skill started (by its PID), never `pkill` by pattern.

## 1. Set up

1. Find the part's commit: `git log --format='%h %s'`, the one subject starting `Day $ARGUMENTS:`.
   None or several: stop and report that; do not guess.
2. `git worktree add --detach "$CLAUDE_JOB_DIR/tmp/verify-$ARGUMENTS" <hash>` (any scratch directory if
   `$CLAUDE_JOB_DIR` is unset) and run every later command from inside it. The worktree has its own
   `acme/data/acme.db` and `uv` environment, so the author's checkout and server are untouched.
3. `make reset`, then start Acme in the background and record its PID:
   `uv run uvicorn --factory acme.app:create_app --host 127.0.0.1 --port 8001`. Wait for `GET /healthz`.

## 2. Derive the checks (do not invent scope)

- `docs/progress.md`: the part's Done-log row, its "Deviations from spec" entry and any "how to check" notes.
- `docs/risk-log.md`: the "How we prove it" / Test column of every risk the row says it added or tested.
- `docs/acme-spec.md` and `CLAUDE.md` for the expected behaviour behind each check.

Each check gets an expected result before it runs. Log in through `POST /api/login` with the dev
credentials from `acme/auth.py` (or the env overrides already exported in the shell; never read `.env`).

## 3. Run

1. The derived checks with `curl` against `http://127.0.0.1:8001` (Playwright from Day 2 on).
2. `make test`, then every concurrency test 5 times in a loop
   (`uv run pytest -q -k "at_once or concurrent or race"`); one failure in five is a fail.
3. The ship-check steps by hand, as listed in `.claude/skills/ship-check/SKILL.md` ("Run", steps 1-6);
   that skill cannot be invoked by the model. Skip its commit commands.

## 4. Clean up (always, even after a failure)

1. `kill <PID>` of the server started in step 1.3; confirm port 8001 is free.
2. `make reset` inside the worktree.
3. `git worktree remove --force "$CLAUDE_JOB_DIR/tmp/verify-$ARGUMENTS"` (scratch files only; nothing
   in it is the author's work).

## Report

| # | check | expected | actual | pass/fail |
| --- | --- | --- | --- | --- |

Then, for each failure: the cause (with the command and output that showed it), a proposed fix and the
files it would touch. Do not apply the fix.

End with exactly one line: `ready to push: yes` or `ready to push: no` (no if any check failed, a
ship-check step failed, or the part's commit could not be found).
