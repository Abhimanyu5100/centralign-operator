---
name: resume
description: Restore context at the start of a session - read progress, recent decisions, open risks and git state, report where we are and any mismatch, then wait.
disable-model-invocation: true
---

# Resume

Read-only. Never run `git commit` or `git push`. Rules live in `CLAUDE.md`; read it first if it is
not already in context.

## Read

- `docs/progress.md` (all of it)
- The last 10 rows of `docs/decisions.md`
- Rows with status `open` in `docs/risk-log.md`
- `git log --oneline -10` and `git status --short`

## Report

1. **Where we are**: day / phase / part, and what was last completed (with commit hash if committed).
2. **Uncommitted work**: files in `git status`, grouped by part. Also any work that exists in the tree
   or in git but has no Done-log row in `progress.md`.
3. **Mismatches between progress.md and git**: e.g. Done-log rows marked `pending` that are committed,
   rows claiming work that git doesn't show, or a Now section older than the latest commit. **Git
   wins** for what is committed; say which entries need correcting (fix them only when asked, or via
   `/checkpoint`).
4. **Open risks and blockers** relevant to the next step.
5. **Next step**: from the Now section, adjusted for anything found above, plus the RESUME PROMPT.

Then **stop and wait for the author.** Do not start the next step.
