---
name: ship-check
description: Pre-commit / pre-submission check - pytest, attribution scan, secret grep, .env untracked, stale docs and stale progress.md - then print pass/fail and the exact commit commands for the author. Never commits or pushes.
disable-model-invocation: true
---

# Ship check

Rules live in `CLAUDE.md` ("Git and commits", "Never"). **Never run `git commit` or `git push`**;
only print the commands for the author.

## Run

1. **Tests**: `pytest -q`
2. **Attribution**: `python3 scripts/check_attribution.py`
3. **Secrets** (prints file:line only, never the matched text):
   ```
   git grep -nIE --untracked \
     'AIza[0-9A-Za-z_-]{30,}|gsk_[0-9A-Za-z]{20,}|sk-or-v1-[0-9a-f]{20,}|sk-[0-9A-Za-z_-]{20,}|(api[_-]?key|secret|token)[[:space:]]*[:=][[:space:]]*["'"'"']?[0-9A-Za-z_-]{16,}' \
     | cut -d: -f1,2
   ```
   Any hit fails. Also check `cassettes/` and `runs/` if they are tracked.
4. **.env**: `git ls-files --error-unmatch .env` must fail (untracked) and `git check-ignore -q .env`
   must succeed. Never open or print `.env`.
5. **Stale docs**: compare the code against `CLAUDE.md` (layout, Commands, build order) and
   `docs/acme-spec.md` (endpoints, tables, chaos profiles, tasks). List each doc that no longer matches,
   with `path:line` and what changed.
6. **progress.md freshness**: flag it if it is older than the latest code change:
   ```
   git log -1 --format=%ct -- docs/progress.md
   git log -1 --format=%ct -- . ':!docs/progress.md'
   find . -type f -newer docs/progress.md -not -path './.git/*' -not -path './.venv/*' \
     -not -path '*/__pycache__/*' -not -path './runs/*' -not -name decisions.md -not -name risk-log.md
   ```
   Also flag Done-log rows marked `pending` that are already committed, and work in `git status` that
   has no Done-log row.

## Output

1. Summary table: `| check | pass/fail | detail |`.
2. If anything fails: what to fix first, and stop there (no commit commands).
3. If all pass: the exact commands for the author to run, with explicit file paths (no `git add -A`
   unless every changed file was reviewed) and a suggested message, e.g.
   ```
   git status --short
   git diff --stat
   git add <file> <file> ...
   git commit -m "<Day N.part: what was built>"
   python3 scripts/check_attribution.py
   git push        # only before submission or when the author chooses
   ```
