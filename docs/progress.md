# Progress

The single source of truth for where the project is. Updated by `/checkpoint` at the end of every part.
If this file disagrees with git, git wins for what is committed.

## Now

- **Last updated:** 2026-10-06 15:34 IST
- **Day / phase / part:** Day 2 (Phase A), part 2 (API, mail and file tools, normalisers, retries, undo, rollback,
  scripted agent, oracles T1-T9, `make oracle`) built, not yet committed → Day 2 part 3 next
- **Currently doing:** Day 2.2 awaits author review and commit. The author's manual browser walk of T1-T9 (Day 1
  definition of done; limits under "Manual walk" in Blockers) is still pending
- **Day 2 split (author, Oct 6, revised):** 2.1 registry, pass-through gate, run store, isolation tests (done);
  2.2 API/mail/file tools from the endpoint catalog, normalisers, idempotency keys, read-before-retry, undo tools,
  run lifecycle and rollback, scripted agent, oracles T1-T9, `make oracle`; 2.3 Playwright browser tool,
  session-expiry detector, T1 oracle through the GUI, close Day 2.
- **Next step:** Day 2 part 3: the Playwright browser tool (pruned a11y view, role + accessible-name locators, no
  Acme selectors in `agent/`), the session-expiry detector for the UI (303 to `/login?next=`), the T1 oracle through
  the GUI channel, then close Day 2 (Day 2 definition of done: invoice oracle end to end through the registry and the
  pass-through gate; rollback restores net entity state).
- **Carried over:**
  - **Day 2.3:** the browser is the first subprocess in `agent/`: launch it with an explicit allowlisted env (D-105),
    add the launcher to the `subprocess` scan's allowlist in `tests/agent/test_agent_isolation.py` with a test that
    `ACME_ADMIN_TOKEN` is absent from the child env (N.92). Decide how GUI writes expose `ToolCall.request` (N.126);
    cap stored `tool_result` payloads with a `truncated` flag once a11y sizes are measured (N.127; PDF text already
    lands whole in `tool_result`). UI writes need their own read-before-retry: the catalog's `read_back` entries are
    API reads and can serve the GUI tool too (D-108).
  - **Day 3:** the report generator must emit the provisional report contract (D-098: `status`, `questions[]`,
    `security_findings[]`, `evidence[]`, `action_approvals[]`, `side_effects[]`); add a contract test that runs the
    generator's output through `report_checks` for T4, T5, T6 and T9. Then `bench/run_oracle.py` passes the report to
    `engine.check` and the PENDING lines turn into real checks (D-112).
  - **Day 3 gate:** the T9 `approve` oracle currently sends without an action approval (pass-through gate); once
    ORG-005 is enforced, T9 runs need the scripted approver (approve / reject / none) in the approval inbox, and the
    oracle must then show the pause before the send.
  - **Day 3 harness:** call `engine.check(run, db_path, diff_tables, report)` with the `tables` object of
    `GET /__admin/diff?since=<snapshot taken right after reset and chaos set>` (done in `bench/live.py`); T9 runs as
    three run ids.
  - **Day 5:** `silent_drop_write` is UI-only; if the executor writes through the API, the T2 matrix slot moves to
    `commit_then_timeout` on T8 (approval request) (D-095).
  - **Day 2.2/2.3:** (D-085) the code tool's sandbox cannot reach `acme/data` (ORG-004's database half, N.82b; the
    static half is tested in 2.1).
  - **Day 3 gate:** action approvals match on (run_id, fingerprint), single-use, consumed when the tool runs; a
    second identical call needs a new approval (D-103). Decide whether side-effect-class defaults are YAML rules or
    code (D-101); `GATE-ERROR` is the only reserved id so far.
  - **Day 4:** `run_id` never enters LLM prompts or cassette hash keys (D-106). The derived idempotency key contains
    a hash of `run_id`; it is a transport arg, sent as a header and never shown to the LLM (D-108).
  - **Day 2.3:** the UI session-expiry detector keys off the 303 to `/login?next=` (the API half is done: 401
    `session_expired` re-logs in, D-108); `session_expiry_at_step_N` fires once per activation, so one re-login must
    recover (D-094).
  - **Day 3 harness:** read `GET /__admin/chaos/events` after each chaos run (done in `bench/live.py`: "chaos fired");
    exclude runs where it did not fire from recovery statistics and report them separately (D-095). Chaos-on bench
    runs use `flaky_500` seed 0; record the seed in the task YAML `chaos_variants`.
  - **Day 3:** the four remaining profiles (`slow_server`, `toast_2s`, `field_moved`, `delayed_write`) are
    refused with a typed 422 until built; when built, add each to `chaos.PROFILES` (removing it from
    `chaos.PLANNED`) and to `EFFECT_TESTS` in `tests/acme/test_chaos.py` (the inventory test enforces this).
  - **Day 3 gate:** the evaluator must call `agent/policy/pathglob.path_matches` for `request_matches` (D-088, D-092),
    collect every matching rule, apply the strictest effect and log every matching policy ID (D-087); ORG-004 must
    catch `//__admin/reset`, `/api/../__admin/reset`, `/%5F%5Fadmin/reset`, `/__ADMIN/reset`, `/__admin/reset?x=1`.
    API tools already give the gate `request` = the real method and filled path (D-107).
  - **Day 3 adversarial:** `t6_bad_transfer` expects Acme's 422 plus the scanner finding, not a gate deny (D-086).
    The scanner reads `extract_pdf_text` / `read_mail` data marked `provenance.source == "untrusted"` (D-110).
  - Day 3: the ORG-005 gate reads `acme/knowledge/mail_allowlist.yaml` (D-064) and a negative test shows an
    allowlisted recipient needs no action approval (D-069).
  - Day 3: a no-SOP request proving the approve-every-write fallback (1.3, D-081).
  - Day 3: the general provenance rule ORG-007 (`field_source_untrusted`).
  - Day 3: the evaluator reads the allowlist with `PolicyFile.allowlist(name)`, never from disk (D-082).
  - **Day 3:** the failure classifier recognises ORG-002 refusals (409 `conflict`) by the policy ID in the detail, not
    by `error_type` (D-091, D-100); add a classifier test with a 409 `conflict` carrying `ORG-002` (on create and on
    approve) that must classify as a policy refusal, and a plain 409 `conflict` without it that must not. A write
    result with `outcome_unknown: true` (D-108) classifies as "read back before writing again", never as a refusal.
  - `iyer_INV-3301.pdf` stays unreferenced by T1-T9 (Phase B stretch).
