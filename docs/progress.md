# Progress

The single source of truth for where the project is. Updated by `/checkpoint` at the end of every part.
If this file disagrees with git, git wins for what is committed.

## Now

- **Last updated:** 2026-10-12 15:10 IST
- **Day / phase / part:** Day 7 (submission day). Revert run done (D-220, D-222), docs and README filled, README
  images and the demo video recorded. Awaiting the author's commit, push, video upload and link, submit.
- **Headline, revert run (bench/results/20261012-143613; declared before it ran; 3.1 Flash-Lite pinned, Groq
  reachable):** pass^3 1/8 (T5), runs passed 14/27, **Acme's end state correct 25/27**, refusals 4/6, chaos 4/4 fired
  and recovered, unexplained 0, agreement 31/31, adversarial 8/8, 478 calls. Listed beside it: first 5/8, VPN-confounded
  2/8, rerun 3/8. Main failure: a wrong first assertion locked in by the replan rule (N.214); safe direction.
- **Replay (bench/results/20261012-143855):** 154 cassettes from the revert run; every row to its live status with
  no key; T1 by a shorter path (N.211). T1's passing recording is its `flaky_500` row, used by the quick start, README
  images, fresh-clone check and video.
- **Demo video:** `make demo-video` -> runs/demo/demo.webm (gitignored, about 3 min, captioned, no voice).
- **Checks:** see the checkpoint row below.
- **Running agent/ total (ceiling 3,950):** **3,875** non-blank lines.
- **Next step:** the video is uploaded and linked in README.md; the author commits, pushes, makes the repo
  public and submits the form.
