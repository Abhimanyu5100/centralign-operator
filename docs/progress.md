# Progress

The single source of truth for where the project is. Updated by `/checkpoint` at the end of every part.
If this file disagrees with git, git wins for what is committed.

## Now

- **Last updated:** 2026-10-06 01:00 IST
- **Day / phase / part:** Day 1 (Phase A), part 4 done (not yet committed) → part 5 next
- **Currently doing:** waiting for author review of Day 1.4
- **Next step:** Day 1 part (5): mailbox, including the HR offer email: seeded `acme/data/inbox/*.json`,
  `GET /api/mail?folder=`, `POST /api/mail/send` (external recipients flagged), and the carried-over `/mail`,
  `/mail/{id}`, `/mail/compose` pages with their tests. Mail writes go through `api._write` and the service
  layer; error types only from `web.ERROR_TYPES`
- **Carried over:** `/mail*` pages and mail API to part 5; PDF attach action to part 6; each with their tests (D-056).
- **RESUME PROMPT:**
  ```
  Read CLAUDE.md and docs/progress.md, then docs/acme-spec.md. Day 1 parts 1 to 4 are done (service layer
  in acme/services.py; login in acme/auth.py; web plumbing and the fixed ERROR_TYPES list in acme/web.py; UI
  in acme/ui.py; JSON API in acme/api.py with every write through `_write`; shared idempotency store in
  acme/idempotency.py; reads in acme/queries.py; `make acme` serves Acme, `make test` is the fast suite).
  Build Day 1 part (5): mailbox including the HR offer email, the mail API and the carried-over /mail*
  pages, per the Day 1 prompt in SETUP.md. Show the risk table first, stop after the part, and run
  /checkpoint. Do not commit or push.
  ```

## Done log

| Date | Day.part | What was built | Files | Tests | Commit |
| --- | --- | --- | --- | --- | --- |
| 2026-10-05 | 0.1 | Project brief, docs, git guardrails | `CLAUDE.md`, `docs/*`, `SETUP.md`, `.githooks/*`, `scripts/check_attribution.py`, `.claude/*`, `.env.example`, `.gitignore` | n/a (docs) | c430059 |
| 2026-10-05 | 0.2 | Applied the 29 review decisions (D-001–D-029) to the docs | `CLAUDE.md`, `docs/acme-spec.md`, `docs/failure-register.md`, `docs/model-plan.md`, `docs/risk-log.md`, `docs/research-notes.md`, `SETUP.md`, `.env.example`, `.claude/settings.json` | n/a (docs) | 1b1ef0b |
| 2026-10-05 | 0.3 | N.11 decision (D-034); project skills (add-task, explain, day-review, ship-check, checkpoint, resume); continuity (progress, decisions log, SessionStart hook) | `docs/acme-spec.md`, `docs/risk-log.md`, `docs/decisions.md`, `docs/progress.md`, `CLAUDE.md`, `.claude/skills/*/SKILL.md`, `.claude/hooks/session-context.sh`, `.claude/settings.json` | Hook output test: pass | 2bb1c8d |
| 2026-10-05 | 0.4 | Checkpoint skill syncs the Done log with git before updating progress | `.claude/skills/checkpoint/SKILL.md`, `docs/progress.md` | n/a (docs) | 2516246 |
| 2026-10-05 | 1.1 | Python 3.12 project (uv); Acme data model, logical clock, permission map, input models, service layer with audit log and business rules (auto-approval, approvals, payments, undo paths), seed (base/t8/t9) and reset with frozen `now`, `make reset`/`make test` | `pyproject.toml`, `uv.lock`, `.python-version`, `Makefile`, `.gitignore`, `acme/{db,clock,permissions,models,services,seed}.py`, `tests/acme/*` | 72 passed, 0 failed | 7d4abb6 |
| 2026-10-05 | 1.2 | Login and roles: users and roles in code with env passwords (D-043), cookie sessions (8 h wall-clock TTL, per-session request count, revoke), `POST /api/login` shared by form and JSON, logout, whoami, login and home pages, app-wide login guard with typed 401 (API) / 303 (UI), sessions outside the state hash and wiped by reset; Testing section in CLAUDE.md, `make test` (fast) vs `make test-e2e`, `e2e` marker with a static marker check; decisions D-043 to D-051; register rows 0.10, 0.11 | `acme/{auth,app}.py`, `acme/templates/{login,home}.html`, `acme/{db,permissions}.py`, `tests/acme/test_auth.py`, `tests/test_markers.py`, `Makefile`, `pyproject.toml`, `CLAUDE.md`, `.env.example`, `docs/*` | `make test`: 114 passed, 0 failed (`make test-e2e`: none collected) | 1ab7b52 |
| 2026-10-06 | 1.3 | UI pages and forms with server-side validation: invoices, approvals (detail page holds Approve/Reject/Withdraw), payments, vendors (read-only), employees, IT tickets; inline per-field errors, PRG with one-shot toast; shared idempotency store (UI token now, API key in part 4); exact rupee parsing; `acme/web.py` split; `make acme`; route-protection test now walks the OpenAPI schema (N.49); decisions D-052 to D-057; risks N.42 to N.49 tested | `acme/{web,ui,forms,money,idempotency,queries}.py`, `acme/{app,db}.py`, `acme/templates/*`, `Makefile`, `tests/acme/{test_ui,test_money_and_forms,test_idempotency,htmlutil}.py`, `tests/acme/test_auth.py`, `docs/*` | `make test`: 213 passed, 0 failed (`make test-e2e`: none collected); UI tests mutation-checked | 313dec3 |
| 2026-10-06 | 1.4 | JSON API: reads incl. by-id read-back routes, writes through one `_write` helper (strict JSON bodies, 415 for non-JSON, `Idempotency-Key` on invoices/payments via the shared store with replay header), approval requests and decisions, undo endpoints, `GET /api/audit?since=` with paging; fixed `ERROR_TYPES` list incl. `server_error`, typed 404/405/422/500 under `/api/`; shared filter validation; UI/API parity and concurrent-write tests (carried over from 1.3); decisions D-058 to D-063; risks N.50 to N.55 added and tested, N.21 and N.25 tested | `acme/api.py`, `acme/{app,web,services,idempotency,queries,ui}.py`, `tests/acme/{test_api,conftest,test_ui}.py`, `docs/{acme-spec,decisions,risk-log,progress}.md` | `make test`: 276 passed, 0 failed (`make test-e2e`: none collected); API tests mutation-checked (6 mutants caught); race tests stable over 6 repeats; curl walk against `make acme` verified | pending |

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

