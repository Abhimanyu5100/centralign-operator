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
- **Plan B, approved now:** if the Day 3 check or Day 4 shows under about 500 requests per day on
  Gemini Flash, enable billing on that AI Studio project.
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
