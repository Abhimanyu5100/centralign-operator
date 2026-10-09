"""The LLM client (agent/llm/) without a network: an httpx.MockTransport stands in for the providers.

URL joining (the trailing-slash bug), retries with Retry-After and backoff, fallback to the lite model, skipping a
provider that is not configured (OpenRouter has no key, D-165), record and replay with no key, cassette keys (the
frozen now in, the run id refused, never the provider), the token budget, tool-call parsing (empty ids, provider
fields echoed back) and the `llm_call` event. Register X.1, X.3, M.4, D-106."""

import asyncio
import json

import httpx
import pytest

from agent.llm.client import BudgetExceeded, CassetteMiss, LLMClient, LLMError, LLMUnavailable

NOW = "2026-10-07T10:30:00+05:30"
MESSAGES = [{"role": "user", "content": "Say pong."}]


def config(tmp_path, **extra):
    base = {"GEMINI_API_KEY": "gk-secret-1", "GEMINI_BASE_URL": "https://gemini.test/v1beta/openai/",
            "GEMINI_MODEL": "flash", "GEMINI_LITE_MODEL": "flash-lite", "GROQ_API_KEY": "gq-secret-2",
            "GROQ_BASE_URL": "https://groq.test/openai/v1", "GROQ_JUDGE_MODEL": "oss-120b",
            "CASSETTE_DIR": str(tmp_path / "cassettes")}
    return {**base, **extra}


def answer(content="pong", tool_calls=None, tokens=10):
    message = {"role": "assistant", "content": content, **({"tool_calls": tool_calls} if tool_calls else {})}
    return {"choices": [{"message": message}], "usage": {"prompt_tokens": tokens - 2, "completion_tokens": 2,
                                                          "total_tokens": tokens}}


class Provider:
    """Answers each request from a script of (status, body, headers) per model; records every request."""

    def __init__(self, script):
        self.script, self.requests = {k: list(v) for k, v in script.items()}, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append((str(request.url), body, dict(request.headers)))
        status, payload, headers = self.script[body["model"]].pop(0)
        return httpx.Response(status, json=payload, headers=headers)


def client(tmp_path, script, *, events=None, sleeps=None, **extra):
    provider = Provider(script)

    async def sleep(seconds):
        (sleeps if sleeps is not None else []).append(seconds)
    c = LLMClient(config(tmp_path, **extra), now=NOW, log=(events.append if events is not None else lambda event: None),
                  forbidden=("run-abc123",), transport=httpx.MockTransport(provider), sleep=sleep)
    return c, provider


def chat(c, *args, **kwargs):
    return asyncio.run(c.chat(*args, **kwargs))


@pytest.mark.parametrize("base", ["https://gemini.test/v1beta/openai/", "https://gemini.test/v1beta/openai",
                                  "https://gemini.test/v1beta/openai//"])
def test_the_url_never_has_a_double_slash(tmp_path, base):
    c, provider = client(tmp_path, {"flash": [(200, answer(), {})]}, GEMINI_BASE_URL=base)
    assert chat(c, "reason", MESSAGES).content == "pong"
    assert provider.requests[0][0] == "https://gemini.test/v1beta/openai/chat/completions"


def test_a_429_waits_retry_after_then_succeeds(tmp_path):
    sleeps, events = [], []
    c, provider = client(tmp_path, {"flash": [(429, {"error": "slow down"}, {"Retry-After": "7"}), (200, answer(), {})]},
                         sleeps=sleeps, events=events)
    reply = chat(c, "reason", MESSAGES)
    assert reply.model == "flash" and sleeps == [7.0] and len(provider.requests) == 2
    assert events[0]["notes"] == ["gemini/flash try 1: HTTP 429 '{\"error\":\"slow down\"}'"]


def test_geminis_retry_delay_in_the_body_is_honoured(tmp_path):
    sleeps = []
    body = {"error": {"details": [{"retryDelay": "12s"}]}}
    c, _ = client(tmp_path, {"flash": [(429, body, {}), (200, answer(), {})]}, sleeps=sleeps)
    chat(c, "reason", MESSAGES)
    assert sleeps == [12.0]


def test_a_daily_quota_goes_to_the_lite_model_without_waiting(tmp_path):
    """Gemini's free tier answers a spent daily quota with a 429 and a retryDelay of hours: never wait that out."""
    sleeps = []
    daily = (429, {"error": {"details": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                                          "retryDelay": "34017s"}]}}, {})
    c, provider = client(tmp_path, {"flash": [daily], "flash-lite": [(200, answer(), {})]}, sleeps=sleeps)
    assert chat(c, "reason", MESSAGES).model == "flash-lite" and sleeps == [] and len(provider.requests) == 2


def test_503_three_times_falls_back_to_the_lite_model_with_jittered_backoff(tmp_path):
    sleeps, events = [], []
    busy = (503, {"error": "high demand"}, {})
    c, provider = client(tmp_path, {"flash": [busy] * 3, "flash-lite": [(200, answer(), {})]}, sleeps=sleeps,
                         events=events)
    reply = chat(c, "reason", MESSAGES)
    assert (reply.provider, reply.model) == ("gemini", "flash-lite")
    assert len(sleeps) == 2 and all(0 <= s <= 20 for s in sleeps)  # between tries, not after the last one
    assert [r[1]["model"] for r in provider.requests] == ["flash"] * 3 + ["flash-lite"]
    assert len(events[0]["notes"]) == 3


def test_a_404_goes_to_the_next_model_at_once(tmp_path):
    sleeps = []
    c, _ = client(tmp_path, {"flash": [(404, {}, {})], "flash-lite": [(200, answer(), {})]}, sleeps=sleeps)
    assert chat(c, "reason", MESSAGES).model == "flash-lite" and sleeps == []


