# Progress

The single source of truth for where the project is. Updated by `/checkpoint` at the end of every part.
If this file disagrees with git, git wins for what is committed.

## Now

- **Last updated:** 2026-10-07 00:08 IST
- **Day / phase / part:** Day 3 (Phase A), part 3.4 (packaging and skills) committed (ab94660) and its Docker check passed
  → Day 4 next (Phase B), after the author's evening curl check
- **Currently doing:** Day 3.4 awaits author review and commit. It includes the author's two fixes before 3.4:
  N.169 (the T2 chaos slot moved to `commit_then_timeout` on T8; UI-only variants marked `channel: gui` and skipped
  without a GUI oracle; every chaos run must fire, D-161) and the bench shutdown noise (D-162).
- **Day 3 done-when "`docker compose up` serves Acme": DONE (2026-10-07 00:08 IST, Colima, Docker Compose 5.6.0).**
  `docker compose build` passed in 5 min 12 s (image `centralign-operator:latest` 4 GB, on the 3.4 GB Playwright
  base); `docker compose up -d acme` answered `/healthz` `{"ok":true}` after 2 s (PDFs checked, seed `base` reset,
  uvicorn on 0.0.0.0:8000); the admin token is set inside `acme` and absent inside `runner` even with a token exported
  in the shell; `docker compose run --rm runner make bench` exited 0 in 24 s with the same table as the local run
  (12/12 chaos-off runs, pass^1 11/11, CuP 12/12, 0 unexplained, refusals 2/2, chaos fired 4/4, agreement 16/16,
  adversarial 8/8) and no traceback; results written to the mounted `bench/results/20261006-183847.{json,md}`;
  `docker compose down` left nothing running. Whole check: 389 s. The token for this check was a random value
  exported in the shell for the commands only (`.env` has none).
- **Day 3 plan:** `docs/day3-plan.md` (approved; D-125 to D-135, then D-136 to D-163 while building). Parts: 3.1
  b04ddba, 3.2 5adf948, 3.3 781c099, 3.4 ab94660.
- **Running agent/ total (D-115, D-154):** 2,907 non-blank lines (3,557 raw); 3.4 added no agent code. Day 3 ends at
  2,907, about 890 under the 3,800 ceiling for Days 4-6 (estimated about 800).
- **Latest bench (`make bench`, 23 s, exit 0, no traceback):** chaos-off runs 12/12 (11 API + T1 GUI), pass^1 11/11,
  CuP 12/12, 0 unexplained side effects, correct refusals 2/2, chaos fired 4/4 and recovered 4/4 (T7's GUI-only
  `rename_submit_button` skipped), verifier-vs-diff agreement 16/16, adversarial 8/8. T3 and T8 under
  `commit_then_timeout` take about 3 s each.
- **Next step:** Day 4 (Phase B), per the CLAUDE.md build order: the LLM client with record/replay cassettes and a smoke
  test through the client first; then the Goal Spec and feasibility gate (`agent/feasibility.py`), the planner
  (`agent/planner.py`, emitting `agent/plan.Plan`) and the executor loop replacing the scripted agent. The planner
  and executor are author-owned: propose their designs in prose first. Before it: the author's Docker check and
  the manual 5-minute curl check per provider (outside the repo).
