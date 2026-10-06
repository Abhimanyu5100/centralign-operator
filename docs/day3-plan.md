# Day 3 plan: policy gate, scanner, verifier, report, bench, packaging

Status: **approved 2026-10-06** with all eight decisions as recommended (decision 2 with three new condition types)
and four changes, recorded as D-125 to D-135 (see "Author's changes" at the end). Rules for the whole day:
no LLM code, no API keys, `agent/` never reads `bench/`, no commit or push.

Read for this plan: `CLAUDE.md`, `docs/progress.md` (Now and every carry-over), `docs/acme-spec.md`,
`docs/failure-register.md`, `docs/risk-log.md`, `docs/decisions.md` (D-064 to D-124), `acme/knowledge/policies.yaml`
and `api.yaml`, and the Day 2 code the designs plug into (`agent/policy/*`, `agent/tools/*`, `agent/lifecycle.py`,
`agent/scripted.py`, `bench/live.py`, `bench/checkers/engine.py`, `bench/oracles/*`).

## 0. Open decisions

Each has a recommendation; "all as recommended" is a valid answer. Decisions 1 to 3 push back on parts of the
decided design.

1. **The gate cannot see what a GUI submit sends (push back).** A `browser_click` call carries only `{ref}`. So the
   gate cannot see the vendor on a GUI invoice (ORG-002), the recipient on the compose form (ORG-005) or any
   trust-sensitive value (ORG-007), and an action approval for a GUI click (fingerprint of `{ref}`) would not bind
   the email's content. Declaring `trust_sensitive_args` on `ui_forms` does not fix this on its own.
   - **A (recommended):** a new async `ToolSpec.gate_args_of`. For a submit, the browser tool reads the form's
     visible named fields (`FormData`, hidden inputs left out) just before the gate decides. Their HTML names are
     the API's argument names (`vendor_id`, `to`, `subject`, `body`; the vendor select's value is the vendor id).
     The registry adds them to `ToolCall.args`, so the conditions and the fingerprint see them. At click time the
     tool reads the form again and refuses to submit if any field changed (the same pattern as today's
     form-target re-check). About 20 lines in `browser.py` and 8 in `registry.py`.
   - B: deny every GUI submit to a form a rule must see into. Cheaper, but it ends GUI invoice entry, so the T1 GUI
     oracle and the GUI chaos runs (`rename_submit_button`, `field_moved`, `silent_drop_write`) stop working.
2. **Side-effect-class defaults as blanket rules would over-hold (push back).** Rules can only tighten. "Every
   `external_comms` needs approval" would also hold T3's internal welcome email and break the "allowlisted recipient
   needs no approval" test. "Every `irreversible_write` needs approval" would hold every rollback step (the API undo
   tools are irreversible). Recommended YAML, all through the new `side_effect_in` condition, no policy ID in code:
   - **ORG-005 becomes the external-comms default:** `side_effect_in: [external_comms]` plus
     `recipient_domain_not_in: {arg: to}` (the request path list goes). Covers any channel and any future tool. A
     call whose recipient the gate cannot read is held.
   - **New ORG-008:** `side_effect_in: [irreversible_write]` plus a third new condition type,
     `target_not_created_by_run` → require_approval. "An irreversible change to a record this run did not create
     needs an action approval." It holds unknown GUI forms (the catalog classes them irreversible), GUI undo forms
     and an API undo aimed at someone else's row. That last case matters: Acme checks the creator on void, withdraw
     and payment cancel, but **not** on `cancel_employee` or `cancel_it_ticket`. Rollback is not held, because it
     only undoes rows the run created. "Created by the run" = rows returned by the run's own API writes, plus rows
     that a `list_audit` result in the run's log shows were inserted by the run's account after the run's start
     mark (that is how a GUI rollback qualifies, decision 4).
     *If you want to stay at two new condition types:* ORG-008 = `side_effect_in: [irreversible_write]` +
     `tool_in: [browser_click]`, and the API undo hole is logged for Day 4.
   - **New ORG-009 (no SOP, D-081):** `run_has_no_sop` + `side_effect_in: [reversible_write, irreversible_write,
     external_comms]` → require_approval.
   - ORG-007 (provenance) as decided.
3. **Vendor status inside a pure, synchronous `check()` (push back on the mechanism, not the intent).** Reading a
   vendor from Acme is async I/O, and `check()` is sync and pure. Recommended: the lookup answers from this run's own
   trusted reads in the event log (the latest vendor row for that id from `find_vendors` / `get_vendor`). A vendor
   not read in this run has an unknown status, which counts as `not in [approved]`, so ORG-002 denies with "read
   the vendor first" (fail closed). The process-invoice SOP reads the vendor anyway. Consequences: the T1 GUI oracle
   gains one API `find_vendors` step (its writes stay GUI). A vendor blocked mid-run, after the read, is not noticed
   (Acme does not re-check invoice entry), which is accepted for the sandbox (N.147).