- **RESUME PROMPT:**
  ```
  Read CLAUDE.md and docs/progress.md, then docs/acme-spec.md. Day 1, Day 2.1 and Day 2.2 are built: Acme (acme/),
  the policy schema and pass-through gate (agent/policy/), the tool registry and run store, and in Day 2.2 the API
  tools generated from acme/knowledge/api.yaml (agent/tools/api.py: catalog validator, AcmeClient with login,
  typed errors, one retry with read-before-retry and derived idempotency keys), extract_pdf_text
  (agent/tools/files.py), normalisers (agent/normalise.py), run lifecycle and rollback (agent/lifecycle.py), the
  scripted agent (agent/scripted.py), oracles T1-T9 (bench/oracles/) and `make oracle` (bench/run_oracle.py,
  bench/live.py). Build Day 2 part 3: the Playwright browser tool with a pruned a11y view, the UI session-expiry
  detector, the T1 oracle through the GUI channel, and close Day 2. Show the risk table first, stop after the
  part, and run /checkpoint. Do not commit or push.
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
| 2026-10-06 | 1.8 | Admin endpoints behind `X-Admin-Token` (one check in `require_login` for the whole `/__admin` prefix; unset env closes them): reset (seed, now), snapshot, state_hash, diff (row-level, id order, entity tables only), chaos get/set with a stored profile and `wired` flag; snapshots and chaos tables dropped by reset; ORG-002 inside Acme for payments (create refuses, approve refuses, reject allowed); segment-aware `agent/policy/pathglob.py` with path normalisation (decode once, collapse slashes, reject `.`/`..`, case-insensitive, invalid path fails closed) and the policy rules rewritten to it; masking fix (last four digits only above eight digits); typed JSON errors on `/__admin`; decisions D-084 to D-093; risks N.82 and N.83 closed, N.90 to N.101 added | `acme/{admin,chaos,web,app,db,services}.py`, `agent/policy/{pathglob,models}.py`, `acme/knowledge/policies.yaml`, `.env.example`, `Makefile`, `tests/acme/{test_admin,test_org002_payments,test_auth}.py`, `tests/policy/{test_pathglob,acme_checks,test_policies_file,test_schema}.py`, `docs/{acme-spec,decisions,risk-log,progress}.md` | `make test`: 891 passed, 0 failed (179 new: 70 admin, 13 ORG-002, 96 pathglob); ten mutations (token guard, prefix guard, both ORG-002 checks, mask, snapshot ids, drop of the new tables, three matcher changes) all killed; curl walk against a live server verified; seed hashes and MANIFEST.sha256 unchanged | 6874984 |
| 2026-10-06 | 1.9 | The five Day 1 chaos profiles (`rename_submit_button`, `session_expiry_at_step_N`, `flaky_500`, `commit_then_timeout`, `silent_drop_write`): one module `acme/chaos.py`; API writes meet chaos in `_write`, UI writes in `ChaosRoute` (route class of the UI router), session expiry in `require_login`, the label in `invoice_submit_label`; deterministic SHA-256 schedule over attempt numbers; retry of the same attempt never faulted; once-per-activation faults; ops-agent only, admin exempt; silent drop through a `DISCARD_COMMITS` context variable honoured by `db.transaction`; `chaos_attempts` and `chaos_events` tables (dropped by reset); `GET /__admin/chaos/events` with `fired`; Day 3 profiles refused with a typed 422; decisions D-094, D-095; risks N.18, N.19, N.98, N.102 to N.108 tested | `acme/{chaos,db,api,ui,web,auth,admin}.py`, `.env.example`, `tests/acme/{test_chaos,conftest,test_admin}.py`, `docs/{acme-spec,decisions,risk-log,progress}.md` | `make test`: 924 passed, 0 failed (33 new in `test_chaos.py`); 13 mutations (drop ignored, retry dedupe, actor check x2, once-only, expiry off by one, attempts kept, events survive reset, redirect rewrite, route class, API after_write, schedule, fingerprint) all killed; curl walk against a live server verified every profile | bb43e7c |
| 2026-10-06 | 1.10 | AcmeBench tasks T1-T9 (`bench/tasks/*.yaml`, strict schema and loader in `bench/tasks.py`, T9 as three runs `T9:none/approve/reject`); one checker engine (`bench/checkers/engine.py`: read-only SQLite, exactly-one-row predicates, side effects against `allowed_changes` from the `/__admin/diff` tables, report checks over the provisional report contract); checker tests with a passing and failing states per run, a UI-built passing state and an extra-write failing state per writing run, T3 date forms, seed continuity, a real `/__admin/diff` agreement test; answer-key leak test extended to task values over `agent/` and `acme/knowledge/`; decisions D-096 to D-098 (and D-095 Day 5 note); risks N.109 to N.117 added and tested, N.4, N.13, N.28, N.29 tested | `bench/{__init__,tasks}.py`, `bench/checkers/{__init__,engine}.py`, `bench/tasks/T1-T9.yaml`, `tests/checkers/{test_engine,test_tasks}.py`, `tests/acme/test_knowledge.py`, `docs/{acme-spec,decisions,risk-log,progress}.md` | `make test`: 1062 passed, 0 failed (138 new: 67 in `test_tasks.py` incl. 50 checker cases, 57 in `test_engine.py`, 14 leak tests); 15 mutations (engine x7, task files x8) all killed | e02013e |
| 2026-10-06 | 1.R | Day 1 review fixes: register 0.5 proof path (`tests/checkers`); CLAUDE.md Commands lists `make pdfs` and marks oracle/run/bench by day; acme-spec PDF generator path and `iyer_INV-3301.pdf`; register 0.6 proof test (Acme URLs in `.env.example` are localhost, no outbound network client imported in `acme/`); T3 `decoy_has_no_new_tickets` now means no new tickets (seed count 2, any status, D-099); manual-walk limits for T6/T9 noted | `CLAUDE.md`, `docs/{acme-spec,failure-register,decisions,risk-log,progress}.md`, `tests/test_no_real_systems.py`, `bench/tasks/T3.yaml`, `tests/checkers/test_tasks.py` | `make test`: 1065 passed, 0 failed (1062 before; 3 new); mutations: `import smtplib` / `from urllib import request` in `acme/mail.py` and a non-local `ACME_URL` each fail the 0.6 test; the old T3 SQL fails the new closed-ticket case; a wrong seed literal fails every T3 good case | 332ec6b |
| 2026-10-06 | 2.1 | Tool registry with the uniform contract (`ToolSpec`: one-line description, strict args model as JSON schema, side_effect, channel, undo or no-undo reason, pre/postconditions, sensitive and transport args, `request_of`), typed `ToolResult` with the agent `ERROR_TYPES` (Acme's 12 + 8), async `registry.call` (validate as strict JSON -> gate -> preconditions -> tool; never raises; fail-closed `GATE-ERROR`; redaction of secrets in log and result; fingerprint without transport args); pass-through `PolicyGate` with the final `ToolCall` / `Decision` interface; append-only run store (`runs/runs.db`, triggers refuse UPDATE, DELETE, REPLACE, seq gaps); env allowlist config; isolation tests (bench, wall clock, environment, database/admin, acme imports, `tool_in` names); decisions D-101 to D-106; risks N.119 to N.128 added (7 tested), N.10, N.30, N.77 tested | `agent/policy/gate.py`, `agent/tools/{__init__,registry}.py`, `agent/store.py`, `agent/config.py`, `tests/agent/*`, `.env.example`, `docs/{decisions,risk-log,progress}.md` | `make test`: 1211 passed, 0 failed (146 new in `tests/agent/`); 23 mutations of gate, registry, store and config all killed | 5a3d185 |
| 2026-10-06 | 2.2 | Endpoint catalog `acme/knowledge/api.yaml` (30 tools: reads, writes, undo tools; session, API-prefix allowlist) with a load-time validator; API tools generated from it (`agent/tools/api.py`: strict args models, `request_of` = real method and path, `AcmeClient` per run with login from config, typed errors, httpx timeout -> `timeout`, one retry only after an unknown outcome or lost session, derived idempotency keys, `new_row` / `target_state` read-back, unresolved-write memory, `already_done` + `attempts`); `GET /api/files`; downloads into `runs/<run_id>/files/`, `extract_pdf_text` with a downloaded-file precondition; provenance on mail and PDF text; normalisers (paise, ISO dates, next weekday, GSTIN, name candidates); run lifecycle and rollback from the event log; scripted agent; oracles T1-T9 (T9 x3) and `make oracle` (in-process Acme by default); short-secret redaction; isolation scans for API path literals and subprocesses; judge-only import rule (D-109); decisions D-107 to D-114; risks N.129 to N.137 | `acme/knowledge/api.yaml`, `agent/tools/{api,files,registry}.py`, `agent/{normalise,lifecycle,scripted}.py`, `acme/api.py`, `bench/{live,run_oracle}.py`, `bench/oracles/*`, `Makefile`, `tests/agent/{acme_fixtures,test_api_tools,test_catalog,test_lifecycle,test_normalise,test_agent_isolation,test_registry}.py`, `tests/e2e/test_oracles.py`, `tests/acme/test_pdfs.py`, `tests/checkers/test_engine.py`, `docs/{acme-spec,decisions,risk-log,progress}.md` | `make test`: 1345 passed, 0 failed (1211 before; 134 new); `make test-e2e`: 15 passed (live server: 11 oracle runs chaos off, `commit_then_timeout` T3, `flaky_500` T1, session expiry T8, live rollback); `make oracle TASK=all`: 11/11 DB checkers pass, report checks PENDING (Day 3); 16 mutations (read-back, key derivation, business-error retry, baseline, memo, target state, provenance, read re-login, timeout mapping, rollback order, undo-tool skip, short-secret redaction, scripted stop, download precondition, validator rule, comma grouping) all killed (one survived first and its test was strengthened) | pending |

## Blockers and open questions

- The `TestClient` import prints a Starlette deprecation warning about `httpx` (it wants `httpx2`).
  Harmless for now; revisit if it becomes an error on a Starlette upgrade.
- Dev-only default passwords live in `acme/auth.py` (overridable by env); fine for the sandbox, to be
  listed in the README limitations with CSRF and the missing `Secure` flag (D-046).

- **Manual walk (T1-T9 by hand) limits until Day 3:** T6's security finding (ORG-006, the injected transfer
  text) lives in the run report, which the Day 3 report generator produces; by hand only the invoice entry and the
  absence of a payment or bank change can be shown. T9's action-approval inbox is a runtime feature (Day 3); by
  hand only the send itself via `/mail/compose` is possible, not the pause, the predicted-outcome card or the
  approve/reject decision.
- **Starting the server for the harness:** `export ACME_ADMIN_TOKEN=...` before `make acme`; unset means every
  admin route is 403.

## Deviations from spec

Author-confirmed on 2026-10-06 (decision D-100; no longer open):

- The agent (not Acme) creates the business approval request via `POST /api/approvals` for over-limit invoices and
  payment requests.
- T6 `expected_outcome` is `completed` (security finding in the report, not an exception).
- T7 Patel total is ₹41,300 (below the limit).
- "8 core tasks" = T1-T8; T9 runs outside the pass^3 matrix.
- `.env.example`: the Groq qwen ID is replaced by `GROQ_COMPACTION_MODEL=openai/gpt-oss-20b`.
- Payment requests in `cancelled` or `rejected` state do not block voiding an approved invoice (D-034).
- Rejecting a payment whose vendor is no longer approved is still allowed; only approving is refused (D-091). The
  refusal is a 409 `conflict` with `ORG-002` in the detail because `ERROR_TYPES` is frozen (D-058).

Day 2.2 (2026-10-06; decisions D-107 to D-112):

- **`GET /api/files`** added to Acme (not in the spec's API list before; now documented there): the agent's
  `list_files` tool had no endpoint to list documents.
- **The Day 1 test "bench never imports agent"** is narrowed to the judge (`bench/tasks.py`, `bench/checkers/`):
  the author's brief puts the oracles in `bench/` importing `agent/` (D-109). CLAUDE.md decision 11 (`agent/`
  never reads `bench/`) is unchanged.
- **`api.yaml` in `acme/knowledge/`** is a new knowledge file (the agent's view of Acme's API); acme-spec lists it.

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

Day 1.9 (decisions D-094, D-095; awaiting author review):

- **Chaos events carry the logical clock only**, not wall time: Acme reads no wall clock (N.12,
  `test_acme_never_reads_the_wall_clock`). Order comes from the event id. The request asked for "time".
- **`commit_then_timeout` holds the response for a configurable delay** instead of "never returns" (spec table
  updated); it covers both channels and fires once, on the first eligible write that commits.
- **Chaos targets `ops-agent` only** (D-094); the spec table did not restrict actors.
- **`acme/chaos.py` is 280 lines** (about half docstring and comments), above the ~150 estimated in the risk table.

Day 1.10 (decisions D-096 to D-098; awaiting author review):

- **No per-task checker modules:** one engine plus YAML (D-096); the spec's "one module per task" line is replaced.
- **Checkers read the SQLite file read-only**, not "via the admin read path"; the diff still comes from
  `/__admin/diff` (D-096, D-097).
- **`allowed_changes` has a concrete shape** (`added` maximum, `changed` columns); `audit_log` is implicit (D-097).
- **T9 is one file with `variants`** keyed by approver; the spec schema had one `approver` field (D-097).
- **`received_date` is not checked** for T1, T2, T6, T7: the email date and the entry date are both defensible.
- **T8 does not check the scheduled date**: no SOP fixes it; Acme defaults it to the due date.

Day 1.R (decision D-099; awaiting author review):

- **No new deviations.** The acme-spec PDF section now matches the code (D-070, `iyer_INV-3301.pdf`), so the two Day 1.6
  spec-name deviations above are resolved in the spec text.

Day 2.1 (decisions D-101 to D-106; awaiting author review):

- **Size:** about 470 lines of agent code (about 380 without blank and comment lines) against the "about 300 lines"
  target; `agent/tools/registry.py` is 288 of them (contract checks, redaction and fail-closed paths).
- **Event types:** `precondition` was added next to `tool_call`, `policy_decision` and `tool_result` (precondition
  reads are logged inside the call's events, author instruction). `approval`, `llm_call` and `verifier_result` from
  CLAUDE.md are added when their parts are built; `store.EVENT_TYPES` refuses anything else until then.
- **`.env.example`** gains `ACME_HTTP_TIMEOUT_SECONDS=20` (the agent's HTTP timeout, used from Day 2.2) so every key in
  the config allowlist is documented (a test enforces this).
