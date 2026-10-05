---
name: day-review
description: Review one build day's work against the spec, CLAUDE.md decisions and failure-register rows with Scope=build; checks tests, agent/ isolation, git rules, docs vs code, and progress.md freshness. Read-only.
argument-hint: "<day number, e.g. 2>"
disable-model-invocation: true
---

# Day review

Day: $ARGUMENTS

**Read-only: no edits unless the user asks.** Never run `git commit` or `git push`.

## Sources of truth

- The Build order row for this day in `CLAUDE.md`, plus its key decisions and "Never" list.
- `docs/acme-spec.md` (for Day 1, the whole spec; for other days, the parts the day touches).
- `docs/failure-register.md`: rows with Scope `build` whose mechanism belongs to this day's work.
- `docs/progress.md` (Done log for this day) and `docs/decisions.md`.

## Checks

1. **Tests**: `pytest -q`. Every Scope=build row for this day has its named test, and that test passes.
2. **Day's done-when**: each criterion in the Build order row is met (cite evidence).
3. **No Acme-specific selectors or IDs in `agent/`**:
   `grep -rnE 'acme\.example|INV-[0-9]+|Save invoice|"/(invoices|payments|employees|it-tickets|mail|approvals|vendors)' agent/`
   Any hit is a gap unless it is clearly generic.
4. **`agent/` never reads `bench/`**: `grep -rn 'bench' agent/`, plus the isolation test passes.
5. **Git rules**: `python3 scripts/check_attribution.py`; `git log --format='%an <%ae>' | sort -u`
   shows only the author.
6. **Docs match code**: spec items for this day exist as specified; the `CLAUDE.md` Commands section
   matches the Makefile; deviations are recorded in `progress.md` with a decision row.
7. **progress.md freshness**: flag it if it is older than the latest code change:
   ```
   git log -1 --format=%ct -- docs/progress.md          # last progress commit
   git log -1 --format=%ct -- . ':!docs/progress.md'    # last other commit (newer = stale)
   find . -type f -newer docs/progress.md -not -path './.git/*' -not -path './.venv/*' \
     -not -path '*/__pycache__/*' -not -path './runs/*' -not -name decisions.md -not -name risk-log.md
   ```
   Also flag Done-log rows marked `pending` that git shows as committed (git wins).

## Output

One table: `| item | status (ok / gap / risk) | evidence | fix |`. Evidence is a command result,
`path:line` or a test name. Then list the top three fixes in priority order, and stop.
