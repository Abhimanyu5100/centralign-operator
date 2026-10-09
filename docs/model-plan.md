# Model plan: running the agent on free API keys

Building happens in Claude Code on the Claude subscription. The **agent's own LLM calls** run on free
API tiers, starting on Day 4 (Phase B). Phases before that use no LLM calls at all. Free tiers change
without notice, so every number below must be re-checked on the provider's live limits page during the
author's **Day 3 evening manual check** and recorded here. That check is a 5-minute curl per provider
(keys plus one forced tool call), run outside the repo; no LLM code is written before Day 4.

## Measured on Oct 9, 2026 (Day 4 smoke test, `make smoke`, through `agent/llm/client.py`)

The author's curl check (Oct 9, outside the repo) confirmed keys and IDs; the 2.5 Gemini models return 404 to new
keys. The smoke test then ran per model: a plain call, a forced tool call, the tool result sent back (second turn,
which also exercises Gemini's thought signatures), JSON-schema output, and a long input.

| Model (env var) | Plain | Forced tool call | Tool round trip | JSON schema | Long input | Empty tool-call ids | Free-tier limits seen |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `gemini-3.5-flash` (`GEMINI_MODEL`) | ok 1.7 s | ok, args exact | ok | ok | ok (10,399 prompt tokens) | no | **5 RPM, 20 requests per day per model** (429 bodies: `GenerateRequestsPerMinutePerProjectPerModel-FreeTier` 5, `GenerateRequestsPerDayPerProjectPerModel-FreeTier` 20); no rate-limit headers |
| `gemini-3.5-flash-lite` (`GEMINI_LITE_MODEL`) | ok 0.9 s | ok | ok | ok | ok (10,399) | no | no 429 in about 15 requests; no rate-limit headers (limits not yet known) |
| `openai/gpt-oss-120b` (`GROQ_JUDGE_MODEL`) | ok 0.6 s | ok | ok | ok | ok (3,818) | no | headers: 1,000 requests per day, **8,000 tokens per minute** |
| `qwen/qwen3.8-27b` (`GROQ_COMPACTION_MODEL`) | ok 0.2 s | ok | ok | ok | ok (4,530) | no | headers: 1,000 requests per day, 8,000 tokens per minute |

**Consequence (R.5, M.1):** Gemini Flash's free tier allows 20 requests a day per model, far under the about 500 a
day the plan needs (one T1 run is about 15-25 calls). Plan B below applies: enable billing on the AI Studio project
(the author's step). Until then a spent daily quota answers 429 with a `retryDelay` of hours; the client goes to the
next model at once instead of waiting (D-166).

### Measured run cost (R.5, Oct 9, 2026; `make run`, Gemini Flash-Lite after Flash's daily quota was spent)

| Run | LLM calls | Tokens (prompt) | Verifier status | Cassettes |
| --- | --- | --- | --- | --- |
| T5 "Pay the invoice from Kapoor Steel." | 1 (gate) | 370 (292) | `infeasible` | 1 |
| T1 "Process the latest invoice from Sharma Logistics." | 24 (gate 1, gather 11, planner 2, act 10) | 138,069 (135,145) | `awaiting_business_approval` | 24 |

About 5,600 prompt tokens per T1 call on average: the 42 tool schemas (about 3,500 tokens) plus the growing history
are resent every turn. At 20 requests a day per model on the free tier, one T1 run does not fit Flash's daily quota;
the benchmark matrix (28 runs, about 600 calls and 3.5M tokens) needs Plan B (billing) or several days of quota.
Day 5 levers: fewer tool schemas per phase, compaction of old tool results.

## Day 5 changes (Oct 9, 2026; D-174 to D-181)

**Free tier only, no billing (D-175):** Plan B below is withdrawn. Instead:

- **Two more Gemini models (D-176),** each with its own daily quota. Smoke test (`make smoke
  MODELS=GEMINI_FLASH2_MODEL,GEMINI_LITE2_MODEL`, Oct 9):

  | Model (env var) | Plain | Forced tool call | Tool round trip | JSON schema | Long input | Empty tool-call ids | Limits seen |
  | --- | --- | --- | --- | --- | --- | --- | --- |
  | `gemini-3.7-flash` (`GEMINI_FLASH2_MODEL`) | ok 21 s | ok, args exact | ok | ok | 503 "high demand" | no | no 429, no headers: daily limit unknown |
  | `gemini-3.1-flash-lite` (`GEMINI_LITE2_MODEL`) | ok 26 s | ok, args exact | ok | ok | 503 "high demand" | no | no 429, no headers: daily limit unknown |

  Latency was 15-30 s per call at the time (high demand). A daily limit cannot be measured without spending it:
  the author reads it on AI Studio's rate-limit page and adds it to `LLM_DAILY_LIMITS`; until then the client
  learns it from the first 429 (marked spent for the day).
- **Routing by measured size (D-178):** the feasibility gate (266-292 prompt tokens on T1) and the planner (3,432,
  and 4,254 on its retry) are under the 5K bar, so both use the `plan` role: Groq `openai/gpt-oss-120b` first, then
  the Gemini chain. Gemini keeps only the executor loop. A planner retry inside the same minute can pass Groq's 8K
  tokens a minute; its Retry-After is seconds, which the client waits.
- **Daily quota book (D-179):** `runs/llm_quota.json` counts live calls per model per Pacific day (when Gemini's
  free quota resets); `LLM_DAILY_LIMITS` holds the known limits (`gemini-3.5-flash=20,openai/gpt-oss-120b=1000`
  in `.env` so far); a model at its limit is skipped before any request, a long 429 marks it spent; `make run`
  prints what is left before and after.
- **No compaction code (D-174).** Token cost is cut by sending less (D-180, D-181): tools scoped by the SOP (2,500-
  4,000 tokens of schemas per turn before), the gate's lookups in the gather brief (no re-probe), the act brief with
  only the cited SOP steps and no self-checking reads, results without empty fields (4,000-character cap), facts
  kept across `facts_ready` calls and read after their labels (T1 had three refusals).

| Run | Before (Oct 9, Day 4) | After (Day 5, one live T1) |
| --- | --- | --- |
| T1 LLM calls (gate, gather, planner, act) | 24 (1, 13, 2, 8) | 17 (1 Groq, 8, 2, 6) |
| T1 tokens (prompt) | 138,069 (135,145) | **76,283 (73,199): -45%, target 60K not met** |

Measured on the recorded run 288ca95898e4f4cb (Oct 9, after D-191 to D-195), whose cassettes are committed: gather
about 32K prompt tokens over 8 calls, planner about 8K over 2 (the first attempt is refused every time so far:
`status: "any"` in an enum arg and a missing PI-6 milestone), act about 32.5K over 6 calls (the browser view adds
about 1.2K per turn after the attach page opens). Levers left, not taken before the Day 5.2 commit (each is a prompt
edit after the freeze and a re-record): drop an enum arg whose value is "any" in code instead of refusing the plan
(saves the planner retry, about 5.6K); a smaller first gather result (the inbox list, about 1K, is resent 7 times);
the browser observation cap (8,000 characters) for the attach page.

### Free-tier limits (AI Studio rate-limit page, read by the author on Oct 9, 2026; Groq from its headers)

| Model | RPM | RPD | TPM | Role |
| --- | --- | --- | --- | --- |
| `gemini-3.5-flash-lite` | 15 | 500 | 250K | executor, first |
| `gemini-3.1-flash-lite` | 15 | 500 | 250K | executor, second |
| `gemini-3.5-flash` | 5 | 20 | 250K | executor, quality fallback |
| `gemini-3.7-flash` | 5 | 20 | 250K | executor, last |
| Groq `openai/gpt-oss-120b` | 30 | 1,000 | 8K | gate, planner, judge |

These go into `LLM_DAILY_LIMITS` and `LLM_RPM` (`.env.example`, D-187); the client skips a model at its daily
estimate and spaces calls to it by 60/RPM seconds.

**Role routing now (D-187):** executor Flash-Lite 3.5 → Flash-Lite 3.1 → Flash 3.5 → Flash 3.7 (T1 passed on Lite on
Day 4; the Flash models are a quality fallback with 20 calls a day); gate and planner Groq gpt-oss-120b → the executor
chain; judge Groq gpt-oss-120b → Gemini Flash-Lite (logged as same family). **Planner moved back to the executor's
Gemini chain (D-193):** on Groq gpt-oss-120b two live T1 plans in a row had read-step milestones and a pre-state
check that contradicted the entry, and its retry kept them; the gate stays on Groq. So the judge (Groq) is
independent of both the executor and the planner (Gemini) that wrote its criteria; it can only lower `completed` or
add `judge_flags`. Cost: about 2 Flash-Lite calls per run (about 62 on Day 6).

### Day 6 benchmark estimate (pass^3 restored, D-188)

Calls per task: T1 measured on Day 4 (22 executor calls, 2 planner, 1 gate) and T5 measured on Day 5 (1 gate call);
every other figure is an estimate from T1's shape, to be replaced by the Day 5 live counts (5.3). Day 4 figures are
before the Day 5 token cuts, so the estimate is on the high side.

| Run | Runs | Executor (Lite) calls each | Groq calls each (gate, planner, judge) | Lite total | Groq total |
| --- | --- | --- | --- | --- | --- |
| T1, T2, T6, T7 (process-invoice) | 4 x 3 | 22 (T1 measured) | 3 | 264 | 36 |
| T3 (onboarding) | 3 | 22 | 4 | 66 | 12 |
| T4 (ask) | 3 | 8 | 1 | 24 | 3 |
| T5 (decline) | 3 | 0 | 1 (measured) | 0 | 3 |
| T8 (schedule payment) | 3 | 18 | 3 | 54 | 9 |
| Chaos on (4 tasks x 1) | 4 | 22 | 3 | 88 | 12 |
| T9 none / approve / reject | 3 | 8 | 3 | 24 | 9 |
| Replans (up to 3 per failing run; allow 10%) | | | | about 52 | about 9 |
| **Total** | **31** | | | **about 572** | **about 93** |

Against the limits: about 572 of the 1,000 Flash-Lite calls a day (500 + 500), so the matrix fits one day with room
for a re-run, without touching the 40 Flash calls. Groq: about 93 of 1,000. **Time, not count, binds:** at 15 RPM the
Lite calls need at least 38 minutes; Groq's 8K tokens a minute allows about one planner call (about 4K prompt tokens
plus its answer) every 40 seconds, so the 31 planner calls add at least 20 minutes. Tokens: about 5K per Lite call x
15 a minute = 75K, under 250K TPM. Cassettes recorded on Day 5 (one live run per task) do not count against Day 6.

## Providers (as checked on Oct 5, 2026; superseded where the table above differs)

| Provider | Free models of interest | Published free limits | Notes |
| --- | --- | --- | --- |
| Google AI Studio (Gemini API) | Gemini Flash, Gemini Flash-Lite | Per project, shown live in AI Studio; reports range roughly 5–15 RPM and 250–1,500 RPD for Flash. Pro models left the free tier in April 2026 | Function calling, vision, long context. Free-tier prompts may be used to improve Google products (fine: Acme data is fake). Limits: https://ai.google.dev/gemini-api/docs/rate-limits |
| Groq | `openai/gpt-oss-120b` (judge), `qwen/qwen3.8-27b` (compaction, D-165) | 30 RPM, 1K RPD, **8K TPM**, 200K TPD per model | Very fast. The 8K tokens-per-minute cap binds long before the request cap, so Groq serves only the judge and compaction. Limits: https://console.groq.com/docs/rate-limits |
| OpenRouter | Models ending in `:free` | 20 RPM; 50 requests/day with < $10 credits ever purchased | **Not used (D-165): no key, and none will be made.** A provider with no key is not configured and the client skips it; the `OPENROUTER_*` keys stay in the allowlist, so a key added later just works as the last reasoning fallback. |

Exact model IDs: copy them from each console into `.env` during the Day 3 evening check. Do not trust IDs
from memory.

## Role routing

| Role | Primary | Fallback chain | Typical input size |
| --- | --- | --- | --- |
| Feasibility gate | Gemini Flash | Gemini Flash-Lite | small |
| Planner | Gemini Flash | Gemini Flash-Lite | small–medium |
| Executor (tool loop) | Gemini Flash | Gemini Flash-Lite | medium (pruned a11y tree, growing history) |
| Vision (screenshot fallback) | Gemini Flash | none (escalate) | image |
| Compaction / extraction clean-up | Gemini Flash-Lite | Groq qwen3.8-27b | small |
| Verifier judge | Groq gpt-oss-120b | Gemini Flash-Lite | small (final-state text) |

**Groq is used only for the judge and compaction.** Its 8K tokens-per-minute cap cannot carry the
executor's growing context, or the gate and planner prompts with SOPs attached.

The judge deliberately uses a **different model family** from the executor so verification is more
independent. Keep judge inputs to final-state text and the behavior narrative, which fits Groq's TPM.
When the judge falls back to Flash-Lite (same family as the executor), the run is marked so in results.

## Client design

- One `LLMClient` with `chat(messages, tools, model_role)`; providers behind it via OpenAI-compatible
  endpoints:
  - Gemini: `https://generativelanguage.googleapis.com/v1beta/openai/`
  - Groq: `https://api.groq.com/openai/v1`
  - OpenRouter: `https://openrouter.ai/api/v1`
- Day 3 evening: the author's manual curl check (outside the repo) confirms keys, model IDs, tool calling
  and the live limits. Day 4, first thing: the smoke test through this client, one forced tool call per
  provider. If Gemini's compatibility layer mishandles tools, switch that provider to the native
  `google-genai` SDK behind the same interface.
- Honour `Retry-After` or Gemini's `retryDelay`, else exponential backoff with full jitter; 3 tries per model; a wait over a minute or a non-retryable 4xx goes to the next model at once (D-166). No token-bucket limiter yet (Day 5 if the bench needs one).
- Fallback chain per role; every fallback is logged so benchmark numbers state which model ran. A provider with no
  key, base URL or model id is not configured and is skipped (D-165).
- **Cassettes:** hash(role, request body, frozen `now`) → stored response, never the provider or model, so a replay
  does not depend on the evaluator's keys (D-165); the cassette records which model answered. `REPLAY=1` serves only from
  cassettes and fails loudly on a miss. Used for: evaluators without keys, deterministic demo takes,
  re-running checkers without spending quota.

## Budget maths

- One task run ≈ 15–30 LLM calls (gate 1–2, planner 1–3, executor 10–20, compaction 0–3, judge 1).
- AcmeBench matrix: 8 core tasks (T1–T8) × 3 runs with chaos off (pass^3) = 24 runs, plus 4 tasks × 1 run
  with chaos on = 4 runs. 28 runs ≈ 420–840 calls.
- ~~**Plan B, approved now:** if the Day 3 check or Day 4 shows under about 500 requests per day on
  Gemini Flash, enable billing on that AI Studio project.~~ Withdrawn on Day 5: free tier only (D-175).
- Other measures:
  - Spread the benchmark over Days 5–6, recording cassettes as it runs.
  - Cache: re-running checkers or the report never re-calls the LLM.
  - Keep observations small (pruned a11y tree, diffs) to stay under TPM.
  - Deterministic layers (predicates, side-effect check, normalisers, error classification, injection
    scanner) use zero LLM calls.

## Risks specific to free keys

| # | Problem | How it shows up | How we handle it | How we prove it |
| --- | --- | --- | --- | --- |
| M.1 | Daily quota exhausted mid-benchmark | 429s; half the results missing | Reduced matrix above; runs spread over Days 5–6; cassettes; fallback chain; billing plan B if Flash < ~500 RPD | Benchmark log shows quota headroom per day |
| M.2 | TPM cap (Groq 8K) | Long prompts rejected even at low RPM | Groq only for the judge and compaction; pruned observations | Token counts logged per call |
| M.3 | Weaker tool calling than frontier models | Malformed arguments, wrong tools, loops | Strict schemas + validation errors as observations; few tools per step; deterministic layers | Phantom-tool and validation-error rates in logs |
| M.4 | Limits or models change without notice | Yesterday's config fails today | IDs and limits in `.env`; Day 3 evening check, Day 4 smoke test, pre-recording checks | Smoke test passes before every demo take |
| M.5 | Free-tier data use | Prompts may be used for training | Only fake Acme data ever reaches the model | No real data in repo or prompts |
| M.6 | Evaluators have no keys | Repo "doesn't run" | `REPLAY=1` mode with committed cassettes for the demo tasks | Fresh clone runs the demo in replay mode |
| M.7 | Nondeterminism across providers | Benchmark numbers vary by which fallback ran | Log provider/model per call; report results per primary model | Results table includes a model column |

## Interview framing

Running a reliable operator on free-tier models is a feature, not a compromise: the harness (gate,
state milestones, policy gate, verifier) carries the reliability, which matches Pointer's finding that a
smaller model inside a strong harness approaches a larger one at a fraction of the cost.