Day 1.3 (decisions D-052 to D-057):

- **Approve, Reject and Withdraw are on `/approvals/{id}`**, not on the list (spec put them on the list), so
  role+name locators stay unique (N.26, D-053). The list rows link to the detail page.
- **`/mail*` pages and the PDF attach action are not built** (carried over to parts 5 and 6, D-056).
- **Extra routes:** `POST /logout` (UI logout with a redirect), `POST /invoices/{id}/request-approval` and
  `POST /payments/{id}/request-approval` (the UI way to create a business approval request), and
  `POST /approvals/{id}/decide|withdraw`. All writes are POST with a 303 redirect.
- **UI forms use rupees as plain decimals** (D-055) and `novalidate`, so the server's messages are shown (D-057).
- **Idempotency store built in part 3**, not part 4 (D-054); part 4 must reuse it.
- **`app.py` split**: login guard, connection and templates moved to `acme/web.py` (D-052).
- **Error handling:** `AcmeError` and malformed-URL errors share one handler: typed JSON for `/api/`, an error
  page for the UI.

Day 1.4 (decisions D-058 to D-063):

- **Extra read routes:** `GET /api/{vendors,approvals,payments,employees,it-tickets}/{id}`; `GET /api/invoices/{id}`
  embeds `vendor_name`, `approvals`, `payments` (D-063).
- **Audit paging:** `limit` (default 500, max 1000), `has_more`, `next_since`; the spec named only `since` (D-063).
- **Strict bodies and 415** for API writes; a body `actor` is 422, not ignored (D-059, D-061).
- **Filters by id only** (D-060).
- **Error responses** now always carry `data` (`{}` or `{"field": ...}`); part 2's login errors gained the key too.
- **Mail endpoints** (`GET /api/mail`, `POST /api/mail/send`) are not built; part 5.