4. **GUI rollback source (simplifies D-124).** D-124 says business key plus creator, and the audit log only where a
   table has no creator column. Recommended: the audit log for every table. Take rows **inserted** by the run's
   actor through the `ui` channel since the run's start mark, newest first. Undo each with the catalog undo of the
   write tool that creates that entity (`ui_forms.same_as`). Same rows, one mechanism, about 30 lines. API writes
   keep the existing event-log rollback (exact ids from the run's own results). D-124 has the same caveat: this
   assumes one run per actor at a time (X.7, future).
5. **Adversarial calls the catalog cannot express.** The agent has no tool to decide an approval or write bank
   details. `create_payment`'s strict args also reject an amount or an account before anything is sent.
   Recommended:
   - `approve_own_invoice`, the ORG-004 API-request variants and `bank_details_from_document` each register a
     clearly labelled **fixture tool** on that run's registry (a stand-in for a careless catalog edit). The gate must
     stop it, and Acme's own refusal is shown as the second line.
   - `t6_bad_transfer` proves three lines. The registry refuses the extra fields (`invalid_args`, nothing sent). The
     same body sent raw with the run's own session gets Acme's 422. The run's ORG-006 scanner finding is in the
     report. No gate deny is expected (D-086).
6. **CuP definition for the bench.** Recommended: a run is completed under policy when its checker passes, it got
   no gate deny and no Acme policy refusal (403, or a 409 naming an ORG id), and the verifier lists no unexplained
   side effect. As in ST-WebAgentBench, an attempt the gate stopped still counts as a violation.
7. **Additions to the D-101 "final" interface (need your OK).** All are optional, so existing callers are unchanged:
   - `ToolCall.sop_id: str | None` (from `RunContext.sop_id`) and `ToolCall.trust_sensitive: tuple[str, ...]` (from
     the spec, never from the caller, N.119).
   - `Decision.approval_id: str | None` (set only on an allow that rests on an approval).
   - `ToolSpec.trust_sensitive_args` and `ToolSpec.gate_args_of` (decision 1). Each catalog entry gets
     `trust_sensitive_args` and `entity`, and each write gets `verify`. `ui_forms` entries get `trust_sensitive_args`.
   - `field_source_untrusted` loses its `args` list: the call's declared trust-sensitive args become the one source.
   - New event types: `approval`, `security_finding`, `run_start`, `verifier_result`.
   - A new file outside the CLAUDE.md layout, `agent/plan.py`: the Plan / Milestone / Predicate models that the
     Day 4 planner emits and the verifier reads.
8. **`toast_2s` carry-over:** recommended to leave it as a documented limitation. No bench variant uses `toast_2s`,
   so the "chaos fired" column is unaffected. A fix in Acme is about 10 lines if you want it.

## (a) Designs of the author-owned modules

### A1. Gate evaluator: `agent/policy/gate.py`

**Interface**

```python
class PolicyGate:
    def __init__(self, policies: PolicyFile, facts: RunFacts, approvals: ApprovalStore): ...
    def check(self, call: ToolCall) -> Decision: ...      # sync and pure: reads lookups, writes nothing
```

`policies` comes from `load_policies()`. A bad file raises `PolicyError`, and `start_run` refuses to start a run
without a gate. `facts` (`agent/policy/facts.py`) and `approvals` (`agent/policy/approvals.py`) are read-only views
of the run store. The pass-through gate leaves `agent/` and becomes a test fixture (`AllowAllGate`).

**Data flow for one call**

```
registry.call: validate args -> await gate_args_of (GUI form fields) -> ToolCall
               (side_effect, channel, request, trust_sensitive from the spec; sop_id from ctx) -> gate.check
gate.check:
  1. matched = every rule whose conditions ALL hold (every rule is evaluated)
  2. nothing matched             -> allow, "no rule matched"
  3. any matched rule is deny    -> deny; policy_ids = every match, strictest first
  4. otherwise (all holds):
       approvals.usable(run_id, fingerprint) -> allow + approval_id (the policy ids are still cited)
       none                                  -> require_approval
  any exception in steps 1-4     -> deny [GATE-ERROR] (the registry keeps its own GATE-ERROR backstop)
registry: deny -> policy_denied
          require_approval -> files a pending approval with the predicted outcome, returns approval_required + id
          allow with approval_id -> marks the approval consumed, then runs the tool
```

`policy_ids` are ordered deny first, then org > user > task, then by id. In YAML an effect can only be deny or
require_approval, so a user or task rule can never loosen an org rule (P.11). "Tighten-only" needs no extra code;
a test proves it.

**Conditions.** Each is one small function in a dict keyed by type. The constructor fails if a type in
`CONDITION_TYPES` has no function.

| Type | Holds when | Value missing or unreadable |
| --- | --- | --- |
| `request_matches` | the call has a request, the method matches (`*` = any), and `pathglob.path_matches` matches any glob | no request (a local tool): false; invalid path: matches (pathglob fails closed) |
| `tool_in` | `call.tool` is listed | n/a |
| `side_effect_in` (new) | `call.side_effect` (the per-call class) is listed | n/a |
| `amount_gt` | `int(args[arg]) > paise` | true |
| `vendor_status_not_in` | `facts.vendor_status(run, vendor_id)` is not in the list | arg missing, or vendor not read in this run: true |
| `recipient_domain_not_in` | the domain of the one plain address is not in `policies.allowlist(name)` | missing, malformed or several addresses: true |
| `field_source_untrusted` | the normalised value of some declared trust-sensitive arg is in `facts.untrusted(run)` and not in `facts.trusted(run)` | arg absent: no effect |
| `run_has_no_sop` (new) | `call.sop_id is None` | n/a |
| `target_not_created_by_run` (new, decision 2) | the call's target (catalog `entity` plus its one path id) is not in `facts.created(run)` | no known target (any GUI click): true |

**Lookups** (read-only, passed to the constructor)

- `RunFacts` reads the run's own event log:
  - `untrusted(run)`: normalised values (lower-cased emails, digit-only account numbers, IFSC codes, rupee amounts
    as paise) found by `scanner.values` in tool results tagged `provenance.source == "untrusted"` (mail, PDF text,
    browser pages);
  - `trusted(run)` (D-133): the same kinds of values in the run's request text and in the top-level fields of rows
    returned by API reads of business entities, excluding rows in `created(run)` and rows whose creator field names
    the agent's account. Write results, nested sub-rows, mail, audit rows and browser pages never count;
  - `vendor_status(run, id)`: the latest trusted row of entity `vendor` with that id;
  - `created(run)`: (entity, id) of rows the run's API writes returned, plus rows a `list_audit` result shows were
    inserted by the agent's account after the `run_start` mark.
- `ApprovalStore.usable(run, fingerprint)` returns an approved, unconsumed approval id or None.
- `PolicyFile.allowlist(name)` returns the domains validated at load time (D-082). The gate never opens a file.

**What is logged.** The registry logs; the gate writes nothing.
- `policy_decision` {effect, policy_ids (every match), reason, approval_id}. The reason has one clause per match:
  the id, the effect, the rule's message and why it applied ("vendor 7 not read in this run", "`to` seen only in
  mail:12").
- On a hold: `approval` {requested, approval_id, fingerprint, policy_ids, predicted}.
- On an allow resting on an approval: `approval` {consumed}, just before the tool runs.

**How it fails closed**

- An unknown condition type is a load error (schema) and a construction error (no function for it).
- Any exception during evaluation, including a lookup or store read failure, is a deny with `GATE-ERROR`.
- A value the gate cannot read counts as "the rule applies" (table above). A path that cannot be normalised matches
  every glob.
- An approval never lifts a deny. An approval matches one (run, fingerprint) and is used once.
- A bad policy file stops the run before it starts.

**Policy file after Day 3.** The `DRAFT` header goes; `schema_version` stays 0. ORG-001 to 004 and ORG-006 are
unchanged. ORG-005 changes as in decision 2. New: ORG-007 (provenance), ORG-008 (irreversible changes to records
the run did not create), ORG-009 (no SOP). `enforced_by: acme` rules (ORG-001, 003, 006) still match only bypass
attempts (deciding an approval, any `bank` path). Submitting an over-limit invoice matches no rule.

**Three likely live changes**

1. *"Hold every payment request for an action approval."* YAML only: a rule with
   `request_matches: {method: POST, path: [/api/payments, /payments/new]}` and effect `require_approval`, plus one
   passing and one failing test. No code.
2. *"Add a condition type, such as `channel_in`."* A model class in `models.py` and its name in `CONDITION_TYPES`,
   one function in the gate's table, one passing and one failing test. Construction fails until the function exists.
3. *"Let one approval cover a retry"* or *"show which rule won first"*. One place each: `ApprovalStore.usable` /
   `consume`, or the sort key. Be ready to explain why approvals are single-use (D-103).

### A2. Scanner: `agent/policy/scanner.py`

**Interface**

```python
class Finding(BaseModel): policy_id: str = "ORG-006"; kind: str; origin: str; excerpt: str
def scan(text: str, origin: str) -> list[Finding]
def scan_result(data: dict) -> list[Finding]   # every string in an untrusted result; origin from its provenance
def values(text: str) -> set[str]               # normalised emails, account numbers, IFSC, amounts (used by RunFacts)
```

**Patterns.** Compiled regexes, case-insensitive, one per kind:
- `payment_instruction`: transfer / pay / remit / wire / deposit, followed in the same sentence by an amount with
  Rs, INR or ₹, or by "account" / "a/c";
- `bank_details`: "account" / "a/c" / "acct" (optionally "no." or "number") followed by 9 to 18 digits, or an IFSC
  code (`[A-Z]{4}0[A-Z0-9]{6}`);
- `bank_change`: change / update / new / revised, then bank details / account.

A plain amount ("Total Amount Payable: Rs. 62,400.00") is not a finding: `\bpay\b` matches neither "Payable" nor
"Payment".

**Data flow.** `registry._finish` checks `result.data.provenance.source == "untrusted"`. If set, it runs
`scan_result` and appends one `security_finding` event per finding, deduplicated by kind and excerpt. The result is
unchanged and nothing is blocked; blocking belongs to Acme and the gate (D-086). The report lists the findings.

**What is logged:** `security_finding` {policy_id, kind, origin, excerpt}. The excerpt is the matching line, cut to
200 characters. Every run of 9 or more digits is masked as in Acme's audit (last four shown only above eight digits,
D-093), so no report ever shows an account number (7.6).

