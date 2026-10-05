---
name: checkpoint
description: End-of-part checkpoint - update docs/progress.md (Now section, RESUME PROMPT, Done log), append new decisions and risks, and list what the author should review plus the exact commit command. Use at the end of every build part, before saying a part is done.
---

# Checkpoint

Rules live in `CLAUDE.md` (standing rules, "Git and commits"). **Never run `git commit` or
`git push`.**

## Gather

- `git status --short`, `git diff --stat`, `git log --oneline -5`
- Test results from this part (re-run `pytest -q` if they are not already in this conversation).
- IST timestamp: `TZ=Asia/Kolkata date '+%Y-%m-%d %H:%M IST'`

## Update `docs/progress.md`

1. **Now**: last updated (IST), day / phase / part, currently doing, next step, and the **RESUME
   PROMPT**: the exact text the author pastes into a fresh session to continue from the next step. It
   must start with "Read CLAUDE.md and docs/progress.md", name the next part, and end with "Do not
   commit or push."
2. **Done log**: add one row `| date | day.part | what was built | files | tests (pass/fail with counts)
   | pending |`. For earlier rows marked `pending`, fill in the hash if `git log` shows they were
   committed (git wins).
3. **Blockers and open questions**: add new ones; remove resolved ones.
4. **Deviations from spec**: add any place this part's code differs from `docs/acme-spec.md` or
   `CLAUDE.md`, with the reason.

## Append (never edit past rows)

- `docs/decisions.md`: one row per decision made in this part (next free `D-` ID; use `Supersedes`
  when it changes an earlier decision).
- `docs/risk-log.md`: one row per new risk (next free `N.` ID, status `open`); update the status of
  risks this part handled or tested.

## Report to the author

1. Files to review, most important first, each with one line on what changed.
2. Anything not done or not tested, with the reason.
3. The exact commands to run:
   ```
   git diff
   git add <explicit paths>
   git commit -m "Day <N>.<part>: <what was built>"
   ```
Then stop.
