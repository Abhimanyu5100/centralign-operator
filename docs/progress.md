# Progress

The single source of truth for where the project is. Updated by `/checkpoint` at the end of every part.
If this file disagrees with git, git wins for what is committed.

## Now

- **Last updated:** 2026-10-05 21:32 IST
- **Day / phase / part:** Day 1 (Phase A), part 1 done (not yet committed) → part 2 next
- **Currently doing:** waiting for author review of Day 1.1
- **Next step:** Day 1 part (2): login and roles (users with passwords, cookie sessions with configurable
  expiry, `POST /api/login` shared by UI and API per D-037, sessions cleared on reset)
- **RESUME PROMPT:**
  ```
  Read CLAUDE.md and docs/progress.md, then docs/acme-spec.md. Day 1 part 1 is done (acme/db.py,
  clock.py, permissions.py, models.py, services.py, seed.py). Build Day 1 part (2): login and roles,
  per the Day 1 prompt in SETUP.md and decision D-037. Show the risk table first, stop after the part,
  and run /checkpoint. Do not commit or push.
  ```

## Done log

| Date | Day.part | What was built | Files | Tests | Commit |
| --- | --- | --- | --- | --- | --- |
| 2026-10-05 | 0.1 | Project brief, docs, git guardrails | `CLAUDE.md`, `docs/*`, `SETUP.md`, `.githooks/*`, `scripts/check_attribution.py`, `.claude/*`, `.env.example`, `.gitignore` | n/a (docs) | c430059 |
| 2026-10-05 | 0.2 | Applied the 29 review decisions (D-001–D-029) to the docs | `CLAUDE.md`, `docs/acme-spec.md`, `docs/failure-register.md`, `docs/model-plan.md`, `docs/risk-log.md`, `docs/research-notes.md`, `SETUP.md`, `.env.example`, `.claude/settings.json` | n/a (docs) | 1b1ef0b |
| 2026-10-05 | 0.3 | N.11 decision (D-034); project skills (add-task, explain, day-review, ship-check, checkpoint, resume); continuity (progress, decisions log, SessionStart hook) | `docs/acme-spec.md`, `docs/risk-log.md`, `docs/decisions.md`, `docs/progress.md`, `CLAUDE.md`, `.claude/skills/*/SKILL.md`, `.claude/hooks/session-context.sh`, `.claude/settings.json` | Hook output test: pass | 2bb1c8d |
| 2026-10-05 | 1.1 | Python 3.12 project (uv); Acme data model, logical clock, permission map, input models, service layer with audit log and business rules (auto-approval, approvals, payments, undo paths), seed (base/t8/t9) and reset with frozen `now`, `make reset`/`make test` | `pyproject.toml`, `uv.lock`, `.python-version`, `Makefile`, `.gitignore`, `acme/{db,clock,permissions,models,services,seed}.py`, `tests/acme/*` | 72 passed, 0 failed | pending |

## Blockers and open questions

- Interpretations made in the Oct 5 decisions pass, not yet explicitly confirmed by the author:
  - The agent (not Acme) creates the business approval request via `POST /api/approvals` for over-limit
    invoices and payment requests.
  - T6 `expected_outcome` is `completed` (security finding in the report, not an exception).
  - T7 Patel total set to ₹41,300 (below limit).
  - "8 core tasks" = T1–T8; T9 runs outside the pass^3 matrix.
  - `.env.example`: Groq qwen ID replaced by `GROQ_COMPACTION_MODEL=openai/gpt-oss-20b`.
  - Payment requests in `cancelled` or `rejected` state do not block voiding an approved invoice (D-034).
- Day 1.1 additions beyond the spec (see Deviations): confirm or reject each at review; confirmed ones
  get a decision row.
- Done log has no row for commit 2516246 ("Day 0.4: checkpoint syncs Done log with git"); git wins.

## Deviations from spec

(Record here any place where the built code differs from `docs/acme-spec.md` or `CLAUDE.md`,
with the reason, and add a decision row in `docs/decisions.md`.)

Day 1.1 (pending author confirmation):

- **One active payment request per invoice.** `create_payment` returns 409 if a `pending_approval`,
  `scheduled` or `sent` request exists. Not in the spec; prevents a double payment. Read-before-retry is
  still exercised on approvals and IT tickets (3.5, D-008).
- **Extra validations:** invoice date not in the future; received date not in the future; tax ≤ total;
  employee email must be `@acme.example`; manager must be an active employee; start date not in the
  past; duplicate employee email (non-cancelled) is 409; payment date not in the past.
- **Requester cannot decide their own approval** (403), in addition to the role check.
- **`audit_log.reason` column** added (spec lists none) to hold e.g. "ORG-001 below limit".
- **`mail.from_addr` / `mail.to_addr`** instead of `from` / `to` (SQL keywords).
- **`vendors.version`** added for consistency; admin-only `update_vendor_bank` and `set_status`
  (harness marks payments `sent`, invoices `paid`).
- **Seed names** are `base`, `t8`, `t9` (task YAML `seed` field). Base includes the T4 near-duplicates
  and history rows (no audit rows); t8/t9 overlays run through the service layer the day before `now`.
- **Write timestamps** follow D-035: first write after reset is stamped exactly `now`, then +1 s each.