- **Carried over:**
  - **Day 6 polish (seen in the Docker run, not fixed: Dockerfile edits need the author's OK):** inside the
    container the bench's timestamps are UTC (`20261006-183847`, `+00:00`; no `TZ` in the image) and the commit shows
    as "unknown" (`.git` is not in the image). Options: `ENV TZ=Asia/Kolkata` (needs `tzdata`) and a `GIT_COMMIT`
    build arg the bench prints.
  - **Day 4 (N.168):** a record the run created through the GUI is not "created by the run" until the run reads the
    audit log, so a GUI attach right after a GUI invoice entry is held by ORG-008 (an API entry then a GUI attach
    passes). Fix if the executor needs it: read the new record's id from the redirect after a create form, or read
    the audit log after a GUI create.
  - **Day 4:** the GUI channel's failures are typed like the API's (`timeout` with `outcome_unknown`,
    `session_expired` with `session_renewed`, `server_error` from a 500 page); the GUI oracle does not retry a 500,
    the executor's classifier does (two strikes, read back first).
  - **Day 4:** the executor uses `agent/failures.classify` for every failed result: two strikes count the API tool's
    own `attempts` (D-108), and after `read_back_first` it reads back before any new write.
  - **Day 4:** `run_id` never enters LLM prompts or cassette hash keys (D-106); the derived idempotency key is a
    transport arg, never shown to the LLM (D-108).
  - **Day 4:** the executor calls `Run.begin()` before its first step, `verify(run)` at the end and
    `build_report` / `write_report` after, as `bench/live.run_oracle` does; the planner emits `agent/plan.Plan`
    (business keys and `{ref: Mn}`, N.156) with a milestone for every entity it may write through the browser (D-156).
  - **Bench timing (N.167):** T6's verification waits the full read lag (about 6 s, one absence check); a 500 under
    `flaky_500` waits the read lag before the keyless retry (T1 about 6 s).
  - **Day 5:** `rolled_back` as a verifier status arrives with "rollback if rejected"; a GUI oracle for T7 would let
    its `rename_submit_button` variant run (D-161).
  - **Day 6:** the README (started in 3.1 with "Known limitations" only) gets setup (including Docker), demo, results
    and tools used; keep one `bench/results/<timestamp>.md` (`git add -f`); the fresh-clone test.
  - `iyer_INV-3301.pdf` stays unreferenced by T1-T9 (Phase B stretch); the scanner corpus test reads it.
- **RESUME PROMPT:**
  ```
  Read CLAUDE.md and docs/progress.md, then docs/model-plan.md, docs/research-notes.md and docs/failure-register.md.
  Phase A (Days 1-3) is built: Acme, the tool registry, the policy gate, scanner and action approvals with the
  inbox, the verifier, the run report and AcmeBench (make bench), Docker files. Start Day 4 (Phase B): first the LLM
  client with record/replay cassettes and a smoke test through the client (agent/llm/), then the Goal Spec and
  feasibility gate, the planner (emitting agent/plan.Plan) and the executor loop replacing the scripted agent. The
  planner and executor are author-owned: propose their designs in prose first and wait for my approval. Show the
  risk table first, stop after each part, and run /checkpoint. Do not commit or push.
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
| 2026-10-06 | 2.2 | Endpoint catalog `acme/knowledge/api.yaml` (30 tools: reads, writes, undo tools; session, API-prefix allowlist) with a load-time validator; API tools generated from it (`agent/tools/api.py`: strict args models, `request_of` = real method and path, `AcmeClient` per run with login from config, typed errors, httpx timeout -> `timeout`, one retry only after an unknown outcome or lost session, derived idempotency keys, `new_row` / `target_state` read-back, unresolved-write memory, `already_done` + `attempts`); `GET /api/files`; downloads into `runs/<run_id>/files/`, `extract_pdf_text` with a downloaded-file precondition; provenance on mail and PDF text; normalisers (paise, ISO dates, next weekday, GSTIN, name candidates); run lifecycle and rollback from the event log; scripted agent; oracles T1-T9 (T9 x3) and `make oracle` (in-process Acme by default); short-secret redaction; isolation scans for API path literals and subprocesses; judge-only import rule (D-109); decisions D-107 to D-114; risks N.129 to N.137 | `acme/knowledge/api.yaml`, `agent/tools/{api,files,registry}.py`, `agent/{normalise,lifecycle,scripted}.py`, `acme/api.py`, `bench/{live,run_oracle}.py`, `bench/oracles/*`, `Makefile`, `tests/agent/{acme_fixtures,test_api_tools,test_catalog,test_lifecycle,test_normalise,test_agent_isolation,test_registry}.py`, `tests/e2e/test_oracles.py`, `tests/acme/test_pdfs.py`, `tests/checkers/test_engine.py`, `docs/{acme-spec,decisions,risk-log,progress}.md` | `make test`: 1345 passed, 0 failed (1211 before; 134 new); `make test-e2e`: 15 passed (live server: 11 oracle runs chaos off, `commit_then_timeout` T3, `flaky_500` T1, session expiry T8, live rollback); `make oracle TASK=all`: 11/11 DB checkers pass, report checks PENDING (Day 3); 16 mutations (read-back, key derivation, business-error retry, baseline, memo, target state, provenance, read re-login, timeout mapping, rollback order, undo-tool skip, short-secret redaction, scripted stop, download precondition, validator rule, comma grouping) all killed (one survived first and its test was strengthened) | 3fbefab |
| 2026-10-06 | 2.3 | Browser tool (`agent/tools/browser.py`: Chromium per run with an allowlisted env, pruned aria-snapshot view with refs and an 8,000-char cap, role + accessible name actions, per-call side effect and form request for the gate via `ToolSpec.side_effect_of` and catalog `ui_forms`, stale-target refusal, GUI session renewal without resubmitting, Playwright timeouts typed); `login_page` and `ui_forms` in the catalog; scripted `Step.when`; T1 GUI oracle with read-back and one redo; `make oracle CHANNEL=gui`; Acme served as a child process by the harness; four chaos profiles (`slow_server`, `toast_2s`, `field_moved`, `delayed_write`, D-116) with `chaos_hidden`; leak fix (form hint 12500.00) and leak test over templates and form messages; agent line target 3,500 (D-115); manual walk and Day 4 carry-over recorded; decisions D-115 to D-120; risks N.138 to N.143; N.92, N.126, N.127 tested | `agent/tools/{browser,api,registry}.py`, `agent/{config,lifecycle,scripted,normalise}.py`, `acme/{chaos,db,web,ui,api,money,forms}.py`, `acme/templates/{base,_macros,error,invoice_form}.html`, `acme/knowledge/api.yaml`, `bench/{live,run_oracle}.py`, `bench/oracles/{__init__,T1_gui}.py`, `Makefile`, `.env.example`, `CLAUDE.md`, `tests/agent/{test_browser_unit,test_agent_isolation,test_api_tools,test_catalog}.py`, `tests/e2e/{test_browser,test_oracles}.py`, `tests/acme/{test_chaos,test_knowledge,test_money_and_forms,test_ui}.py`, `tests/checkers/test_engine.py`, `docs/{acme-spec,decisions,risk-log,progress}.md` | `make test`: 1395 passed, 0 failed (1345 before; 50 new); `make test-e2e`: 29 passed (14 new: browser view, cap, stale target, GUI session, toast capture, slow write, T1 GUI oracle off/rename/field_moved/toast/silent drop/delayed write/flaky, harness env); 19 mutations (browser env, launch env, click effect and request, quoted lines, stale check, no-resubmit, refs for buttons, outcome_unknown, session detection, ui_forms validation, four chaos effects, field order guarantee, old hint, `when`) all killed (one survived first; test added) | 49dedd1 |
| 2026-10-06 | 2.R | Day 2 review fixes (`/day-review 2`, author calls): register 3.6 to `future`, no general code tool, `code.py` out of the CLAUDE.md layout (D-121); registry invariant: a per-call side effect stronger than the declared worst case fails closed, `browser_click` worst case `external_comms` (D-122); a link's href is re-read before a click; re-render e2e tests (register 4.5); register 3.2 proof reworded; P.7 secret grep over `runs/` after a GUI run; CLAUDE.md Commands `make oracle` line and Day 3 row (chaos profiles done Day 2.3); D-123 (`delayed_write` never with T3/T8 until polling; N.141 a Day 3 must-do) and D-124 (GUI rollback through API undo tools, N.142) with carry-overs | `agent/tools/{registry,browser}.py`, `tests/agent/{test_registry,test_browser_unit}.py`, `tests/e2e/test_browser.py`, `CLAUDE.md`, `docs/{failure-register,decisions,risk-log,progress}.md` | `make test`: 1402 passed, 0 failed (1395 before; 7 new); `make test-e2e`: 34 passed (29 before; 5 new: re-render x3, same-name link, P.7 secret grep); 4 mutations (strength check, href re-read, a password leaked into an observation, `browser_click` worst case) all killed (the last survived first; a mail-form case was added) | 7938f85 |
| 2026-10-06 | 3.1 | Day 3 plan (`docs/day3-plan.md`, approved: D-125 to D-135) and part 1, policy: the gate evaluator over every rule (strictest effect wins, every matching id cited, approvals lift holds once and never denies, any error is GATE-ERROR); three new condition types (`side_effect_in`, `run_has_no_sop`, `target_not_created_by_run`); ORG-005 widened to external comms, new ORG-007 (provenance), ORG-008 (irreversible change to a record the run did not create), ORG-009 (no SOP); run facts from the run's own log (untrusted/trusted values with taint laundering closed, vendor status, created rows); ORG-006 scanner with masked excerpts; append-only single-use action approvals filed by the registry with a predicted outcome; GUI form fields visible to the gate and re-checked at click time; off-site targets denied; `ask_user` / `declare_infeasible`; scripted pause / resume / blocked; `Run.begin` audit start mark; oracles carry plans (SOP), T4 asks, T5 declines, T9 pauses; approval inbox `ui/app.py` (`make ui`) and the bench's scripted approver; eight adversarial scripts (`make adversarial`); Acme test for one audit `ts` per write; README limitations; decisions D-125 to D-143; risks N.144 to N.164 | `agent/policy/{gate,facts,scanner,approvals,models,loader}.py`, `agent/{plan,scripted,lifecycle,store}.py`, `agent/tools/{registry,api,browser,ask}.py`, `acme/knowledge/{policies,api}.yaml`, `ui/{__init__,app}.py`, `ui/templates/inbox.html`, `bench/{live,run_oracle,approver}.py`, `bench/adversarial/*`, `bench/oracles/*`, `Makefile`, `README.md`, `CLAUDE.md`, `tests/policy/{test_gate,test_facts,test_scanner,test_approvals,test_schema,test_policies_file}.py`, `tests/agent/{test_scripted,test_gate_interface,test_registry,test_browser_unit,test_agent_isolation,test_lifecycle,test_api_tools,test_catalog,acme_fixtures,agent_fixtures}.py`, `tests/ui/test_inbox.py`, `tests/e2e/{test_adversarial,test_oracles,test_browser}.py`, `tests/acme/test_services.py`, `docs/{day3-plan,decisions,risk-log,failure-register,progress}.md` | `make test`: 1577 passed, 0 failed (1402 before); `make test-e2e`: 46 passed, 0 failed (34 before; 12 new: 8 adversarial scripts, the spec list, T9 approval order, GUI form fields seen and a changed form refused); `make oracle TASK=all`: 11/11 DB checkers pass through the real gate with the expected endings (T4 asked, T5 infeasible, T9 paused / done / blocked); `make adversarial`: 8/8 stopped as expected; 22 mutations (gate x8, facts x3, scanner x2, registry x3, browser, approvals x2, inbox token, resume after rejection, ORG-009 removed) all killed (the IFSC case mutant survived first; a test was added); the laundering script fails without D-133 | b04ddba |
| 2026-10-06 | 3.2 | D-144 (ORG-007 exempts only the internal domain; `exempt_recipient_domains: internal`) and part 2, verifier and recovery: `agent/plan.py` (Predicate / Milestone / Plan with business keys and `{ref: Mn}`, a backward-only DAG, `plan_problems`); the verifier (`agent/verifier/`): layer 1 postconditions from the catalog's `verify` read per write, layer 2 milestone predicates through API reads polled through `READ_LAG_SECONDS`, absence believed only after the window, layer 3 audit rows since the start mark grouped by `ts` and matched to the run's writes (any row of a group), `decide_status` as a pure table, `unverified` on crash or timeout, a `verifier_result` event; the failure classifier `agent/failures.py`; read-lag polling in the keyless read-back after an unknown outcome (D-123); GUI rollback from audit inserts (D-128); milestone plans for every oracle; the harness verifies every run; acme-spec policy and adversarial tables; audit-insert bug fixed (N.165); decisions D-144 to D-153; risks N.165 to N.167 | `agent/verifier/{__init__,predicates,side_effects}.py`, `agent/{plan,failures,lifecycle,config}.py`, `agent/policy/{facts,gate,loader,models}.py`, `agent/tools/api.py`, `acme/knowledge/{api,policies}.yaml`, `.env.example`, `bench/{live,run_oracle}.py`, `bench/oracles/*`, `tests/agent/{test_verifier,test_plan,test_failures,test_api_tools,acme_fixtures}.py`, `tests/policy/{test_facts,test_gate,test_loader,test_schema}.py`, `tests/e2e/{test_browser,test_oracles}.py`, `docs/{acme-spec,decisions,risk-log,progress}.md` | `make test`: 1677 passed, 0 failed (1577 before); `make test-e2e`: 49 passed, 0 failed (46 before; new: T3 under `delayed_write`, GUI rollback, silent drop without redo is `failed`; verifier status asserted on every oracle and chaos run); `make oracle TASK=all` and `CHANNEL=gui`: every run's verifier status equals its `expected_outcome`; `make adversarial`: 8/8; 21 mutations (status table x2, verifier x4, predicates x4, layer 3 x3, API polling x2, audit insert, classifier x2, plan refs, ORG-007 partners exempt) plus the GUI rollback on e2e, all killed | 5adf948 |
| 2026-10-06 | 3.3 | Author decisions D-154 (ceiling about 3,800), D-155 (`ui_forms` declare `entity` and `target_param`; the browser tool gives the gate the record a GUI form changes, so the PI-6 attach passes ORG-008 on the run's own invoice and is held on a pre-existing one; layer 3 matches GUI writes by entity and id), D-156 (claimed-but-not-audited writes listed under report side effects; a verifier note when a GUI write's entity has no milestone); part 3, report and bench: `agent/report.py` (D-098 contract, status only from `verifier_result`, questions, refusal, masked security findings, evidence, action approvals with the flattened predicted call and decision, side effects with Acme table names from the catalog, classified failures, verifier checks; `report.json` and a one-screen `report.md` per run); the harness verifies, reports and checks every run (report checks are real, no PEND); bench and adversarial runs use `runs/bench.db` (N.164); `bench/run_bench.py` and `make bench` (every run chaos off K times, the GUI oracle, the YAML chaos variants once with the T3/T8 `delayed_write` guard, the adversarial scripts; pass, status, CuP, unexplained, refusals, chaos fired, verifier-vs-diff agreement, held calls, wall and verifier time; `bench/results/<timestamp>.{json,md}`, ignored by git); decisions D-154 to D-160; risks N.168, N.169 | `agent/report.py`, `agent/{plan,lifecycle}.py`, `agent/verifier/{__init__,side_effects}.py`, `agent/tools/{api,browser}.py`, `acme/knowledge/api.yaml`, `bench/{live,run_oracle,run_bench}.py`, `bench/adversarial/__init__.py`, `bench/oracles/{__init__,T4,T5,T6,T9}.py`, `bench/results/.gitkeep`, `.gitignore`, `Makefile`, `CLAUDE.md`, `tests/checkers/test_report_contract.py`, `tests/bench/test_run_bench.py`, `tests/agent/{test_report,test_verifier,test_plan,test_catalog,test_browser_unit}.py`, `tests/policy/test_gate.py`, `tests/e2e/{test_browser,test_oracles}.py`, `docs/{decisions,risk-log,progress}.md` | `make test`: 1730 passed, 0 failed (1677 before); `make test-e2e`: 51 passed, 0 failed (49 before; new: PI-6 attach through the browser and the real gate, a bench slice end to end); `make bench`: 17/17 runs, agreement 17/17, adversarial 8/8 in 37 s; 14 mutations (report x4, bench columns x5, bench store, GUI target x2, layer 3 GUI id, coverage warnings) all killed (the layer 3 GUI id mutant survived first; a `writes_of` test was added) | 781c099 |
| 2026-10-06 | 3.4 | Author fixes before 3.4: D-161 (the T2 chaos slot moves to `commit_then_timeout` on T8; Acme declares its UI-only profiles; a UI-only variant must be marked `channel: gui` and runs only with a GUI oracle, T7's is skipped; every chaos run the bench runs must fire) and D-162 (the harness's Acme holds a timeout 5 s, its agent times out after 3 s, the graceful shutdown outlasts the hold; `chaos.after_write` ends a cancelled hold with one log line); part 4, packaging and skills: `Dockerfile` (one image from the Playwright 1.63.0 noble image, uv 0.12.23, `uv sync --frozen`, `make`), `docker-compose.yml` (`acme` on :8000 with the admin token only in its env and a health check; `runner` in a `tools` profile running `make bench` with its own child Acme, results mounted), `.dockerignore`, `make acme HOST=`, the `/add-policy` and `/chaos-test` skills, CLAUDE.md commands, a static packaging test; decisions D-161 to D-163; risk N.170 | `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `Makefile`, `CLAUDE.md`, `.claude/skills/{add-policy,chaos-test}/SKILL.md`, `acme/chaos.py`, `bench/{live,run_bench,run_oracle,tasks}.py`, `bench/tasks/{T2,T7,T8}.yaml`, `tests/test_packaging.py`, `tests/acme/test_chaos.py`, `tests/bench/test_run_bench.py`, `tests/checkers/test_engine.py`, `tests/e2e/test_oracles.py`, `docs/{decisions,risk-log,progress}.md` | `make test`: 1743 passed, 0 failed (1730 before); `make test-e2e`: 52 passed, 0 failed (51 before; new: the bench prints no traceback and T3's held run takes 3 s); `make bench`: exit 0 in 23 s, chaos fired 4/4, adversarial 8/8, no traceback; mutation (no cancellation handler) killed; Docker check (2026-10-07, Colima): build 5 min 12 s, image 4 GB, `/healthz` ok after 2 s, token only in `acme`, `docker compose run --rm runner make bench` exit 0 in 24 s with the same table | ab94660 (Docker results added after) |

## Blockers and open questions

- The `TestClient` import prints a Starlette deprecation warning about `httpx` (it wants `httpx2`).
  Harmless for now; revisit if it becomes an error on a Starlette upgrade.
- Dev-only default passwords live in `acme/auth.py` (overridable by env); fine for the sandbox, to be
  listed in the README limitations with CSRF and the missing `Secure` flag (D-046).

- **Manual walk (done Oct 6, see Now); what it could not show until Day 3:** T6's security finding (ORG-006, the injected transfer
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

Day 2.3 (2026-10-06; decisions D-116 to D-119):

- **The four remaining chaos profiles** landed on Day 2 instead of Day 3 (D-028 said Day 3), with semantics
  written into acme-spec first (D-116). `delayed_write` is read lag (rows hidden from ops-agent GETs for 5 s), the
  narrowest reading of "write becomes visible after 5 s" that needs no async write path.
- **The harness serves Acme as a child process** (D-119), not a thread, so the admin token never enters the
  harness or agent process env.
- **`ToolSpec.side_effect_of`** extends the 2.1 registry contract: a tool may name its side effect per call; the
  static `side_effect` is the worst case (D-117). `ToolCall` and the gate are unchanged.

Day 3.4 (2026-10-06; decisions D-161 to D-163):

- **Docker ran after the part** (2026-10-07, Colima; see Now): the build machine had no container runtime while 3.4
  was built, so the check ran once the author started Colima. Every step passed.
- **The runner is started with `docker compose run --rm runner make bench`** (`--rm` added to the planned command so
  finished runner containers do not pile up).
- **T2 has no chaos variant; T8 has two** (D-161, D-095); T7's variant is marked GUI-only and skipped.
- **`make oracle` (without LIVE) also uses the harness server settings** (5 s hold, 3 s agent timeout), like the bench.

Day 3.3 (2026-10-06; decisions D-154 to D-160):

- **The report adds fields to the D-098 contract:** `status_reasons`, `notes`, `refusal`, `failures` and `verifier`;
  `action_approvals[]` adds `approval_id`, `policy_ids`, `reason`, `decided_by` and `used`; `side_effects[]` adds
  `actor`, `channel`, `unexplained` and the claimed-but-not-audited entries (D-157).
- **`Oracle.pending` and `OracleRun.pending` are gone:** every report check is a real check now (D-160).
- **The catalog session gains `entity_tables`** (audit entity type -> Acme table) for the report (D-157).
- **Bench results are ignored by git** (`bench/results/*.json`, `*.md`); keep a chosen one with `git add -f` (D-158).

Day 3.2 (2026-10-06; decisions D-144 to D-153):

- **Layer 1 reads the catalog's `verify` spec** (one per write, D-146) instead of `ToolSpec.postconditions`, which
  stays in the registry contract unused.
- **A claimed-but-not-audited write is a note, not a failure** (D-148): the plan's A3 table listed it under
  `failed`. A run that read back and redid a silently dropped GUI submit reached its target states; when the write
  mattered, its postcondition (API) or a milestone (GUI) fails the run. `Verdict.notes` holds these.
- **No plan or no milestones gives `unverified`** even when nothing was written, unless an ask, a refusal, a pause
  or a rejection decides the status (D-148): nothing to check is never `completed` (6.10).
- **GUI rollback undoes API writes first, then GUI rows** (each newest first), not one merged order (D-128).
- **`make test` takes about 29 s** (19 s before): the verifier and polling tests wait out short read lags.
- **3.2 is over its line estimate** (+511 against +320), see Now.

Day 3.1 (2026-10-06; decisions D-125 to D-143):

- **Policies:** ORG-005 matches every `external_comms` call (any channel) instead of two request paths; ORG-007,
  ORG-008 and ORG-009 are new (D-126, D-133, D-136, D-144). acme-spec's policy table was updated in 3.2.
- **Interfaces beyond D-131:** `ToolCall.target` (the existing record an undo changes, from the catalog's single
  integer path id) and `ToolSpec.target_of` (D-137); `GateArgs` returned by `gate_args_of`; the session gains
  `creator_fields` in `api.yaml` (D-133).
- **The pass-through gate left `agent/`:** `AllowAllGate` is a test fixture only; `start_run` always builds the policy
  gate unless a test injects one (D-138). Browser e2e tests (mechanics) use it; oracle, rollback and adversarial
  tests use the real gate.
- **`tests/agent/test_gate.py` renamed `test_gate_interface.py`:** it shared a basename with the new
  `tests/policy/test_gate.py`, and pytest without `__init__.py` files cannot collect both (N.161).
- **A link click's request carries its query string** (`site_target`); `pathglob` strips it before matching.
- **`t6_bad_transfer`** asserts three lines (D-129) instead of "Acme 422 plus the finding" only.
- **`bench/approver.py` imports `ui/`:** the scripted approver drives the inbox's own endpoints through TestClient.
- **README.md exists** with "Known limitations" only (the author's change 2); the full README is Day 6.
- **3.1 is over its line estimate** (+644 against +460), see Now.

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