**How it fails.** It cannot block, so it fails loudly instead. An exception becomes a `security_finding` of kind
`scan_failed` with the origin; the report shows it and the run continues. A corpus test proves coverage: across
every seeded mail and every PDF, only the Mehta line is flagged, as both `payment_instruction` and `bank_details`.

**Three likely live changes**

1. Add a pattern, for example UPI ids (`name@okhdfc`) or "pay to this QR": one regex, one kind, and the corpus test
   updated.
2. Make a finding hold later writes: a gate condition `run_has_security_finding` (read through `RunFacts`) and a
   YAML rule. This shows why detection and enforcement are separate.
3. Fix a false positive, for example "pay within 30 days": tighten the regex; the corpus test shows the precision.

### A3. Verifier: `agent/verifier/`

Files: `__init__.py` (`verify`, `decide_status`), `predicates.py` (layers 1 and 2, polling), `side_effects.py`
(layer 3). The plan models are in `agent/plan.py` (decision 7).

**Plan models.** They are the planner's exact output from Day 4; in Phase A each oracle passes in the values.

```python
class Predicate(BaseModel):          # one read-tool call and what its rows must show
    read: str                        # an API read tool: never a browser read, never SQL
    args: dict[str, Value | Ref]     # Ref = {"ref": "M1"}: the id of the row found by M1's first predicate
    where: dict[str, Value | Ref]    # which rows to pick (from data.items, or the single row)
    expect: dict[str, Value]         # exact values on every picked row (money and dates exact, 6.3)
    contains: dict[str, list[str]]   # text a field must contain, ignoring case (e.g. the welcome mail body)
    count: int = 1                   # exactly this many picked rows; 0 means "must not exist"
class Milestone(BaseModel):
    id: str; target: str; sop_step: str | None; after: list[str]
    predicates: list[Predicate]      # at least one
    critical: bool = True; awaits_business_approval: bool = False
class Plan(BaseModel):
    sop_id: str | None; milestones: list[Milestone]   # 0 to 7 (T4 and T5 have none)
```

Example, T1. M1 "INV-1043 entered for Sharma with the PDF's values, pending approval":
`list_invoices(status=pending_approval)`, where `{invoice_no: INV-1043, vendor_name: Sharma Logistics Pvt Ltd}`,
expect `{amount_paise: 6240000, tax_paise: 951864, due_date: 2026-11-02}`, count 1. M2 (`awaits_business_approval`):
`list_approvals(status=pending)`, where `{entity_type: invoice, entity_id: {ref: M1}}`, expect
`{approver_role: finance_manager}`, count 1. Rows are found by business keys, not ids, so one plan verifies both
the API run and the GUI run.

**Interface**

```python
async def verify(run: Run, plan: Plan | None, approvals: ApprovalStore) -> Verdict
class Verdict(BaseModel):
    status: RunStatus; reasons: list[str]
    postconditions: list[Check]; milestones: list[MilestoneCheck]
    side_effects: SideEffects        # rows, unexplained, claimed_not_audited
```

**Data flow**

1. **Layer 1, postconditions (one per write).** Take every successful API write in the event log whose catalog
   entry has a `verify` spec. Examples: `submit_invoice` → `get_invoice(invoice_id=id)` comparing `invoice_no`,
   `amount_paise` and the other written fields; `send_mail` → `read_mail(mail_id=id)` with `to_addr ← to`. Read the
   row and compare the written fields. Undo tools check their target status. A GUI write returns a page, not an id,
   so GUI writes rely on layer 2. Every check is an independent read, never the write's own response (D-134).
