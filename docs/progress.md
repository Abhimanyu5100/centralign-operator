# Progress

The single source of truth for where the project is. Updated by `/checkpoint` at the end of every part.
If this file disagrees with git, git wins for what is committed.

## Now

- **Last updated:** 2026-10-06 02:52 IST
- **Day / phase / part:** Day 1 (Phase A), part 8 done (not yet committed) → part 9 next
- **Currently doing:** waiting for author review of Day 1.8 (admin endpoints, ORG-002 in Acme, segment-aware path globs)
- **Next step:** Day 1 part 9, the five Day 1 chaos profiles wired into `_write` and the UI (`rename_submit_button`,
  `session_expiry_at_step_N`, `flaky_500`, `commit_then_timeout`, `silent_drop_write`), reading the profile that
  `/__admin/chaos` now stores (`acme/chaos.py`). Then part 10: task YAMLs T1-T9 with frozen `now`, SQL checkers and
  checker tests.
- **Carried over:**
  - **Part 9:** one effect test per profile, plus an inventory test that fails if a profile in `chaos.PROFILES` (or the
    `session_expiry_at_step_N` pattern) has no effect test; add each name to `chaos.WIRED_PROFILES` when built (N.98).
  - **Day 2:** (D-085) a test that no agent tool touches the database and the code tool's sandbox cannot reach
    `acme/data` (ORG-004's database half, N.82b); and a test that the agent's tool environment has no
    `ACME_ADMIN_TOKEN` (N.92).
  - **Day 3 gate:** the evaluator must call `agent/policy/pathglob.path_matches` for `request_matches` (D-088, D-092),
    collect every matching rule, apply the strictest effect and log every matching policy ID (D-087); ORG-004 must
    catch `//__admin/reset`, `/api/../__admin/reset`, `/%5F%5Fadmin/reset`, `/__ADMIN/reset`, `/__admin/reset?x=1`.
  - **Day 3 adversarial:** `t6_bad_transfer` expects Acme's 422 plus the scanner finding, not a gate deny (D-086).
  - Day 3: the ORG-005 gate reads `acme/knowledge/mail_allowlist.yaml` (D-064) and a negative test shows an
    allowlisted recipient needs no action approval (D-069).
  - Day 3: a no-SOP request proving the approve-every-write fallback (1.3, D-081).
  - Day 3: the general provenance rule ORG-007 (`field_source_untrusted`).
  - Day 3: the evaluator reads the allowlist with `PolicyFile.allowlist(name)`, never from disk (D-082).
  - Day 2: if a `tool_in` rule is ever added, add the registry-name test with it (N.77).
  - `iyer_INV-3301.pdf` stays unreferenced by T1-T9 (Phase B stretch).
- **RESUME PROMPT:**
  ```
  Read CLAUDE.md and docs/progress.md, then docs/acme-spec.md. Day 1 parts 1 to 8 are done (service layer
  in acme/services.py; login in acme/auth.py; web plumbing and the admin token rule in acme/web.py; UI in
  acme/ui.py; JSON API in acme/api.py; idempotency in acme/idempotency.py; reads in acme/queries.py; mailbox in
  acme/mail.py; PDFs via acme/pdfs.py; admin endpoints in acme/admin.py; chaos registry and stored profile in
  acme/chaos.py (nothing consumes it yet); knowledge in acme/knowledge/; policy schema, strict loader and the
  path-glob matcher in agent/policy/; `make test` is the fast suite). Build Day 1 part 9: wire the five Day 1
  chaos profiles into Acme (rename_submit_button, session_expiry_at_step_N, flaky_500, commit_then_timeout,
  silent_drop_write), set through POST /__admin/chaos (needs ACME_ADMIN_TOKEN), add each to chaos.WIRED_PROFILES,
  with one effect test per profile and an inventory test. Part 10 (task YAMLs T1-T9, SQL checkers, checker tests)
  follows. Show the risk table first, stop after the part, and run /checkpoint. Do not commit or push.
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
| 2026-10-06 | 1.4 | JSON API: reads incl. by-id read-back routes, writes through one `_write` helper (strict JSON bodies, 415 for non-JSON, `Idempotency-Key` on invoices/payments via the shared store with replay header), approval requests and decisions, undo endpoints, `GET /api/audit?since=` with paging; fixed `ERROR_TYPES` list incl. `server_error`, typed 404/405/422/500 under `/api/`; shared filter validation; UI/API parity and concurrent-write tests (carried over from 1.3); decisions D-058 to D-063; risks N.50 to N.55 added and tested, N.21 and N.25 tested | `acme/api.py`, `acme/{app,web,services,idempotency,queries,ui}.py`, `tests/acme/{test_api,conftest,test_ui}.py`, `docs/{acme-spec,decisions,risk-log,progress}.md` | `make test`: 276 passed, 0 failed (`make test-e2e`: none collected); API tests mutation-checked (6 mutants caught); race tests stable over 6 repeats; curl walk against `make acme` verified | 5320b80 |
| 2026-10-06 | 1.5 | Mailbox: allowlist in `acme/knowledge/mail_allowlist.yaml` (single source for the `external` flag and the Day 3 ORG-005 check, fails closed); `acme/mail.py`; `services.send_mail` (computed `external`, session sender, audited, no undo); seed inbox from 9 JSON files (6 task invoices + 2 older, HR offer email without start date); `GET /api/mail`, `GET /api/mail/{id}`, `POST /api/mail/send` (idempotency key); `/mail`, `/mail/{id}`, `/mail/compose` pages; decisions D-064 to D-069; risks N.56 to N.64 tested | `acme/{mail,models,permissions,services,queries,api,ui,seed}.py`, `acme/knowledge/mail_allowlist.yaml`, `acme/data/inbox/*.json`, `acme/templates/{mails,mail,mail_form,base}.html`, `tests/acme/{test_mail,test_ui,test_api,test_services}.py`, `docs/*` | `make test`: 381 passed, 0 failed (`make test-e2e`: none collected); curl walk against a live server verified | e75d3b2 |
| 2026-10-06 | 1.6 | Generated PDFs (13: seeded history, the six task invoices, one scanned) from one fact table in `acme/seed.py`, byte-identical reportlab invariant output, committed with `MANIFEST.sha256`; `acme/files.py` and four download routes; UI-only attach-source action; `send_mail` refuses missing attachments; duplicate check before date rules; decisions D-070 to D-076; risks N.65 to N.70 tested | `acme/{pdfs,files,seed,services,permissions,web,ui,api}.py`, `acme/templates/{invoice,mail}.html`, `acme/data/files/*`, `Makefile`, `tests/acme/test_pdfs.py`, `docs/*` | `make test`: 473 passed, 0 failed (91 new); mutation check on the file listing failed the symlink test as expected; curl against a live server: 200 pdf, traversal 404 | 8debb73 |
| 2026-10-06 | 1.7 | Company knowledge: four SOPs (process-invoice, onboard-employee, schedule-payment, notify-vendor) with stable step IDs and a documented format; `policies.yaml` ORG-001 to ORG-006 (DRAFT, schema v0); policy schema and strict loader in `agent/policy/` (six condition types incl. `request_matches`, five `acme_check` kinds, deny/require_approval only); SOP parser as the planner contract; ORG-006 pinned inside Acme (no payment amount, payee or bank field, no bank route); register 1.3 and acme-spec updated | `acme/knowledge/sops/*`, `acme/knowledge/policies.yaml`, `acme/mail.py` (one word: `fullmatch`), `agent/__init__.py`, `agent/policy/{__init__,models,loader}.py`, `tests/policy/*` (incl. `test_loader.py`), `tests/acme/{sop_format,test_knowledge,test_payment_amount}.py`, `docs/{acme-spec,decisions,failure-register,risk-log,progress}.md` | `make test`: 712 passed (new: 167 in `tests/policy`, 63 in `test_knowledge.py`, 9 in `test_payment_amount.py`); mutation-checked (wrong limit, widened role set, wrong model fields, missing allowlist, planted vendor leak, bad route, bad policy ID, duplicate step ID, and ten loader mutations all fail); review fixes D-082 and D-083 included | 077edb2 |
| 2026-10-06 | 1.8 | Admin endpoints behind `X-Admin-Token` (one check in `require_login` for the whole `/__admin` prefix; unset env closes them): reset (seed, now), snapshot, state_hash, diff (row-level, id order, entity tables only), chaos get/set with a stored profile and `wired` flag; snapshots and chaos tables dropped by reset; ORG-002 inside Acme for payments (create refuses, approve refuses, reject allowed); segment-aware `agent/policy/pathglob.py` with path normalisation (decode once, collapse slashes, reject `.`/`..`, case-insensitive, invalid path fails closed) and the policy rules rewritten to it; masking fix (last four digits only above eight digits); typed JSON errors on `/__admin`; decisions D-084 to D-093; risks N.82 and N.83 closed, N.90 to N.101 added | `acme/{admin,chaos,web,app,db,services}.py`, `agent/policy/{pathglob,models}.py`, `acme/knowledge/policies.yaml`, `.env.example`, `Makefile`, `tests/acme/{test_admin,test_org002_payments,test_auth}.py`, `tests/policy/{test_pathglob,acme_checks,test_policies_file,test_schema}.py`, `docs/{acme-spec,decisions,risk-log,progress}.md` | `make test`: 891 passed, 0 failed (179 new: 70 admin, 13 ORG-002, 96 pathglob); ten mutations (token guard, prefix guard, both ORG-002 checks, mask, snapshot ids, drop of the new tables, three matcher changes) all killed; curl walk against a live server verified; seed hashes and MANIFEST.sha256 unchanged | pending |

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

- **Author to confirm (part 8):** rejecting a payment whose vendor is no longer approved is still allowed; only
  approving is refused (D-091). A 409 `conflict` with `ORG-002` in the detail is used for the refusal because
  `ERROR_TYPES` is frozen (D-058); the Day 2 classifier must key off the policy ID.
- **Starting the server for the harness:** `export ACME_ADMIN_TOKEN=...` before `make acme`; unset means every
  admin route is 403.

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

Day 1.5 (decisions D-064 to D-069):

- **Allowlist file:** `acme/knowledge/mail_allowlist.yaml` (`internal_domain`, `partner_domains`); spec said only "allowlisted partner domains" (D-064).
- **Mail lists omit `body`**; `GET /api/mail` defaults to the inbox (D-067).
- **`POST /api/mail/send` needs an `Idempotency-Key`** (the spec's key list named only invoices and payments) (D-066).
- **Mail pages:** `/mail?folder=outbox` shows sent mail; the detail page lists attachment filenames as text, with no download link until part 6.
- **Seed mail:** 9 messages (spec: "the invoice emails the tasks need"): added older Sharma INV-1012 (so "latest" is meaningful) and Patel INV-5480.
- **Length limits** on subject (200) and body (5000) are worded by the form in its own way; the status code matches the API.
- `acme/data/inbox/*.json` and `acme/knowledge/` are now tracked directories (the DB file stays ignored).

Day 1.6 (awaiting author review):

- **Generator path:** `acme/pdfs.py`, not `scripts/make_pdfs.py` (D-070).
- **Scanned PDF** is written by hand (no reportlab) so its bytes cannot vary with library versions (D-073). The vendor is "Iyer Electricals" (the seed name), not "Iyer Components".
- **Spec table `scanned_INV-3301.pdf`** is now named `iyer_INV-3301.pdf` to match the other files.
- **Duplicate check now runs before the date rules** in `submit_invoice` (D-074).
- **`send_mail` now refuses attachments that are not generated files** (D-075).
- **Base seed unchanged:** no mail or invoice rows were added; the scanned invoice has no email.

Day 1.7 (decisions D-077 to D-081; awaiting author review):

- **Spec said ORG-006 is `runtime`**; the author moved it to `acme` (D-079). Acme already rejected an amount, payee
  or bank field on a payment request (`PaymentIn` forbids unknown fields), so no new validation was added, only tests.
- **Rules match HTTP requests** (`request_matches`) instead of tool names (D-077); `tool_in` stays in the schema.
- **Four SOPs, not three** (`notify-vendor` added), so register row 1.3's proof changed (D-081).
- **`agent/` now exists** (policy models and loader only, no evaluator, no LLM code). It reads `acme/knowledge/`
  and nothing from `bench/`.
- **ORG-002 covers invoice entry only** in YAML; payments, ORG-004's database half and the `t6_bad_transfer`
  gate expectation are open in N.82 for the Day 3 design.
- **Loader hardening after the author's review (D-082):** symlinked allowlists refused; allowlist domains validated with Acme's
  pattern and kept on the policy (`PolicyFile.allowlist`); every read or parse failure is a `PolicyError`;
  `schema_version` must be the plain integer 0. The review had wrongly said `false` was rejected (N.84).
- **`acme/mail.py` touched in part 7:** the allowlist domain check uses `fullmatch` (D-083, N.88). A symlinked
  `acme/knowledge/` is accepted on purpose (N.89).

Day 1.8 (decisions D-084 to D-093; awaiting author review):

- **Admin routes accept a token, not a session** (`X-Admin-Token`), one rule in `require_login` for the `/__admin`
  prefix (D-089). The spec did not say how the token is sent.
- **Admin responses use the API shape and error types** (D-089); the diff reports only changed tables, and `meta`
  rows are excluded, with `now` reported top-level (D-090). The spec said "row-level before/after per table".
- **Snapshots and chaos are tables dropped by reset**, so reset clears the chaos profile (D-090).
- **Chaos profile `wired` flag:** the set response says `wired: false` until part 9 (N.98).
- **ORG-002 reaches payments in Acme**, both on creation and on approval; the policy file keeps ORG-002 as one
  `runtime` rule and the spec table says so (D-091). Spec said ORG-002 is a runtime rule only.
- **Path globs changed meaning** (D-088, D-092): `*` no longer crosses `/`; rules ORG-001, 003, 004 and 006 and the
  `no_route` checks were rewritten (`/__admin/**`, `/**/*bank*/**`); a malformed glob is now a load error; matching
  is case-insensitive for every rule; an invalid path matches every glob.
- **`t6_bad_transfer` expectation changed** in the spec table: Acme's 422 plus the scanner finding (D-086).
- **`_mask_account` changed** (D-093): short numbers are fully hidden.
- **No `create_payment_request`**: the check lives in `services.create_payment` (the function's real name).
