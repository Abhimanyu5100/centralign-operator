"""The LLM client (agent/llm/) without a network: an httpx.MockTransport stands in for the providers.

URL joining (the trailing-slash bug), retries with Retry-After and backoff, fallback to the lite model, skipping a
provider that is not configured (OpenRouter has no key, D-165), record and replay with no key, cassette keys (the
frozen now in, the run id refused, never the provider), the token budget, tool-call parsing (empty ids, provider
fields echoed back) and the `llm_call` event. Register X.1, X.3, M.4, D-106."""

import asyncio
import json

import httpx
import pytest

from agent.llm.client import CHAINS, BudgetExceeded, CassetteMiss, LLMClient, LLMError, LLMUnavailable, QuotaBook

NOW = "2026-10-07T10:30:00+05:30"
# The retry and fallback mechanics are tested on a fixed two-model chain; the real order has its own test.
MECHANICS = {**CHAINS, "reason": [("GEMINI", "GEMINI_MODEL"), ("GEMINI", "GEMINI_LITE_MODEL"),
                                  ("OPENROUTER", "OPENROUTER_FALLBACK_MODEL")]}
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


def client(tmp_path, script, *, events=None, sleeps=None, quota=None, chains=MECHANICS, clock=None, paced=None,
           **extra):
    provider = Provider(script)

    async def sleep(seconds):
        (sleeps if sleeps is not None else []).append(seconds)
    c = LLMClient(config(tmp_path, **extra), now=NOW, log=(events.append if events is not None else lambda event: None),
                  forbidden=("run-abc123",), transport=httpx.MockTransport(provider), sleep=sleep, quota=quota,
                  chains=chains, **({"clock": clock, "paced": paced} if clock else {}))
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


# --- daily quota book (D-179, R.5) ------------------------------------------------------------------------------

def test_the_lite_models_come_first_and_the_plan_role_tries_groq_first(tmp_path):
    """D-187: the Lite models (500 a day each) before the Flash models (20 a day each); gate and planner on Groq."""
    c, _ = client(tmp_path, {}, chains=CHAINS, GROQ_PLAN_MODEL="oss-120b", GEMINI_FLASH2_MODEL="flash-2",
                  GEMINI_LITE2_MODEL="lite-2")
    assert [e[3] for e in c.chain("reason")] == ["flash-lite", "lite-2", "flash", "flash-2"]
    assert [e[3] for e in c.chain("plan")] == ["oss-120b", "flash-lite", "lite-2", "flash", "flash-2"]


def test_a_model_at_its_estimated_daily_limit_is_skipped_before_any_request(tmp_path):
    book = QuotaBook(tmp_path / "quota.json", "2026-10-09", "flash=2, flash-lite=100")
    c, provider = client(tmp_path, {"flash": [(200, answer(), {})] * 2, "flash-lite": [(200, answer(), {})]}, quota=book)
    assert [chat(c, "reason", [{"role": "user", "content": f"q{i}"}]).model for i in range(3)] == \
        ["flash", "flash", "flash-lite"]
    assert [r[1]["model"] for r in provider.requests] == ["flash", "flash", "flash-lite"]
    again = QuotaBook(tmp_path / "quota.json", "2026-10-09", "flash=2, flash-lite=100")  # read back from the file
    assert (again.left("flash"), again.left("flash-lite"), again.left("unlisted")) == (0, 99, None)


def test_a_long_429_marks_the_model_spent_for_the_day_and_a_new_day_resets(tmp_path):
    book = QuotaBook(tmp_path / "quota.json", "2026-10-09")
    daily = (429, {"error": {"details": [{"retryDelay": "34017s"}]}}, {})
    c, provider = client(tmp_path, {"flash": [daily], "flash-lite": [(200, answer(), {})] * 2}, quota=book)
    chat(c, "reason", MESSAGES)
    chat(c, "reason", [{"role": "user", "content": "again"}])
    assert [r[1]["model"] for r in provider.requests] == ["flash", "flash-lite", "flash-lite"]  # flash asked once
    assert QuotaBook(tmp_path / "quota.json", "2026-10-09").left("flash") == 0
    assert QuotaBook(tmp_path / "quota.json", "2026-10-10").left("flash") is None


def test_replay_never_counts_against_the_quota(tmp_path):
    book = QuotaBook(tmp_path / "quota.json", "2026-10-09", "flash=5")
    c, _ = client(tmp_path, {"flash": [(200, answer(), {})]}, quota=book)
    chat(c, "reason", MESSAGES)
    replay = LLMClient({**config(tmp_path), "REPLAY": "1"}, now=NOW, quota=book)
    asyncio.run(replay.chat("reason", MESSAGES))
    assert book.left("flash") == 4


def test_calls_to_a_model_are_spaced_by_its_rpm_on_a_fake_clock(tmp_path):
    """LLM_RPM: at most n calls a minute per model, so a burst never earns a 429; other models are not slowed."""
    now, sleeps = [100.0], []

    async def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds
    c = LLMClient(config(tmp_path, LLM_RPM="flash=15"), now=NOW, chains=MECHANICS, sleep=sleep, clock=lambda: now[0],
                  paced={}, transport=httpx.MockTransport(Provider({"flash": [(200, answer(), {})] * 3})))
    for i in range(3):
        asyncio.run(c.chat("reason", [{"role": "user", "content": f"q{i}"}]))
        now[0] += 1.0  # one second of work between calls
    assert sleeps == [0.0, 3.0, 3.0]  # 60 / 15 = 4 s apart
    c, provider = client(tmp_path, {"flash": [(200, answer(), {})] * 2}, sleeps=sleeps, clock=lambda: now[0], paced={})
    chat(c, "reason", [{"role": "user", "content": "a"}])
    chat(c, "reason", [{"role": "user", "content": "b"}])
    assert sleeps == [0.0, 3.0, 3.0] and len(provider.requests) == 2  # no LLM_RPM: no spacing


def test_a_scope_keeps_a_scenarios_replies_apart_and_no_scope_keeps_the_plain_key(tmp_path):
    """D-209: a chaos run shares its first requests with the plain task; with its own scope neither overwrites the
    other's replies. No scope gives exactly the key recorded before scopes existed."""
    from agent.llm import cassette
    body = {"messages": MESSAGES}
    plain = cassette.cassette_key("reason", body, NOW)
    assert cassette.cassette_key("reason", body, NOW, "") == plain
    assert cassette.cassette_key("reason", body, NOW, "flaky_500:0") != plain
    c, _ = client(tmp_path, {"flash": [(200, answer("plain"), {}), (200, answer("chaos"), {})]})
    chat(c, "reason", MESSAGES)
    c2, _ = client(tmp_path, {"flash": [(200, answer("chaos"), {})]}, CASSETTE_SCOPE="flaky_500:0")
    chat(c2, "reason", MESSAGES)
    replay = lambda scope: LLMClient({**config(tmp_path), "REPLAY": "1", "CASSETTE_SCOPE": scope}, now=NOW)  # noqa: E731
    assert [asyncio.run(replay(s).chat("reason", MESSAGES)).content for s in ("", "flaky_500:0")] == ["plain", "chaos"]
