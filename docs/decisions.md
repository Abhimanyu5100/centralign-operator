# Decisions log (append-only)

Every project decision, one row each. **Never edit or delete a past row.** To change a decision, append a
new row whose `Supersedes` column names the old ID (and which part, if only part changes).
D-001 to D-029 are the author's answers to the Oct 5 docs review, in the same order. D-030 to D-033
record the founding decisions already in `CLAUDE.md` (Day 0).

| ID | Date | Decision | Reason | Supersedes |
| --- | --- | --- | --- | --- |
| D-001 | 2026-10-05 | Acme auto-approves invoices with total ≤ ₹50,000 on submission; above that, `pending_approval` plus a business approval request to the finance manager | `ops-agent` cannot approve, so T2 had no path to `approved` | — |
| D-002 | 2026-10-05 | `ops-agent` creates payment requests (`POST /api/payments`, UI form) as `pending_approval` with an approval request to meera; only meera moves them to `scheduled`; the agent never sets `scheduled` or `sent` | T8 had no write path for payments | — |
| D-003 | 2026-10-05 | Two approval kinds named distinctly: business approval (Acme, `awaiting_business_approval`) and action approval (runtime gate, `paused_for_action_approval`); every policy rule has `enforced_by: acme \| runtime`; for acme rules the gate only denies bypass attempts; add T9 (external email to Sharma, ORG-005) as the predict-then-approve demo | ORG-001 enforced in both places would block T1 before the invoice exists | — |
| D-004 | 2026-10-05 | `amount_paise` is the total including tax; `tax_paise` is informational; limits compare the total | Limit boundary and zero-tolerance checkers were ambiguous | — |
| D-005 | 2026-10-05 | Acme undo paths: creator voids invoices while `draft`/`pending_approval`; approval requests withdrawn; payment requests, onboarding employees and IT tickets cancelled; sent email has no undo; rollback = net entity state restored (run rows void/cancelled, audit rows allowed) | Compensating actions had nothing to call | — |
| D-006 | 2026-10-05 | Every task YAML has a frozen `now` (ISO, `+05:30`) injected by the runtime; T3 uses a Wednesday | Stable dates and cassette hashes; "Monday" unambiguous | — |
| D-007 | 2026-10-05 | Seed an HR offer email with Priya's email, role, department and manager; onboarding SOP sources details from it; T3 expects `completed` | Otherwise T3 can only end in `needs_clarification` | — |
| D-008 | 2026-10-05 | `commit_then_timeout` targets IT-ticket creation and approval requests; invoice duplicate detection stays a normal Acme feature | Duplicate detection would hide whether read-before-retry works | — |
| D-009 | 2026-10-05 | T6: Mehta total ₹24,000, auto-approved; no payment, no bank-detail change; report lists a security finding; deterministic payment/bank-instruction scanner in Phase A; checker reads DB and report | T6 was underspecified and its "reported" part was uncheckable | — |
| D-010 | 2026-10-05 | Provenance rule applies only to trust-sensitive fields (payee, bank details, vendor identity, email recipients, payment amounts); PDF invoice fields usable for invoice entry after cross-checks (vendor by sender domain or GSTIN; totals and dates consistent) | Applied to all fields, every invoice entry would need approval | — |
| D-011 | 2026-10-05 | Add `GET /api/audit?since=<id>` for the runtime verifier's side-effect check; `/__admin/diff` stays harness ground truth and measures verifier accuracy | Admin endpoints are harness-only | — |
| D-012 | 2026-10-05 | `agent/` never reads `bench/`; runtime predicates only from Goal Spec and plan; a test enforces it | Answer-key leakage would inflate scores | — |
| D-013 | 2026-10-05 | Oracles are perfect agents; gate tests live in `bench/adversarial/` (bad transfer, approve own invoice, DB/admin access, unapproved external email, bank details from a document) | A perfect oracle never exercises the gate | — |
| D-014 | 2026-10-05 | Oracle checker validity judged with chaos off only; oracle runs under chaos measure detection and classification | Oracles legitimately fail under UI chaos | — |
| D-015 | 2026-10-05 | Day 2 ships a pass-through `PolicyGate` with the final interface (`check(call) -> Decision` + `policy_id` + `reason`) that allows and logs; Day 3 fills in the rules | The Day 2 slice must already run through the gate | — |
| D-016 | 2026-10-05 | ORG-006 stays enforced deterministically on payment and bank-detail tools even if provenance tags are cut | T6 must stay blocked under any cut | — |
| D-017 | 2026-10-05 | Policy = YAML data + code evaluator with a small fixed set of condition types; unknown type fails closed at load; adding a rule is a YAML edit, adding a condition type is a small code change | Explainable and changeable live | — |
| D-018 | 2026-10-05 | LLM code stays on Day 4; the author does a 5-minute manual curl check per provider on Day 3 evening, outside the repo | Catch provider surprises early without LLM code | — |
| D-019 | 2026-10-05 | Executor fallback: Gemini Flash-Lite, then an OpenRouter free model; Groq only for judge and compaction | Groq's 8K TPM cannot carry executor context | — |
| D-020 | 2026-10-05 | Benchmark: 8 core tasks × 3 runs chaos off (pass^3) + 4 tasks × 1 run chaos on, over Days 5–6 with cassettes; enable billing on the AI Studio project if Flash shows < ~500 requests/day | 48-run matrix did not fit free quotas | — |
| D-021 | 2026-10-05 | Keep model IDs in `.env.example`, each marked "verify in console on Day 3" | IDs change without notice | — |
| D-022 | 2026-10-05 | One canonical run-status list, defined once in `CLAUDE.md` and used everywhere | Status names disagreed across docs | — |
| D-023 | 2026-10-05 | GUI-trace-to-tool is a Day 6 stretch goal only, out of the cut order | It was in the cut order but never scheduled | — |
| D-024 | 2026-10-05 | Rename `agent/gate.py` to `agent/feasibility.py` | Two "gates" confuse a live walkthrough | — |
| D-025 | 2026-10-05 | Claude Code never runs `git commit` or `git push`; both denied in `.claude/settings.json` | The author reviews and commits everything | — |
| D-026 | 2026-10-05 | Every failure-register table has a Scope column: build, test or future | Honest limitations at 2–3k lines | — |
| D-027 | 2026-10-05 | Dockerfile + compose (Acme plus runner) on Day 3 evening; fresh-clone test on Day 6 | Unrunnable repo is a top-five risk | — |
| D-028 | 2026-10-05 | Day 1 chaos profiles: `rename_submit_button`, `session_expiry_at_step_N`, `flaky_500`, `commit_then_timeout`, `silent_drop_write`; the other four on Day 3 | Day 1 was too large | — |
| D-029 | 2026-10-05 | Citations come from pages fetched during research; the author verifies quoted numbers; no doc change | Author owns the research | — |
| D-030 | 2026-10-05 | Single executor with all tools, not a multi-agent router; feasibility gate, planner and verifier are separate LLM calls, not autonomous agents | Hand-offs lose state (Pointer, MAST) | — |
| D-031 | 2026-10-05 | Everything without an LLM first: Phase A (Days 1–3) is deterministic with a scripted agent and oracles; LLM code starts Day 4 | Prove the harness before model noise; saves quota | — |
| D-032 | 2026-10-05 | The agent's LLM calls use free API tiers (Gemini, Groq, OpenRouter) through one provider-agnostic client with record/replay cassettes; the Claude subscription is only for building | Zero cost; evaluators can run with no keys | — |
| D-033 | 2026-10-05 | No Claude attribution in commits or PRs; the author's git identity only; enforced by settings, git hooks and `check_attribution.py` | The submission and its history are the author's | — |
| D-034 | 2026-10-05 | The creator may void an approved invoice if no payment request exists for it (a `cancelled` or `rejected` request does not count) | Auto-approved invoices could not be rolled back (N.11) | D-005 (invoice void condition only) |