def test_a_provider_without_a_key_is_skipped(tmp_path):
    """OpenRouter is in the reason chain but has no key: it is not configured, so never called (D-165)."""
    c, _ = client(tmp_path, {}, OPENROUTER_BASE_URL="https://openrouter.test/api/v1", OPENROUTER_FALLBACK_MODEL="x:free")
    assert [entry[3] for entry in c.chain("reason")] == ["flash", "flash-lite"]
    c, provider = client(tmp_path, {"flash": [(401, {}, {})], "flash-lite": [(401, {}, {})]})
    with pytest.raises(LLMUnavailable, match="every configured model failed"):
        chat(c, "reason", MESSAGES)
    assert {r[1]["model"] for r in provider.requests} == {"flash", "flash-lite"}
    c, _ = client(tmp_path, {}, GEMINI_API_KEY="", GROQ_API_KEY="")
    with pytest.raises(LLMUnavailable, match="no provider configured"):
        chat(c, "reason", MESSAGES)


def test_a_recorded_call_replays_with_no_key_and_no_network(tmp_path):
    c, _ = client(tmp_path, {"flash": [(200, answer("recorded"), {})]})
    first = chat(c, "reason", MESSAGES)
    replay = LLMClient({"REPLAY": "1", "CASSETTE_DIR": str(tmp_path / "cassettes")}, now=NOW,
                       transport=httpx.MockTransport(lambda r: pytest.fail("replay must not call a provider")))
    again = asyncio.run(replay.chat("reason", MESSAGES))
    assert again == first and again.content == "recorded"


def test_a_replay_miss_fails_loudly(tmp_path):
    replay = LLMClient({"REPLAY": "1", "CASSETTE_DIR": str(tmp_path / "cassettes")}, now=NOW)
    with pytest.raises(CassetteMiss, match="no cassette"):
        asyncio.run(replay.chat("reason", MESSAGES))


def test_the_key_depends_on_the_request_and_now_never_on_the_provider(tmp_path):
    c, _ = client(tmp_path, {"flash": [(200, answer(), {})]})
    chat(c, "reason", MESSAGES)
    files = sorted(p.name for p in (tmp_path / "cassettes").rglob("*.json"))
    other = LLMClient({**config(tmp_path), "GEMINI_MODEL": "another-model", "REPLAY": "1"}, now=NOW)
    asyncio.run(other.chat("reason", MESSAGES))  # same request and now, other model configured: a hit
    later = LLMClient({**config(tmp_path), "REPLAY": "1"}, now="2026-10-08T10:30:00+05:30")
    with pytest.raises(CassetteMiss):
        asyncio.run(later.chat("reason", MESSAGES))
    assert len(files) == 1


def test_a_request_holding_the_run_id_is_refused_before_anything_is_sent(tmp_path):
    c, provider = client(tmp_path, {})
    with pytest.raises(LLMError, match="run id"):
        chat(c, "reason", [{"role": "user", "content": "see runs/run-abc123/files/x.pdf"}])
    assert provider.requests == [] and not (tmp_path / "cassettes").exists()


def test_the_token_budget_stops_the_next_call(tmp_path):
    c, _ = client(tmp_path, {"flash": [(200, answer(tokens=50), {}), (200, answer(), {})]}, LLM_TOKEN_BUDGET="40")
    chat(c, "reason", MESSAGES)
    with pytest.raises(BudgetExceeded):
        chat(c, "reason", [{"role": "user", "content": "again"}])


def test_tool_calls_are_parsed_and_echoed_back_as_the_provider_sent_them(tmp_path):
    raw = [{"id": "", "type": "function", "function": {"name": "find_vendors", "arguments": '{"q": "Sharma"}'},
            "extra_content": {"google": {"thought_signature": "sig-1"}}},
           {"id": "c2", "type": "function", "function": {"name": "list_mail", "arguments": "{not json"}}]
    c, _ = client(tmp_path, {"flash": [(200, answer(None, raw), {}), (200, answer(None, raw), {})]})
    reply = chat(c, "reason", MESSAGES, tools=[{"type": "function", "function": {"name": "find_vendors"}}])
    first, second = reply.tool_calls
    assert first.id.startswith("call_") and first.arguments == {"q": "Sharma"}
    assert second.id == "c2" and second.arguments == {"unparsed_arguments": "{not json"}
    assert reply.message["tool_calls"][0]["extra_content"] == {"google": {"thought_signature": "sig-1"}}
    assert reply.message["tool_calls"][0]["id"] == first.id  # the generated id is stable and echoed back
    again = chat(c, "reason", [*MESSAGES, {"role": "user", "content": "x"}], tools=[{"type": "function"}])
    assert again.tool_calls[0].id == first.id


def test_every_call_is_one_llm_call_event_without_the_key(tmp_path):
    events = []
    c, provider = client(tmp_path, {"flash": [(200, answer(tokens=30), {"x-ratelimit-remaining-requests": "9"})]},
                         events=events)
    chat(c, "reason", MESSAGES, schema={"type": "object"})
    event = events[0]
    assert {k: event[k] for k in ("role", "provider", "model", "prompt_tokens", "completion_tokens", "total_tokens",
                                  "source", "used")} == {"role": "reason", "provider": "gemini", "model": "flash",
                                                         "prompt_tokens": 28, "completion_tokens": 2,
                                                         "total_tokens": 30, "source": "recorded", "used": 30}
    assert provider.requests[0][1]["response_format"]["type"] == "json_schema"
    assert provider.requests[0][2]["authorization"] == "Bearer gk-secret-1"  # the key travels in the header only
    stored = "".join(p.read_text() for p in (tmp_path / "cassettes").rglob("*.json"))
    assert "gk-secret-1" not in stored and "gk-secret-1" not in json.dumps(events)
