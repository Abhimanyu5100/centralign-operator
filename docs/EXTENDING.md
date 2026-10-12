# Extending the operator

Recipes for the changes a reviewer is most likely to ask for live. Each lists the files to touch and the test
that proves the change. The project's Claude Code skills in `.claude/skills/` (`add-policy`, `add-task`,
`chaos-test`) walk through the same steps.

After any change: `make test`. A change that reaches a model's prompt (an SOP, `policies.yaml`, `api.yaml`, the
prompts or the code that builds them) also fails the prompt-freeze test
(`test_no_prompt_input_changed_since_the_freeze` in [tests/agent/test_prompt_freeze.py](../tests/agent/test_prompt_freeze.py)).
That is deliberate: record the edit as a row in [decisions.md](decisions.md), update `PINNED`, and re-record the
cassettes it touches ([section 8](#8-re-record-cassettes)).

## 1. Add an SOP (a new kind of work)

1. Write `acme/knowledge/sops/<id>.md` in the format of [acme/knowledge/sops/README.md](../acme/knowledge/sops/README.md):
   front matter (`id`, `title`, `triggers`), then `### XX-1 Title` steps, each with exactly `- Target:`,
   `- Source:` and `- Ask when:`.
2. Targets are states, never clicks. A step that writes names its `POST` in `Source` (that makes it a write step
   the plan must cover, D-185); a step that applies only sometimes says "when ..." in its title.
3. Name every endpoint the procedure uses in backticks (`GET /api/...`, `POST /api/...`): the executor offers only
   the tools the SOP names (D-180).
4. Keep it generic: no vendor, employee, invoice number or amount from the seed.

Proof: [tests/acme/test_knowledge.py](../tests/acme/test_knowledge.py) (`test_every_step_states_target_source_and_when_to_ask`,
`test_triggers_do_not_overlap_between_sops`, `test_every_endpoint_and_page_an_sop_cites_exists_in_acme`,
`test_every_policy_id_an_sop_cites_exists_in_policies_yaml`). Without an SOP, the request still runs, and ORG-009
holds every write for an approval.

## 2. Add a policy rule

1. Add a rule to [acme/knowledge/policies.yaml](../acme/knowledge/policies.yaml): `id` (`ORG-`, `USR-` or `TSK-`
   plus 3 digits), `level`, `enforced_by` (`acme` or `runtime`), `effect` (`deny` or `require_approval`; there is no
   `allow`), `when` (a list of conditions that must all hold) and `message`. An `acme` rule also lists `acme_check`
   entries naming the Acme code that enforces it.
2. Use the existing condition types: `tool_in`, `request_matches`, `amount_gt`, `vendor_status_not_in`,
   `recipient_domain_not_in`, `field_source_untrusted`, `side_effect_in`, `run_has_no_sop`,
   `target_not_created_by_run` ([agent/policy/models.py](../agent/policy/models.py)). **Adding a rule is a YAML
   edit.**
3. Only if none fits: add a condition type. That means a Pydantic model in `models.py` plus one small function in
   [agent/policy/gate.py](../agent/policy/gate.py) that returns `None` when it does not hold, or a short note when
   it does. An unknown type is a load-time error, so the file fails closed until the code exists.
4. Write one test where the rule fires and one where it does not ([tests/policy/test_gate.py](../tests/policy/test_gate.py)),
   and an adversarial script in [bench/adversarial/](../bench/adversarial/) if the rule stops an attack.

Proof: `test_the_real_file_validates_and_holds_org_001_to_009` (update its id list),
`test_every_acme_rule_maps_to_checks_that_exist_in_acme`, `test_an_unknown_condition_type_fails_closed`.

## 3. Add an API endpoint and its tool

1. Add the route in [acme/api.py](../acme/api.py), with its business rule in [acme/services.py](../acme/services.py)
   and an audit row for every write.
2. Add an entry under `tools:` in [acme/knowledge/api.yaml](../acme/knowledge/api.yaml). The operator generates the
   typed tool from it; no Acme path is ever written in `agent/` code (D-107). A write entry needs:
   - `side_effect`, `entity`, and `undo` (a reversible write) or `no_undo_reason`;
   - `read_back`, which tells a retry how to see that the write already happened (`new_row` or `target_state`);
   - `verify`, the read the verifier makes as the write's postcondition;
   - `trust_sensitive_args` for payees, recipients, bank details and amounts.

   For example, `create_it_ticket` declares its undo `cancel_it_ticket`, reads back new rows through
   `list_it_tickets` by `employee_id` and `type`, and is verified by `get_it_ticket`.
3. A web form the browser may submit goes under `ui_forms` with its side effect, so the gate knows what a click on
   it does; an unknown form is treated as an irreversible write.
4. Name the endpoint in the SOP step that uses it, or the executor will not offer it.

Proof: [tests/agent/test_catalog.py](../tests/agent/test_catalog.py) (`test_every_catalog_entry_is_a_real_acme_route_with_that_method`,
`test_every_acme_write_route_the_agent_may_use_is_in_the_catalog`, `test_every_write_says_how_a_retry_stays_safe`),
and `test_a_spec_that_breaks_the_contract_is_refused` for the registry contract.

## 4. Add a benchmark task

1. `bench/tasks/T<n>.yaml`: `id`, `request`, `category`, `seed`, frozen `now` (ISO with `+05:30`),
   `expected_outcome` (one of the canonical statuses in [CLAUDE.md](../CLAUDE.md)), `success` (SQL predicates, each
   returning one row equal to 1), `allowed_changes`, `report_checks`, optional `chaos_variants`. Schema:
   [bench/tasks.py](../bench/tasks.py).
2. A passing and a failing state for the checker, built through Acme's service layer
   ([tests/checkers/test_tasks.py](../tests/checkers/test_tasks.py)).
3. An oracle `bench/oracles/T<n>.py` with a hand-written plan and steps; `make oracle TASK=T<n>` must pass.
4. Run it with the LLM: `make run TASK=T<n>` (live, records cassettes), then `make run TASK=T<n> REPLAY=1`.

Proof: `test_every_run_has_a_passing_and_a_failing_case_and_writers_have_ui_and_extra_write_cases`; `make bench`
picks the task up automatically.

## 5. Add a chaos profile

1. Add the name to `PROFILES` in [acme/chaos.py](../acme/chaos.py) and implement it in Acme's request path. It must
   be seeded (the same seed fires the same requests), target only the `ops-agent` account, log when it fires, and
   be cleared by reset. Declare it in `UI_ONLY` if only the web UI can see it.
2. Tests in [tests/acme/test_chaos.py](../tests/acme/test_chaos.py) (it fires, it reproduces, reset clears it).
3. Add it to a task's `chaos_variants`; `make oracle TASK=T<n> CHAOS=<profile> CHAOS_SEED=0` shows whether it
   fired and how the failure was classified. A chaos run whose fault never fires fails the bench.

Proof: `test_flaky_500_same_seed_same_failing_requests_and_reset_clears` is the pattern to copy.

## 6. Change what the planner or judge sees

The prompts are `PROMPT` and `REPLAN` in [agent/planner.py](../agent/planner.py), `SYSTEM`, `GATHER` and `ACT` in
[agent/executor.py](../agent/executor.py), and `PROMPT` in [agent/verifier/judge.py](../agent/verifier/judge.py).
Prefer a code check (`plan_errors`, `tidy`) over a prompt sentence: it is testable and does not depend on the
model (D-200, D-217). Every prompt change is a decision row plus a re-record and a live re-measure: D-217's prompt
wording regressed on Flash-Lite and was reverted (D-220).

## 7. Debug a failed run

1. **Rerun and print the log:** `make run TASK=T3 REPLAY=1 EVENTS=1` (or live without `REPLAY=1`). The output
   shows the verifier's status and reasons, each checker line, and every event with its sequence number.
2. **Open the run viewer:** `make ui`, then `/runs/<run_id>` (bench runs: `RUN_STORE=runs/bench.db make ui`). The
   timeline marks policy decisions in yellow and security findings in red; each row expands to the full payload.
3. **Read the report:** `runs/<run_id>/report.json`. The fields that explain a failure:
   - `status_reasons`: which milestone or check failed;
   - `verifier.milestones[].checks[].detail`: what the read found, for example "0 matching row(s), expected 1";
   - `failures`: each failed tool call with its class and next step;
   - `replans` and `escalation`.
4. **Look at the plan:** the `plan` events hold every attempt with its `problems` and `tidied` notes. A milestone
   that can never be met usually means a wrong predicate; compare it with the records the verifier read.
5. **Reproduce without a model:** `make oracle TASK=T3` runs the perfect agent through the same gate and verifier.
   If the oracle passes, the problem is the model's plan or actions; if it fails, it is the tools, the gate, the
   verifier or the checker. Add `CHANNEL=gui HEADED=1` to watch the browser.
6. **Under chaos:** `make run TASK=T1 CHAOS=flaky_500 CHAOS_SEED=0 REPLAY=1 EVENTS=1`. The report's `recovered`
   lists the faults absorbed inside a tool.

## 8. Re-record cassettes

Cassettes are keyed on the role, the exact request body, the frozen `now` and an optional scenario scope
([agent/llm/cassette.py](../agent/llm/cassette.py)), so any change to what a model sees makes old recordings miss,
by design.

- **One task:** `make run TASK=T3` (live) writes to `cassettes/`; check it with `make run TASK=T3 REPLAY=1`.
  Chaos runs and T9's `reject` record under their own scope (D-209, D-211).
- **Everything, the way the committed set was made (D-216):**
  ```
  make bench AGENT=1 LIVE=1 K=3                                    # records under runs/cassettes-live/<timestamp>/a<k>/
  uv run python -m bench.keep_cassettes bench/results/<that>.json  # empties cassettes/, keeps one live run per row
  make bench AGENT=1                                               # replay, no key
  uv run python -m bench.keep_cassettes --prune bench/results/<replay>.json   # drop what the replay did not use
  ```
- A row with no passing attempt keeps its first attempt, so a measured failure replays as measured.
- `tests/e2e/test_agent_replay.py` replays the committed set (`make test-e2e`), and
  `test_no_configured_key_is_in_cassettes_or_runs` checks that no key ended up in a cassette.
