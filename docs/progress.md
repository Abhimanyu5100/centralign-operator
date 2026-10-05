# Progress

The single source of truth for where the project is. Updated by `/checkpoint` at the end of every part.
If this file disagrees with git, git wins for what is committed.

## Now

- **Last updated:** 2026-10-05 21:03 IST
- **Day / phase / part:** Day 0 complete → Day 1 (Phase A), not started
- **Currently doing:** nothing in progress; Day 0.3 (D-034, skills, continuity setup) awaits the author's review and commit
- **Next step:** `/risk-check "Day 1: Acme sandbox"`, then Day 1 part (1) per the Day 1 prompt in `SETUP.md`
- **RESUME PROMPT:**
  ```
  Read CLAUDE.md and docs/progress.md, then docs/acme-spec.md. Run /risk-check "Day 1: Acme sandbox"
  and wait for my confirmation. Then build Day 1 following the Day 1 prompt in SETUP.md, one numbered
  part at a time, and run /checkpoint at the end of each part. Do not commit or push.
  ```

## Done log

| Date | Day.part | What was built | Files | Tests | Commit |
| --- | --- | --- | --- | --- | --- |
| 2026-10-05 | 0.1 | Project brief, docs, git guardrails | `CLAUDE.md`, `docs/*`, `SETUP.md`, `.githooks/*`, `scripts/check_attribution.py`, `.claude/*`, `.env.example`, `.gitignore` | n/a (docs) | c430059 |
| 2026-10-05 | 0.2 | Applied the 29 review decisions (D-001–D-029) to the docs | `CLAUDE.md`, `docs/acme-spec.md`, `docs/failure-register.md`, `docs/model-plan.md`, `docs/risk-log.md`, `docs/research-notes.md`, `SETUP.md`, `.env.example`, `.claude/settings.json` | n/a (docs) | 1b1ef0b |
| 2026-10-05 | 0.3 | N.11 decision (D-034); project skills (add-task, explain, day-review, ship-check, checkpoint, resume); continuity (progress, decisions log, SessionStart hook) | `docs/acme-spec.md`, `docs/risk-log.md`, `docs/decisions.md`, `docs/progress.md`, `CLAUDE.md`, `.claude/skills/*/SKILL.md`, `.claude/hooks/session-context.sh`, `.claude/settings.json` | Hook output test: pass | pending |

## Blockers and open questions

- Interpretations made in the Oct 5 decisions pass, not yet explicitly confirmed by the author:
  - The agent (not Acme) creates the business approval request via `POST /api/approvals` for over-limit
    invoices and payment requests.
  - T6 `expected_outcome` is `completed` (security finding in the report, not an exception).
  - T7 Patel total set to ₹41,300 (below limit).
  - "8 core tasks" = T1–T8; T9 runs outside the pass^3 matrix.
  - `.env.example`: Groq qwen ID replaced by `GROQ_COMPACTION_MODEL=openai/gpt-oss-20b`.
  - Payment requests in `cancelled` or `rejected` state do not block voiding an approved invoice (D-034).

## Deviations from spec

None yet. (Record here any place where the built code differs from `docs/acme-spec.md` or `CLAUDE.md`,
with the reason, and add a decision row in `docs/decisions.md`.)
