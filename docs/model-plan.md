# Model plan: running the agent on free API keys

Building happens in Claude Code on the Claude subscription. The **agent's own LLM calls** run on free
API tiers, starting on Day 4 (Phase B). Phases before that use no LLM calls at all. Free tiers change without notice, so every number below must be re-checked on the provider's
live limits page on Day 0 and recorded here.

## Providers (as checked on Oct 5, 2026)

| Provider | Free models of interest | Published free limits | Notes |
| --- | --- | --- | --- |
| Google AI Studio (Gemini API) | Gemini Flash, Gemini Flash-Lite | Per project, shown live in AI Studio; reports range roughly 5–15 RPM and 250–1,500 RPD for Flash. Pro models left the free tier in April 2026 | Function calling, vision, long context. Free-tier prompts may be used to improve Google products (fine: Acme data is fake). Limits: https://ai.google.dev/gemini-api/docs/rate-limits |
| Groq | `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b` | 30 RPM, 1K RPD, **8K TPM**, 200K TPD per model | Very fast. The 8K tokens-per-minute cap binds long before the request cap. Limits: https://console.groq.com/docs/rate-limits |
| OpenRouter | Models ending in `:free` | 20 RPM; 50 requests/day with < $10 credits ever purchased, 1,000/day at ≥ $10 | Emergency fallback only. Extra keys do not add capacity. Limits: https://openrouter.ai/docs/api-reference/limits |

Exact model IDs: copy them from each console into `.env` on Day 0. Do not trust IDs from memory.

## Role routing

| Role | Primary | Fallback | Typical input size |
| --- | --- | --- | --- |
| Feasibility gate | Gemini Flash | Groq gpt-oss-120b | small |
| Planner | Gemini Flash | Groq gpt-oss-120b | small–medium |
| Executor (tool loop) | Gemini Flash | Groq qwen3.8-27b | medium (pruned a11y tree) |
| Vision (screenshot fallback) | Gemini Flash | none (escalate) | image |
| Compaction / extraction clean-up | Gemini Flash-Lite | Groq gpt-oss-20b | small |
| Verifier judge | Groq gpt-oss-120b | Gemini Flash-Lite | small (final-state text) |

The judge deliberately uses a **different model family** from the executor so verification is more
independent. Keep judge inputs to final-state text and the behavior narrative, which fits Groq's TPM.

## Client design

- One `LLMClient` with `chat(messages, tools, model_role)`; providers behind it via OpenAI-compatible
  endpoints:
  - Gemini: `https://generativelanguage.googleapis.com/v1beta/openai/`
  - Groq: `https://api.groq.com/openai/v1`
  - OpenRouter: `https://openrouter.ai/api/v1`
- Day 0 smoke test: one forced tool call per provider through this client. If Gemini's compatibility
  layer mishandles tools, switch that provider to the native `google-genai` SDK behind the same interface.
- Token-bucket limiter per provider (RPM and TPM), honour `Retry-After`, exponential backoff with jitter.
- Fallback chain per role; every fallback is logged so benchmark numbers state which model ran.
- **Cassettes:** hash(provider, model, messages, tools) → stored response. `REPLAY=1` serves only from
  cassettes and fails loudly on a miss. Used for: evaluators without keys, deterministic demo takes,
  re-running checkers without spending quota.

## Budget maths

- One task run ≈ 15–30 LLM calls (gate 1–2, planner 1–3, executor 10–20, compaction 0–3, judge 1).
- AcmeBench plan: 8 tasks × 3 runs × 2 chaos modes = 48 runs ≈ 1,000–1,400 calls.
- That can exceed a single day's Gemini free quota. Therefore:
  - Split the benchmark across Day 5 evening and Day 6.
  - Cache: re-running checkers or the report never re-calls the LLM.
  - Keep observations small (pruned a11y tree, diffs) to stay under TPM.
  - Deterministic layers (predicates, DB diff, normalisers, error classification) use zero LLM calls.

## Risks specific to free keys

| # | Problem | How it shows up | How we handle it | How we prove it |
| --- | --- | --- | --- | --- |
| M.1 | Daily quota exhausted mid-benchmark | 429s; half the results missing | Budget above; split runs; cassettes; fallback chain | Benchmark log shows quota headroom per day |
| M.2 | TPM cap (Groq 8K) | Long prompts rejected even at low RPM | Groq only for small-input roles; pruned observations | Token counts logged per call |
| M.3 | Weaker tool calling than frontier models | Malformed arguments, wrong tools, loops | Strict schemas + validation errors as observations; few tools per step; deterministic layers | Phantom-tool and validation-error rates in logs |
| M.4 | Limits or models change without notice | Yesterday's config fails today | IDs and limits in `.env`; Day 0 and pre-recording checks | Smoke test passes before every demo take |
| M.5 | Free-tier data use | Prompts may be used for training | Only fake Acme data ever reaches the model | No real data in repo or prompts |
| M.6 | Evaluators have no keys | Repo "doesn't run" | `REPLAY=1` mode with committed cassettes for the demo tasks | Fresh clone runs the demo in replay mode |
| M.7 | Nondeterminism across providers | Benchmark numbers vary by which fallback ran | Log provider/model per call; report results per primary model | Results table includes a model column |

## Interview framing

Running a reliable operator on free-tier models is a feature, not a compromise: the harness (gate,
state milestones, policy gate, verifier) carries the reliability, which matches Pointer's finding that a
smaller model inside a strong harness approaches a larger one at a fraction of the cost.
