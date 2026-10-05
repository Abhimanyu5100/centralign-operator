# Progress

The single source of truth for where the project is. Updated by `/checkpoint` at the end of every part.
If this file disagrees with git, git wins for what is committed.

## Now

- **Last updated:** 2026-10-05 22:00 IST
- **Day / phase / part:** Day 1 (Phase A), part 2 done (not yet committed) → part 3 next
- **Currently doing:** waiting for author review of Day 1.2
- **Next step:** Day 1 part (3): UI pages and forms with server-side validation (`/invoices`, `/invoices/new`,
  invoice detail, approvals, payments, employees, IT tickets, mailbox), calling the service layer, with
  the `rename_submit_button` hook in mind and accessible names that are unique (N.26)
- **RESUME PROMPT:**
  ```
  Read CLAUDE.md and docs/progress.md, then docs/acme-spec.md. Day 1 parts 1 and 2 are done (service
  layer in acme/services.py; login, sessions and the app shell in acme/auth.py and acme/app.py; `make
  test` is the fast suite). Build Day 1 part (3): UI pages and forms with server-side validation, per the
  Day 1 prompt in SETUP.md. Show the risk table first, stop after the part, and run /checkpoint. Do not
  commit or push.
  ```

## Done log

| Date | Day.part | What was built | Files | Tests | Commit |
| --- | --- | --- | --- | --- | --- |
| 2026-10-05 | 0.1 | Project brief, docs, git guardrails | `CLAUDE.md`, `docs/*`, `SETUP.md`, `.githooks/*`, `scripts/check_attribution.py`, `.claude/*`, `.env.example`, `.gitignore` | n/a (docs) | c430059 |
| 2026-10-05 | 0.2 | Applied the 29 review decisions (D-001–D-029) to the docs | `CLAUDE.md`, `docs/acme-spec.md`, `docs/failure-register.md`, `docs/model-plan.md`, `docs/risk-log.md`, `docs/research-notes.md`, `SETUP.md`, `.env.example`, `.claude/settings.json` | n/a (docs) | 1b1ef0b |
| 2026-10-05 | 0.3 | N.11 decision (D-034); project skills (add-task, explain, day-review, ship-check, checkpoint, resume); continuity (progress, decisions log, SessionStart hook) | `docs/acme-spec.md`, `docs/risk-log.md`, `docs/decisions.md`, `docs/progress.md`, `CLAUDE.md`, `.claude/skills/*/SKILL.md`, `.claude/hooks/session-context.sh`, `.claude/settings.json` | Hook output test: pass | 2bb1c8d |
| 2026-10-05 | 0.4 | Checkpoint skill syncs the Done log with git before updating progress | `.claude/skills/checkpoint/SKILL.md`, `docs/progress.md` | n/a (docs) | 2516246 |
| 2026-10-05 | 1.1 | Python 3.12 project (uv); Acme data model, logical clock, permission map, input models, service layer with audit log and business rules (auto-approval, approvals, payments, undo paths), seed (base/t8/t9) and reset with frozen `now`, `make reset`/`make test` | `pyproject.toml`, `uv.lock`, `.python-version`, `Makefile`, `.gitignore`, `acme/{db,clock,permissions,models,services,seed}.py`, `tests/acme/*` | 72 passed, 0 failed | 7d4abb6 |
| 2026-10-05 | 1.2 | Login and roles: users and roles in code with env passwords (D-043), cookie sessions (8 h wall-clock TTL, per-session request count, revoke), `POST /api/login` shared by form and JSON, logout, whoami, login and home pages, app-wide login guard with typed 401 (API) / 303 (UI), sessions outside the state hash and wiped by reset; Testing section in CLAUDE.md, `make test` (fast) vs `make test-e2e`, `e2e` marker with a static marker check; decisions D-043 to D-051; register rows 0.10, 0.11 | `acme/{auth,app}.py`, `acme/templates/{login,home}.html`, `acme/{db,permissions}.py`, `tests/acme/test_auth.py`, `tests/test_markers.py`, `Makefile`, `pyproject.toml`, `CLAUDE.md`, `.env.example`, `docs/*` | `make test`: 114 passed, 0 failed (`make test-e2e`: none collected) | pending |

## Blockers and open questions

- Interpretations made in the Oct 5 decisions pass, not yet explicitly confirmed by the author:
  - The agent (not Acme) creates the business approval request via `POST /api/approvals` for over-limit
    invoices and payment requests.
  - T6 `expected_outcome` is `completed` (security finding in the report, not an exception).
  - T7 Patel total set to ₹41,300 (below limit).
  - "8 core tasks" = T1–T8; T9 runs outside the pass^3 matrix.
  - `.env.example`: Groq qwen ID replaced by `GROQ_COMPACTION_MODEL=openai/gpt-oss-20b`.
  - Payment requests in `cancelled` or `rejected` state do not block voiding an approved invoice (D-034).
- The `TestClient` import prints a Starlette deprecation warning about `httpx` (it wants `httpx2`).
  Harmless for now; revisit if it becomes an error on a Starlette upgrade.
- Dev-only default passwords live in `acme/auth.py` (overridable by env); fine for the sandbox, to be
  listed in the README limitations with CSRF and the missing `Secure` flag (D-046).

## Deviations from spec

(Record here any place where the built code differs from `docs/acme-spec.md` or `CLAUDE.md`,
with the reason, and add a decision row in `docs/decisions.md`.)

Day 1.1 (accepted by the author on 2026-10-05; decisions D-047 to D-051 and D-035):

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

Day 1.2:

- **Extra routes beyond the spec's login:** `GET /healthz` (Docker health check later), `POST /api/logout`,
  `GET /api/whoami`, and a placeholder home page `GET /` that part 3 replaces.
- **`sessions` table** is outside `ENTITY_TABLES` on purpose, so logins never change `state_hash` or the
  diff, and it is dropped by reset (N.32). No users table (D-043).
- **Session errors are typed** (`login_required`, `session_expired`, `invalid_credentials`) so the Day 2
  expiry detector can tell "never logged in" from "expired" (3.4).
- **CSRF and the `Secure` flag are not built** (D-046; register rows 0.10, 0.11).