- **RESUME PROMPT:**
  ```
  Read CLAUDE.md and docs/progress.md. Everything is built and measured: headline revert run pass^3 1/8, state correct
  25/27 (bench/results/20261012-143613), all four runs listed in README and docs/EVALUATION.md. What is left is the
  author's: commit, push, upload runs/demo/demo.webm, its link in README.md, make the repo public, submit. Do not
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
| 2026-10-09 | 3.R | Day 3 review fixes and the combined Day 3.R + Day 4 plan (`docs/day4-plan.md`): the report's `recovered` list (a call that succeeded after a failed attempt inside the tool: error, class, count, what settled it; never changes the status, copies no args) in `report.json` and `report.md`, evidence args without transport args, `<error_type> (recovered)` in the bench Failures column (D-164); register P.3 points at `test_an_unknown_browser_form_is_held`; N.145 e2e (planted off-site link denied by the real gate in a real browser); curl check recorded | `agent/report.py`, `bench/run_bench.py`, `tests/agent/test_report.py`, `tests/bench/test_run_bench.py`, `tests/e2e/test_browser.py`, `docs/{day4-plan,failure-register,decisions,risk-log,progress}.md` | `make test`: 1745 passed, 0 failed (1743 before; 2 new); `make test-e2e`: 54 passed, 0 failed (52 before; 2 new); `make bench`: exit 0, 12/12, chaos fired 4/4, adversarial 8/8, recovered errors shown; 4 mutations (list dropped, transport args kept in evidence, bench column without recovered, off-site target reduced to a path) all killed | 3ebc271 |
| 2026-10-09 | 4 | Day 4 (Phase B): LLM client (`agent/llm/`: OpenAI-compatible Gemini and Groq from config only, providers without a key skipped, retries with Retry-After / retryDelay and full-jitter backoff, a long wait or a 4xx goes to the next model, per-run token budget, `llm_call` events, record/replay cassettes keyed on role + request + frozen now, run id refused, empty tool-call ids filled, provider tool-call objects echoed back); live smoke test (`make smoke`) with measured limits in the model plan; SOP loader; Goal Spec and feasibility gate (code: trigger SOPs, names, master probes; one LLM judgement; code checks); executor (gather / act, two strikes, read back first, turn skipping, holds, facts quoted and normalised in code, audit read after a GUI write, untrusted warning); planner (one call, Plan checks: args by the tool model, seen fields, sourced literals, SOP steps; one retry); `agent/run.py` `operate`; `make run` harness; report narrative and stops; T1 and T5 live and replayed; decisions D-165 to D-172; risks N.171 to N.179 | `agent/llm/{__init__,client,cassette}.py`, `agent/memory/{__init__,knowledge}.py`, `agent/{goal,feasibility,executor,planner,run}.py`, `agent/{config,report,store}.py`, `agent/policy/facts.py`, `bench/run_agent.py`, `scripts/smoke_llm.py`, `cassettes/*`, `Makefile`, `.env.example`, `.gitignore`, `CLAUDE.md`, `tests/agent/{llm_fakes,test_llm_client,test_executor,test_operate}.py`, `tests/e2e/test_agent_replay.py`, `tests/test_no_key_leak.py`, `docs/{day4-plan,model-plan,decisions,risk-log,progress}.md` | `make test`: 1788 passed, 0 failed (1745 before; 43 new); `make test-e2e`: 56 passed, 0 failed (54 before; 2 new: T1 and T5 replay with no key); `make bench`: exit 0, unchanged; `make run TASK=T1` live: `awaiting_business_approval`, checker PASS; `TASK=T5` live: `infeasible`, PASS; both pass with REPLAY=1 and no key; key-leak grep over `cassettes/` and `runs/` clean; 16 mutations, 15 killed (the survivor renames the executor's own "done" label, which nothing reads: the status comes only from the verifier) | 50fdaa6 |
| 2026-10-09 | 5.1-5.2 | Day 5 plan (`docs/day5-plan.md`; judge and replan approved with the author's changes; quota update): quota book (`runs/llm_quota.json`, Pacific day from the harness) and `LLM_RPM` pacing in the client; executor chain Lite 3.5 → Lite 3.1 → Flash 3.5 → Flash 3.7, gate on Groq, planner on Gemini; smoke of the two new models; SOP-scoped tools (browser only for a UI-only step in act), lookups in the briefs, cited steps only in act, pruned results, facts kept across calls and read after labels, request as result 0, weekday dates; SOP write-step coverage (`Plan.not_applicable`, only for "when" steps); gate asks only on ambiguity; ask candidates from results; resume after an action approval (approver; hold never shown), reject rollback, `prediction` events and recipient sources; judge (`agent/verifier/judge.py`, `Milestone.judge`, `judge_flags`); replan (assertions frozen, 3 at most, `escalation`); planner rule 1 in code; report sections (skipped steps, replans, escalation, rollback, predictions, judge); `make run TASK=T9:approve|reject|none`, `APPROVE_WAIT`, quota line; prompt freeze test; T1 and T5 re-recorded, stale cassettes deleted; decisions D-173 to D-195; risks N.175 to N.178 updated, N.180 to N.191 | `agent/{executor,planner,run,feasibility,goal,plan,report,store,config}.py`, `agent/llm/client.py`, `agent/memory/knowledge.py`, `agent/tools/registry.py`, `agent/verifier/{__init__,predicates,judge}.py`, `acme/knowledge/sops/{notify-vendor,README}.md`, `bench/{run_agent,approver}.py`, `scripts/smoke_llm.py`, `Makefile`, `.env.example`, `cassettes/*`, `tests/agent/{test_llm_client,test_executor,test_operate,test_judge,test_prompt_freeze}.py`, `tests/e2e/test_agent_replay.py`, `README.md`, `CLAUDE.md`, `docs/{day5-plan,model-plan,decisions,risk-log,progress}.md` | `make test`: 1831 passed, 0 failed (1788 before); `make test-e2e`: 56 passed, 0 failed; `make bench`: exit 0, 12/12, chaos 4/4, adversarial 8/8; T1 live `awaiting_business_approval` PASS (76,283 tokens) and T5 `infeasible` PASS, both in replay with no key; 34 mutations, 33 killed (two survived first and got tests: the judge's answer by position, the act note's read-before-write line; the last survivor widens the replan loop's range, which the `replan <= MAX_REPLANS` guard makes equivalent) | fb2b86b |
| 2026-10-09 | 5.3-5.4 | Ceiling 3,950 once (D-197) and dead-code pass (-33); D-194 executor-ask test; tasks live one at a time with cassettes and replays (T4, T3, T9 none/reject/approve, T6, T7, T8, T2, T1, T1 `flaky_500`), each failure fixed in code or by a post-freeze decision (D-199 to D-209: judge reads rows by id and "A ... B" quotes; planner `tidy`, sampled row fields, enum check, rupees beside paise, two retries, rule 7 for "when" steps; bare-integer paise; no repeated creating writes after a replan; cassette scope for chaos runs; T9:approve recorded last); stale cassettes pruned (137 kept); `make bench AGENT=1` (D-210); measured calls and tokens per task in the model plan | `agent/{executor,planner,run,goal}.py`, `agent/llm/{client,cassette}.py`, `agent/verifier/{__init__,judge,predicates}.py`, `agent/{normalise,config}.py`, `agent/policy/loader.py`, `agent/tools/registry.py`, `bench/{live,run_bench,run_agent}.py`, `Makefile`, `.env.example`, `cassettes/*`, `tests/agent/{test_executor,test_operate,test_judge,test_llm_client,test_normalise,test_registry,test_prompt_freeze}.py`, `tests/policy/{test_loader,test_schema,test_policies_file,test_gate}.py`, `tests/bench/test_run_bench.py`, `tests/e2e/test_agent_replay.py`, `docs/{model-plan,decisions,risk-log,failure-register,progress}.md` | `make test`: 1843 passed, 0 failed; `make test-e2e`: 62 passed, 0 failed (8 replay cases); `make bench`: 12/12, chaos 4/4, adversarial 8/8; `make bench AGENT=1`: 11/11, chaos 1/1, adversarial 8/8; every task live once (checker PASS) and replayed with no key; 14 mutations, 14 killed (judge full read, quote parts, tidy x5, read_tools row fields, enum check, retries, sampling, replan write guard in the executor and in run.py, paise); two survived first and got tests (the tidy call site, the run.py flag) | pending |
| 2026-10-10 | 6.A-B | Live LLM bench mode (`make bench AGENT=1 LIVE=1 K=3`, per-attempt recordings, quota book, rows printed live, LLM columns, T9 reject scope, D-211); live pass^3 21/27, pass^3 5/8; fixes from measurement D-212 (converted paise, facts two strikes), D-214 (result 0 includes lookups), D-215 (enum where -> args, frozen met milestones, verifier no-row ref); T3 re-measured; cassettes rebuilt from the live runs (`bench/keep_cassettes.py`, D-216); run viewer `/runs` (E); README draft (D); Docker TZ + GIT_COMMIT edits (C, not built); `scripts/fresh_clone.sh`; cuts recorded (D-213) | `agent/{executor,normalise,planner,run}.py`, `agent/verifier/predicates.py`, `bench/{run_bench,live,run_agent,tasks,keep_cassettes}.py`, `ui/app.py`, `ui/templates/{inbox,runs,run}.html`, `cassettes/*`, `README.md`, `Dockerfile`, `docker-compose.yml`, `Makefile`, `scripts/fresh_clone.sh`, tests (executor, operate, verifier, prompt freeze, run_bench, keep_cassettes, run viewer, packaging, e2e replay), `docs/{decisions,risk-log,progress}.md` | `make test`: 1858 passed, 0 failed; `make test-e2e`: 62 passed, 0 failed; live bench 21/27 (pass^3 5/8), adversarial 8/8; replay bench 10/11 as live, adversarial 8/8; every new fix test fails without its fix | e7df5ab |
| 2026-10-10 | 6.C-E | D-217 generic fixes (company_rules from policies.yaml, contains per row, judge criteria about meaning, contains values sourced); Docker TZ + GIT_COMMIT built and run (timings in Now); README results from both live result files with the D-216 note; run viewer row counts | `agent/planner.py`, `agent/verifier/judge.py`, `ui/app.py`, `README.md`, `Dockerfile`, `docker-compose.yml`, `tests/agent/{test_operate,test_prompt_freeze}.py`, `tests/ui/test_run_viewer.py`, `docs/{decisions,risk-log,progress}.md` | `make test`: 1868 passed, 0 failed; `make test-e2e`: 56 passed, 12 failed (stale replay, N.207); Docker runner bench 12/12, adversarial 8/8; the 5 new D-217 tests fail without the fixes | 65f6391 |
| 2026-10-10 | 6.Docs | Submission docs: README rewritten as the front door (submission-requirements map, Mermaid architecture, 8 decisions, assumptions, limitations, next, tools), docs/DESIGN.md, docs/EVALUATION.md, docs/EXTENDING.md, docs/DEMO.md; results sections TODO until the final run; doc test (make targets, links and anchors, cited tests, D- and N- ids, results files) | `README.md`, `docs/{DESIGN,EVALUATION,EXTENDING,DEMO}.md`, `tests/test_docs.py`, `docs/progress.md` | `make test`: 1894 passed, 0 failed (doc test 26) | 58a4c56 |
| 2026-10-10 | 6.Final | Final live pass^3 (2/8, Groq blocked), held-out probe 2/2 (`AS_TASK=`, D-218), cassettes from the final run (191), README/EVALUATION/DEMO results filled, fresh-clone WORKTREE mode, `AS` -> `AS_TASK` fix, risks N.208-N.210 | `Makefile`, `bench/{run_agent,run_bench}.py`, `cassettes/*`, `README.md`, `docs/{EVALUATION,DEMO,decisions,risk-log,progress}.md`, `scripts/fresh_clone.sh`, `tests/e2e/test_agent_replay.py`, `tests/bench/test_run_agent_as.py` | `make test`: 1895 passed; `make test-e2e`: 69 passed; doc test 26 passed; fresh clone OK | a7703d8 |
| 2026-10-12 | 6.Rerun | Final live pass^3 rerun under the intended conditions (D-219): 3/8, the README headline with all three runs side by side; cassettes rebuilt from it (166); e2e replay cases updated; risks N.211-N.213 | `README.md`, `docs/{EVALUATION,DEMO,decisions,risk-log,progress}.md`, `cassettes/*`, `tests/e2e/test_agent_replay.py` | `make test`: 1895 passed; `make test-e2e`: 69 passed; doc test 26; fresh clone OK | pending |

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

- **Day 6 recordings (D-216):** CLAUDE.md's Day 6 says cassettes are recorded and replayed; the committed set is assembled from the pass^3 attempts (each recorded from an empty folder) instead of a second live pass, because the free quota ran out; T1 flaky_500 has no replayable recording for the current code.
Day 5.3-5.4 (2026-10-09; decisions D-196 to D-210):

- **Token target dropped** (D-196); **ceiling 3,950** (D-197).
- **Planner:** two retries, not one (D-207); code corrects recurring model slips before validation (`tidy`, logged);
  list reads the gather phase skipped are sampled for their row fields (D-201).
- **Judge reads each row by id** (D-199), as design B said; D-189's no-second-read shortcut is withdrawn.
- **Cassettes:** an optional scope for chaos runs (D-209); T9:approve is recorded after T9:none and T9:reject (D-203).
- **Only T1 has an LLM chaos recording**; T3's and T8's chaos variants are skipped by `make bench AGENT=1` until Day 6.
- **Eleven prompt-input edits after the freeze** (D-199 to D-209), each with its re-record.

Day 5.1-5.2 (2026-10-09; decisions D-173 to D-195):

- **Governed learning cut, no compaction, free tier only** (D-173 to D-175); pass^3 stays for Day 6 (D-188 withdraws
  D-177).
- **Models:** executor Flash-Lite first (D-187); the feasibility gate on Groq gpt-oss-120b (D-178); the planner back
  on the Gemini chain after two bad Groq plans (D-193), so the judge (Groq) is independent of both executor and
  planner. CLAUDE.md "Models" updated.
- **Judge:** reads the rows the verifier's own milestone reads picked (no second read) and lowers only `completed`;
  other statuses get `judge_flags` (D-189). Plan B said it would re-read through the registry and lower
  `awaiting_business_approval` too.
- **Five prompt edits after the freeze** (D-191 to D-195), each with a T1 (and for D-194 a T5) re-record.
- **T1 tokens 76K, not the 60K target** (model plan).
- **Rollback after a rejection keeps `blocked_by_policy`** (D-183); `rolled_back` stays for an explicit rollback.
- **SOP format:** a write step that applies only in some cases says "when ..." in its title (D-195; SOP README).

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

Day 4 (2026-10-09; decisions D-165 to D-172):

- **OpenRouter is not used** (no key; CLAUDE.md "Models" and the model plan updated): the reasoning chain is Gemini
  Flash then Flash-Lite. **Compaction** is Groq `qwen/qwen3.8-27b` (D-100's `openai/gpt-oss-20b` superseded).
- **Cassette key** excludes the provider and model (the model plan said hash(provider, model, messages, tools)).
- **Gather, then plan:** the planner runs after a read-only executor phase, not before execution (CLAUDE.md's
  architecture shows Planner before Executor); the plan is final before the first write.
- **The SOP parser was not moved** into agent/ (plan B said it would be): a small loader in `agent/memory/knowledge.py`
  is kept in step with the strict test parser by a test (line cap).
- **No token-bucket limiter** (model plan "Client design"): retries and the fallback chain only; Day 5 if the bench
  needs one.

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