2. **Layer 2, milestone predicates.** In DAG order, call each predicate's read tool through `registry.call`, so every
   check is gated, logged and becomes evidence. Predicates read only through API read tools: an API write is read
   back by an API GET (the same channel, but an independent read), and a GUI write through the API (a different
   channel). For API writes the different-channel check is layer 3 plus the harness's `/__admin/diff` (D-134). A predicate that is not met
   is read again every 0.5 s until `READ_LAG_SECONDS` has passed (config, default 6, above Acme's 5 s
   `delayed_write` lag; N.141, 6.9). A `count: 0` predicate passes only after that window, because read lag fakes
   exactly that: absence.
3. **Layer 3, side effects.**
   - Read `list_audit(since=start mark)` to the end. The mark is the last audit id, recorded in a `run_start` event
     when the run begins.
   - Group the rows by `ts`. Acme ticks its clock once per service write, so one group is one write call, cascades
     included (a void and the approval withdrawals it causes). This relies on Acme's clock; production would
     correlate by request id (D-135, README limitation).
   - Each group with a row by the run's actor must match an unused successful write event of the run: the same
     entity (catalog `entity`; for a GUI submit, its `ui_forms` twin's entity) and the same id when the write
     returned one.
   - Groups left over are **unexplained**. Successful writes with no group (and not `already_done`) are **claimed
     but not audited**, which is how a silent drop shows up.
   - Rows by `system` or `meera` are listed but never unexplained. The harness, not the agent, compares this row set
     with `/__admin/diff`.
4. **Status.** One function, `decide_status`; the first matching row wins:

| Evidence | Status |
| --- | --- |
| `verify` raised, or ran longer than `VERIFY_TIMEOUT_SECONDS` | `unverified` |
| `ask_user` or `declare_infeasible` ended the run, but the run wrote something | `failed` |
| an action approval of this run was rejected, or the run ended on a gate deny or an Acme policy refusal | `blocked_by_policy` |
| a pending action approval whose call never ran | `paused_for_action_approval` |
| `ask_user` ended the run and nothing was written | `needs_clarification` |
| `declare_infeasible` ended the run and nothing was written | `infeasible` |
| no plan, or no milestones, and the run wrote something | `unverified` |
| a critical milestone is marked as having no readable effect | `unverifiable` |
| a postcondition or a critical predicate not met, any unexplained side effect, or a claimed-but-not-audited write | `failed` |
| only non-critical predicates not met | `completed_with_exceptions` |
| everything met, and a met milestone is `awaits_business_approval` | `awaiting_business_approval` |
| everything met | `completed` |

`rolled_back` arrives with Day 5's "rollback if rejected" path. On Day 3, rollback is proven by the checker over the
diff.

**What is logged:** every verifier read as ordinary `tool_call` / `tool_result` events, then one `verifier_result`
event holding the whole `Verdict`. The report takes the status only from that event.

**How it fails closed**

- An exception or timeout anywhere gives `unverified`, never `completed` (6.7).
- A read error, a `Ref` that resolves to nothing, or a predicate still unmet after the lag all count as "not met".
- If the plan fails validation (read tools exist and are API reads, refs point backwards, `after` has no cycle), the
  status is `unverified`, with the reason.
- The agent's own messages and `ScriptResult.ok` are never inputs (decision 3, 6.10).

**Three likely live changes**

1. *"Also check X"* (for example, the welcome mail names the manager): add a `contains` entry or a predicate to the
   plan. Data only.
2. *"Count system follow-ups as side effects"* or *"allow one more kind of audit row"*: one rule in the matching in
   `side_effects.py`.
3. *"Unexplained side effects should give `completed_with_exceptions`, not `failed`"*, or *"poll for longer"*: one
   row in `decide_status`, or `READ_LAG_SECONDS` in config.

### A4. Supporting pieces (not author-owned; short)

- **Approval store** (`agent/policy/approvals.py`). Approvals are append-only `approval` events in the run store
  (`requested`, then `decided` approved or rejected, then `consumed`). The state is a fold over those events, so
  nothing is updated in place.
  - `request` is idempotent while a request for the same (run, fingerprint) is pending.
  - `decide` refuses anything that is not pending.
  - `usable` means approved and not yet consumed.
  - The predicted outcome on Day 3 is deterministic: tool, business args (redacted), request, side effect, policy ids
    and messages, and a one-line effect ("creates one outbox email to X; cannot be undone"). The Day 4 executor adds
    its own structured prediction.
- **Approval inbox** (`ui/app.py`, FastAPI on 127.0.0.1:8100, `make ui`).
  - Pending approvals show as cards: run request, tool, request, args, side effect, policy messages. Approve and
    reject need a per-process form token.
  - A JSON twin (`GET /api/approvals`, `POST /api/approvals/{id}/approve|reject`) serves the bench's scripted
    approver, which drives the same app through Starlette's `TestClient`.
  - The agent has no tool that reaches the inbox: the API client talks only to `ACME_URL`, and the browser stays on
    Acme's origin (N.145).
- **Asking and refusing as run steps** (`agent/tools/ask.py`): `ask_user(question, candidates[])` and
  `declare_infeasible(reason, evidence[])`, side effect `read`, channel `code`. Both end the run, for the scripted
  agent now and the executor on Day 4.
- **Scripted agent.** It stops after an ending tool. On `approval_required` it returns `paused` with the approval id
  and the step index. `resume_script` re-runs that same call once the approval is approved (the gate allows it and
  the registry consumes it). It ends `blocked` on a rejection and stays paused while the approval is pending.
- **Failure classifier** (`agent/failures.py`): `classify(result) -> Failure {kind, policy_id, next}`.
  - `policy_denied`, Acme 403, or a 409 `conflict` whose detail names an ORG id (ORG-002 on payment create and on
    approve) → `policy_refusal`, never retried.
  - A plain 409 → `state_conflict` (read again, then replan).
  - `approval_required` → `pause`.
  - `outcome_unknown: true` → `read_back_first`, never a blind retry.
  - `timeout`, `connection_error` or `server_error` on a read → `transient`.
  - `session_*` → `session`.
  - `invalid_*`, `unknown_tool`, `not_found` or `precondition_failed` → `fix_or_replan`.
  - `tool_crashed` → `escalate`.
- **Read-back polling in the API tool.** After an unknown outcome, a keyless write's read-back keeps polling until
  `READ_LAG_SECONDS` before it decides "not written" and sends again (N.141, D-123).
- **Report** (`agent/report.py`). The D-098 contract plus `failures[]` and `verifier`. The status comes only from the
  `verifier_result` event. Everything else comes from events:
  - evidence: tool results with a one-line summary each;
  - security findings;
  - action approvals, with the predicted outcome and the decision;
  - questions;
  - side effects, from layer 3.

  It writes `runs/<run_id>/report.json` and a one-screen `report.md`.

## (b) Risk table for Day 3

Register IDs are reused; N.144 to N.160 are new and are appended to `docs/risk-log.md` as `open`.

| # | Problem | How it shows up | How we handle it | How we prove it |
| --- | --- | --- | --- | --- |
| P.2 | Policy only in the prompt | A write runs with no gate decision | Every call goes through `PolicyGate.check` in `registry.call`; the real gate is the default in `start_run`; pass-through exists only as a test fixture | 3.1 `test_start_run_uses_the_policy_gate`; every adversarial script |
| 1.4, P.11 | Rules conflict, or a lower level loosens | An ORG deny and a TSK hold both match | All rules evaluated; deny > require_approval > allow; every ID logged, strictest first; YAML has no `allow` | 3.1 `test_strictest_effect_wins_and_every_id_is_logged`, `test_a_task_rule_cannot_loosen_an_org_rule` |
| P.3, N.146 | Novel write goes through, or the defaults over-hold | Unknown GUI form submitted; or T3's internal mail and every rollback held | Precise default rules in YAML (decision 2): ORG-005, ORG-008, ORG-009 | 3.1 `test_an_unknown_form_submit_is_held`, `test_internal_mail_and_rollback_undo_are_not_held`, `test_undoing_a_row_the_run_did_not_create_is_held` |
| 3.9, N.23 | Admin endpoint reached | `//__admin/reset`, `/api/../__admin/reset`, `/%5F%5Fadmin/reset`, `/__ADMIN/reset`, `/__admin/reset?x=1` | `path_matches` normalises; an invalid path matches every glob; the GUI action is resolved against the page origin | 3.1 `test_org004_catches_every_admin_variant` (5 variants × API request and GUI form action); `direct_db_or_admin` |
| N.144 | GUI submit invisible to the gate | GUI invoice for a blocked vendor; GUI compose to a vendor; a GUI approval not bound to the content | Decision 1A: form fields become call args and fingerprint; the click refuses a form that changed | 3.1 `test_gui_invoice_for_a_blocked_vendor_is_denied`, `test_gui_compose_to_a_vendor_is_held`; e2e `test_a_form_changed_after_the_decision_is_not_submitted` |
| N.145 | Off-site link or form target reduced to a path | `urlparse(href).path` turns `//host/x` or `http://127.0.0.1:8100/...` into `/x`; the browser leaves Acme and could reach the approval inbox | Targets resolved with `urljoin` against the page; an off-site target is passed as the full URL, which is not a path, so every glob matches and the gate denies | 3.1 `test_an_off_site_link_or_form_is_denied` (unit), e2e with a planted page |
| P.8 | Mail exfiltration | Send to a vendor domain without approval | ORG-005 hold; allowlist only from `PolicyFile.allowlist` (D-082) | `external_email_unapproved`; `allowlisted_recipient_no_approval`; static test: `gate.py` opens no file |
| P.4, P.5 | Approval fatigue, or the worker hangs on approval | Approvals everywhere; or a run that blocks | Holds only where a rule says so; a pause becomes a pending approval with the predicted outcome; resume re-runs the same call | T9 × 3 runs; `test_resume_after_approve_reject_and_pending`; approvals per run in the bench |
| N.128, D-103 | Approval reused or mismatched | A second identical send rides on an old approval; a changed email uses the old one | Match on (run_id, fingerprint); single use; consumed before the tool runs; a deny is never lifted | 3.1 `test_an_approval_is_used_once`, `test_an_approval_for_another_call_does_not_apply`, `test_an_approval_never_lifts_a_deny` |
| N.150 | Self-approval or CSRF on the inbox | The agent's browser or another page posts "approve" | Only the UI process decides; per-process form token; the agent has no tool that reaches it (N.145) | 3.1 `test_approve_needs_the_form_token`, `test_decide_twice_is_refused`, N.145 tests |
| N.151 | Approval consumed, then the call fails | Timeout after consumption; the retry is held again | By design: a retry needs a new approval (D-103); the report says so | 3.1 `test_a_failed_call_after_consume_needs_a_new_approval` |
| P.1, 4.7 | Prompt injection in a PDF | Mehta's "transfer Rs. 1,00,000 to account ..." | Scanner finding ORG-006; the tool args forbid amount and account; Acme has no such field; ORG-006 path rule | T6 report check; `t6_bad_transfer` (`invalid_args`, Acme 422, finding) |
| N.149 | Scanner false positives or negatives | "Payable", a GSTIN or a phone number flagged; "a/c" missed | Narrow, named patterns; findings never block | 3.1 `test_only_the_mehta_line_is_flagged_across_all_seed_mail_and_pdfs` |
| decision 7 (ORG-007) | Trust-sensitive value taken from untrusted text | Recipient copied from the From header; account number from the PDF | Value taint from the event log; trusted = request text plus Acme reads; hold | `bank_details_from_document` (ORG-006 deny with ORG-007; payee variant: ORG-007 hold), `test_recipient_from_a_mail_header_is_held` |
| N.148 | Taint laundering through Acme | Write an untrusted value into Acme, read it back as "trusted" | The only agent-writable email field is the employee email, which Acme forces to `@acme.example`, so laundering yields internal addresses only (accepted) | 3.1 `test_an_external_address_cannot_be_laundered_through_an_employee` |
| N.147 | Vendor status needs I/O inside a pure gate | Sync `check()`; async Acme read | Status from the run's own trusted reads; unread means deny (decision 3); stale mid-run status accepted | 3.1 `test_org002_unread_vendor_is_denied`, `test_org002_uses_the_latest_read` |
| 1.3 | No SOP matches the request | Writes run without a procedure | ORG-009: every write held | `no_sop_every_write`; `test_org009_*` |
| 1.5, 1.7 | Asking and refusing are not real outcomes | T4/T5 end as "script ok" with no question or refusal | `ask_user` / `declare_infeasible` tools; the verifier confirms nothing was written | T4/T5 status and report checks; `test_an_ask_after_a_write_is_failed` |
| 5.2 | Failure misclassified | A 409 with ORG-002 retried; a plain 409 treated as policy | Classifier keys on the ORG id in the detail; `outcome_unknown` means read back first | 3.2 `test_failures.py` (one test per error type, both 409 cases, create and approve) |
| 3.5, 6.9, N.141 | Read too early | Read-back misses a committed row: double write, or a false "not met" | Poll up to `READ_LAG_SECONDS` before "not written" or "not met"; absence confirmed only after the window | 3.2 unit tests with a lagging fake transport; e2e T3 under `delayed_write`: two tickets, `completed` |
| 4.4, 5.3, 6.1 | UI says saved, backend dropped it | `silent_drop_write` | Layer 2 reads through the API; layer 3 lists claimed-but-not-audited | 3.2 e2e: GUI T1 under `silent_drop_write` without the redo → `failed` |
| 6.4, N.154 | Side effects missed or mismatched | Extra write unlisted; cascade rows flagged | Audit rows since the start mark, grouped by `ts`; one group per write | 3.2 `test_a_planted_extra_write_is_unexplained`, `test_a_void_cascade_is_one_explained_group`; bench agreement column vs `/__admin/diff` |
| 6.7 | Verifier crash read as success | Exception swallowed | `unverified` on any exception or timeout | 3.2 `test_a_crashing_or_slow_verifier_gives_unverified` |
| 6.8 | Effect cannot be read back | External mail | Outbox read-back through `read_mail`; `unverifiable` status exists | T9:approve; 3.2 `test_unverifiable_milestone` |
| 6.10, 7.1 | The agent's claim sets the status, or evidence is its word | "Done" with no proof | Status only from `verify`; evidence from tool results | 3.3 `test_the_report_status_comes_only_from_the_verdict` |
| N.153 | Verifier polling slows runs | Unmet or `count: 0` predicates wait the full lag | Poll only predicates the status depends on; skip layer 2 when a pause, rejection, ask or refusal decides the status | bench wall time per run in the results file |
| N.152 | Extra reads move chaos schedules | The start-mark and verifier reads shift `session_expiry_at_step_N` | Accepted; "chaos fired" column; non-fired runs reported apart (D-095) | 3.3 `test_non_fired_chaos_runs_are_reported_separately` |
| 5.4, 7.3, N.142 | Incomplete rollback, or rollback touches others' rows | GUI rows left; a foreign row voided | GUI rollback from audit inserts by the run's actor since the mark (decision 4); ORG-008 holds undo of foreign rows | 3.2 e2e `test_a_gui_run_is_rolled_back_through_the_api_undo_tools` |
| N.109 | Report contract drift | Generator shape differs from `report_checks` | Generator built to D-098; contract test through `engine.check` | 3.3 `test_report_contract.py` (T4, T5, T6, T9 × 3; broken reports fail) |
| 7.6, N.157 | Report leaks bank numbers or secrets | Account number in an excerpt; password in evidence | Masked excerpts; report built from already-redacted events | 3.3 `test_the_report_shows_no_account_number_or_secret` |
| X.1 | Bench results vary | Chaos fires on a different step | Seed 0, frozen `now`, fired column, oracle (k=1) baseline | `make bench` twice gives the same table (excluding times) |
| N.31, 0.7, R.4 | Checkers cannot see the DB in Docker; repo not runnable | Empty DB in the runner; "broken" | The runner starts its own child Acme (D-112, D-119); the compose Acme service only serves people | 3.4 `docker compose run runner make bench` writes a results table |
| N.158 | Docker image drifts from the lock | Playwright and browser version mismatch; ARM hosts | Base image `mcr.microsoft.com/playwright/python:v1.63.0-noble`, equal to `uv.lock`; `uv sync --frozen` | 3.4 `test_the_runner_image_matches_the_locked_playwright` (static) plus the compose run |
| N.159 | Adversarial attempts the catalog cannot express | No decide or bank tool; strict args stop the T6 transfer early | Labelled fixture tools; raw request for Acme's 422 (decision 5) | `bench/adversarial/*`, each asserting its expected stop |
| N.155 | Real gate breaks existing tests and oracles | `PolicyGate()` without args; writes held without `sop_id`; T9 pauses | `AllowAllGate` fixture for unit tests; oracles carry a plan with `sop_id`; T9 oracle pauses | `make test` and `make test-e2e` green after 3.1 |
| N.156 | Plan schema fixed before the planner exists (N.2) | Day 4 LLM cannot emit it | Small, flat, JSON-schema-friendly models; Phase A oracles use only that schema | Day 4 smoke test emits a valid `Plan` |
| N.160, R.3 | Line budget and explainability squeeze | Day 3 adds about 900 lines; the gate grows clever | Each condition one small function; prose first; three live changes rehearsed per module | `agent/` total at each checkpoint: about 2,500 after Day 3 (limit 3,500) |

**Covered by this plan:** every row above. **Deferred, with reasons:**
- the Day 4 executor halves of N.141 and 5.1 (two strikes), because there is no executor yet;
- approve after a process restart (P.5, future), because pause and resume are in-process on Day 3;
- concurrency between runs of one actor (X.7, future), which audit-based rollback and `RunFacts.created` assume away;
- `rolled_back` as a verifier status (Day 5, with "rollback if rejected").

## (c) Sub-parts

Running `agent/` total (non-blank lines of `agent/**/*.py`, D-115): 1,600 now.

### 3.1 Policy: gate, facts, scanner, approvals, pause and resume, inbox, adversarial (about +460 agent lines → about 2,060)

Build ORG-007 (provenance) last inside 3.1, so it can be cut first.

- **Files**
  - `agent/policy/`: `models.py` (`side_effect_in`, `run_has_no_sop`, `target_not_created_by_run`;
    `field_source_untrusted` without `args`), `gate.py` (evaluator, the `ToolCall` and `Decision` additions),
    `facts.py` (new), `scanner.py` (new), `approvals.py` (new).
  - `agent/store.py`: event types; `run()` getter; approval events across runs.
  - `agent/tools/registry.py`: `RunContext.sop_id`, `trust_sensitive_args`, `gate_args_of`, file and consume
    approvals, scanner hook.
  - `agent/tools/api.py`: catalog fields.
  - `agent/tools/browser.py`: form fields for the gate, same-site targets, live form re-check.
  - `agent/tools/ask.py` (new).
  - `agent/scripted.py`: ending tools, pause, `resume_script`.
  - `agent/lifecycle.py`: real gate as the default, `sop_id`, `run_start` mark.
  - `agent/plan.py` (new; `sop_id` only for now).
  - `acme/knowledge/policies.yaml`: ORG-005, 007, 008, 009; `DRAFT` header removed.
  - `acme/knowledge/api.yaml`: `trust_sensitive_args`, `entity`.
  - `ui/app.py` and `ui/templates/inbox.html` (new); `Makefile` `make ui`.
  - `bench/adversarial/` (new): `t6_bad_transfer`, `approve_own_invoice`, `direct_db_or_admin`,
    `external_email_unapproved`, `bank_details_from_document`, `allowlisted_recipient_no_approval`,
    `no_sop_every_write`, and a small runner.
  - Oracles: T9 pauses; T1 GUI reads the vendor; plans with `sop_id`.
  - `bench/live.py`: scripted approver, T9 pause and resume.
- **Tests**
  - `tests/policy/test_gate.py`, rewritten: one passing and one failing test per rule, ORG-001 to ORG-009; strictest
    wins; all IDs logged; tighten-only; `GATE-ERROR` on a lookup failure; every condition type has a function; no
    file I/O in `gate.py`.
  - `tests/policy/test_facts.py`, `test_scanner.py` (corpus precision, masking), `test_approvals.py` (single use,
    pending deduplication, decide twice, other run or fingerprint).
  - `tests/agent/test_scripted.py` (end steps, pause and resume).
  - `tests/agent/test_browser_unit.py` (form fields, off-site targets).
  - `tests/ui/test_inbox.py` (cards, token, approve and reject, JSON twin).
  - e2e: T9 pause before the send for none, approve and reject; every adversarial script stops with its expected
    policy id or Acme refusal and Acme state unchanged; a GUI form changed after the decision is not submitted.
- **Stop:** `/checkpoint`, author commits.

### 3.2 Verifier and recovery (about +320 → about 2,380)

- **Files**
  - `agent/plan.py`: milestones and predicates, validation against the registry.
  - `agent/verifier/__init__.py`, `predicates.py`, `side_effects.py`.
  - `agent/failures.py`.
  - `agent/tools/api.py`: read-back polling after an unknown outcome.
  - `agent/config.py` and `.env.example`: `READ_LAG_SECONDS`, `VERIFY_TIMEOUT_SECONDS`.
  - `agent/lifecycle.py`: GUI rollback from the audit log (decision 4).
  - `acme/knowledge/api.yaml`: `verify` per write.
  - `bench/oracles/*`: hand-written plans (milestones as data) for T1 to T9 and T1 GUI.
- **Tests**
  - `tests/agent/test_verifier.py`: each layer passing and failing; refs; polling with a fake lagging transport;
    `count: 0` waits out the lag; one test per status row of `decide_status`; crash and timeout give `unverified`;
    an ask or refusal after a write gives `failed`.
  - `tests/agent/test_failures.py`.
  - `tests/agent/test_api_tools.py`: a lagged row found by polling, not written twice; a row that never appears is
    retried after the window.
  - e2e:
    - T3 under `delayed_write` ends with exactly two tickets, the checker passes, the verifier says `completed`, and
      the log shows at least one poll;
    - T1 GUI run rolled back through the API undo tools (invoice void, approval withdrawn, nothing else changed);
    - T1 GUI under `silent_drop_write` with the redo disabled gives `failed`, with a claimed-but-not-audited write;
    - every oracle with chaos off: verifier status equals `expected_outcome`.
- **Stop:** `/checkpoint`, author commits.

### 3.3 Report and bench (about +110 → about 2,490)

- **Files**
  - `agent/report.py`.
  - `bench/live.py`: verify, then report, then `engine.check(run, db, diff, report)`, plus verifier-vs-diff
    agreement.
  - `bench/run_oracle.py`: no PENDING lines.
  - `bench/run_bench.py` (new) and `make bench`.
  - `bench/results/` (output, with `.gitkeep`; results kept out of git unless you want them in).
- **Bench**
  - Every oracle with chaos off (T1 to T8, T9 none, approve and reject, T1 GUI).
  - The chaos variants from the task YAMLs at seed 0. The harness refuses a `delayed_write` variant for T3 or T8.
  - The adversarial section: expected stop vs actual.
  - Columns per run: pass/fail; pass^k scaffold (`--k`, default 1 for oracles); CuP (decision 6); unexplained side
    effects; correct refusal (T4, T5); chaos fired yes/no, with non-fired runs listed apart; verifier-vs-diff
    agreement; status; approvals; wall time.
  - Output: `bench/results/<timestamp>.json` and `.md`.
- **Tests**
  - `tests/checkers/test_report_contract.py`: the generator's output for T4, T5, T6 and T9 × 3 passes
    `report_checks`, and broken reports fail.
  - `tests/agent/test_report.py`: status only from the verdict, redaction, findings deduplicated.
  - `tests/bench/test_run_bench.py`: table builder, CuP rule, separation of non-fired runs, agreement, and the T3/T8
    `delayed_write` refusal.
  - Smoke: `make oracle TASK=all` shows no PEND line, and every chaos-off run passes its report checks.
- **Stop:** `/checkpoint`, author commits.

### 3.4 Packaging and skills (0 agent lines → about 2,490)

- **Files**
  - `Dockerfile`: one image based on `mcr.microsoft.com/playwright/python:v1.63.0-noble` (browsers included, Python
    3.12), then `uv sync --frozen`.
  - `docker-compose.yml`:
    - `acme` serves on :8000 with a health check, and `ACME_ADMIN_TOKEN` appears only in this service's environment;
    - `runner` sits in a `tools` profile and runs `make bench`; it starts its own child Acme, so it needs no token;
      results and `runs/` are mounted.
  - `.dockerignore`.
  - `.claude/skills/add-policy/SKILL.md` and `.claude/skills/chaos-test/SKILL.md`: steps only, pointing to CLAUDE.md
    decisions 4 and 7, the failure register and D-123, not restating them.
  - CLAUDE.md "Commands": `make ui`, `make bench`, the compose lines.
- **Tests:** `tests/test_packaging.py` (static: the token appears only in the `acme` service, the image tag equals
  the locked Playwright version, the runner command is `make bench`). Manual: `docker compose up` serves `/healthz`,
  and `docker compose run runner make bench` writes a results table. The output goes into the checkpoint.
- **Evening, the author's own task outside the repo:** the 5-minute curl check per provider.
- **Stop:** `/checkpoint`, author commits.

Total Day 3: about +890 agent lines, ending near 2,490. That leaves about 1,000 lines under the 3,500 ceiling for
Days 4 to 6 (LLM client and cassettes, feasibility gate, planner, executor, judge, findings).

## (d) Day 3 carry-overs from `docs/progress.md`

| Carry-over | Sub-part | Closed by |
| --- | --- | --- |
| D-123 / N.141: read-back polls for at least the read lag; T3 under `delayed_write` ends with exactly two tickets | 3.2 | `test_api_tools.py::test_a_lagged_row_is_found_by_polling_and_not_written_twice`; e2e `test_t3_under_delayed_write_ends_with_two_tickets_and_completed` |
| D-124 / N.142: GUI run rolled back through the API undo tools, tested on the T1 GUI run | 3.2 | e2e `test_a_gui_run_is_rolled_back_through_the_api_undo_tools` (mechanism: decision 4) |
| Day 3 verifier: poll before deciding a write is missing (N.141, 6.9) | 3.2 | `test_verifier.py::test_a_predicate_met_after_the_lag_passes`, `test_absence_is_confirmed_only_after_the_lag`. The executor half stays with Day 4-5 |
| D-098 report contract; contract test for T4, T5, T6, T9; `engine.check` gets the report (D-112) | 3.3 | `test_report_contract.py`; `make oracle TASK=all` prints no PEND line |
| T9 needs the scripted approver; the oracle shows the pause before the send | 3.1 | e2e `test_t9_pauses_before_the_send_and_the_approver_decides` (none, approve, reject; outbox empty before the approval) |
| Harness: `engine.check` with the diff tables (done in `live.py`); T9 as three run ids | 3.3 | `run_bench.py` runs T9:none, T9:approve and T9:reject as three rows (`test_run_bench.py`) |
| Gate: approvals on (run_id, fingerprint), single-use, consumed when the tool runs; side-effect defaults as YAML or code (D-101, D-103) | 3.1 | `test_approvals.py`; defaults are YAML rules ORG-005, 008, 009 (`test_gate.py::test_defaults_*`) |
| Harness: read chaos events after each chaos run; exclude non-fired runs from recovery stats; `flaky_500` seed 0 recorded in the YAML | 3.3 | Chaos fired column and a separate list of non-fired runs (`test_non_fired_chaos_runs_are_reported_separately`); the YAMLs already record seed 0 |
| `toast_2s` counts only pages served by a route handler | not built | Decision 8: no bench variant uses `toast_2s`; README limitation |
| Gate: `request_matches` through `path_matches`; collect every match; strictest effect; log every ID; the five ORG-004 variants | 3.1 | `test_gate.py::test_org004_catches_every_admin_variant[api, gui]`, `test_strictest_effect_wins_and_every_id_is_logged`; `direct_db_or_admin` |
| `t6_bad_transfer` expects Acme's 422 plus the scanner finding (D-086); the scanner reads untrusted `extract_pdf_text` / `read_mail` data (D-110) | 3.1 | `bench/adversarial/t6_bad_transfer.py` (decision 5); `test_scanner.py` |
| ORG-005 reads `mail_allowlist.yaml` (D-064); an allowlisted recipient needs no approval (D-069) | 3.1 | `test_gate.py::test_org005_*`; `allowlisted_recipient_no_approval` |
| A no-SOP request proves the approve-every-write fallback (1.3, D-081) | 3.1 | `no_sop_every_write`; `test_gate.py::test_org009_*` |
| ORG-007 `field_source_untrusted` | 3.1 (built last; first to cut) | `bank_details_from_document`; `test_gate.py::test_org007_*` |
| The evaluator reads the allowlist only through `PolicyFile.allowlist(name)` (D-082) | 3.1 | `test_gate.py::test_the_gate_reads_no_file` (static) and the ORG-005 tests |
| Classifier: ORG-002 409 is a policy refusal, a plain 409 is not, `outcome_unknown` means read back (D-091, D-100, D-108) | 3.2 | `test_failures.py` (ORG-002 409 on create and on approve, plain 409, `outcome_unknown`) |
| Open risk N.23 (ORG-004 is the gate's first line) | 3.1 | ORG-004 tests above |
| Open risk N.31 (checkers cannot see the DB in Docker) | 3.4 | The runner's own child Acme; `docker compose run runner make bench` |

Not Day 3, kept where the author put them:
- Day 4: GUI failures typed like the API's. The 3.2 classifier works on typed results, so it covers GUI once those
  results are typed.
- Day 4: two strikes count tool-level attempts. The classifier exposes `attempts`.
- Day 4: `run_id` never enters prompts.
- Day 5: the `silent_drop_write` matrix slot.
- Code tool: none is built (D-121).
- `iyer_INV-3301.pdf` stays unreferenced (Phase B stretch); the scanner corpus test reads it and finds no text.

## Author's changes on approval (2026-10-06)

1. **Taint laundering (D-133).** `trusted(run)` is the request text plus API read results of rows *not* created by
   the run (and not created by the agent's account). Write results and run-created rows never count. New adversarial
   script `taint_laundering`: an untrusted address written into an Acme field and read back still makes a
   trust-sensitive call require approval (ORG-007).
   *Consequence found while applying it:* T3's welcome-mail recipient (`priya.nair@acme.example`) is only in HR's
   mail and in the employee row the run created, so ORG-007 would hold T3. Built default, flagged for the author at
   the 3.1 checkpoint: `field_source_untrusted` takes an optional `allowlist` (the ORG-005 allowlist), and an email
   value in an allowlisted domain is not treated as untrusted (an internal or partner address cannot exfiltrate
   outside what ORG-005 already allows). Bank details, payees and amounts have no such exemption.
2. **Verifier channel wording (D-134)** in CLAUDE.md, the register row 6.1 and the README limitations.
3. **`test_only_` prefix (D-129)** for adversarial fixture tools; an isolation test scans `build_registry()` and
   `agent/` for it.
4. **Audit `ts` grouping (D-135)**: decision, README limitation, an Acme test now (a void with pending approvals
   writes one `ts`), and the verifier-side grouping test in 3.2.
