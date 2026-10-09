"""LLM client (docs/model-plan.md): OpenAI-compatible providers from config only, a fallback chain per role, a
per-run token budget, one `llm_call` event per call, record/replay cassettes (agent/llm/cassette.py).

- A provider missing its key, base URL or model id is not configured and is skipped (D-165).
- 429, 5xx and transport errors: up to 3 tries per model (Retry-After or retryDelay, else backoff with full
  jitter); another 4xx or a wait over a minute (a spent daily quota) goes to the next model at once (D-166).
- REPLAY=1 serves from cassettes only and needs no key; a miss raises. Otherwise every call is live and recorded.
- A request holding a forbidden value (the run id, D-106) is refused before it is hashed or sent.
- Tool calls keep the provider's own object (Gemini's thought signature goes back unchanged); an empty id gets a
  stable one.
"""

import asyncio
import hashlib
import json
import random
import re
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx
from pydantic import BaseModel

from agent.config import ROOT
from agent.llm import cassette

CHAINS = {  # role -> (provider env prefix, model id key), first choice first
    "reason": [("GEMINI", "GEMINI_MODEL"), ("GEMINI", "GEMINI_LITE_MODEL"), ("OPENROUTER", "OPENROUTER_FALLBACK_MODEL")],
    "compact": [("GEMINI", "GEMINI_LITE_MODEL"), ("GROQ", "GROQ_COMPACTION_MODEL")],
    "judge": [("GROQ", "GROQ_JUDGE_MODEL"), ("GEMINI", "GEMINI_LITE_MODEL")],
}
RETRYABLE = frozenset({429, 500, 502, 503, 504})
TRIES, BASE_DELAY, MAX_DELAY, MAX_WAIT, HTTP_TIMEOUT = 3, 1.0, 20.0, 60.0, 90.0
DEFAULT_BUDGET = 300_000
RETRY_DELAY = re.compile(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"')


class LLMError(RuntimeError):
    """Any reason the model cannot answer; the subclasses below say which."""


class LLMUnavailable(LLMError): ...  # every configured model failed
class CassetteMiss(LLMError): ...    # REPLAY=1 and no cassette for this request
class BudgetExceeded(LLMError): ...  # the run's token budget is used up


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class LLMReply(BaseModel):
    content: str | None = None
    tool_calls: list[ToolCall] = []
    message: dict[str, Any]          # the assistant message to append to the conversation, as the provider sent it
    provider: str
    model: str
    usage: dict[str, int] = {}


def _parse(data: dict[str, Any], provider: str, model: str) -> LLMReply:
    message = data["choices"][0]["message"]
    calls, raw_calls = [], []
    for i, raw in enumerate(message.get("tool_calls") or []):
        text = raw["function"].get("arguments") or "{}"
        try:
            args = json.loads(text) if isinstance(text, str) else text
        except ValueError:
            args = {"unparsed_arguments": text}  # the registry refuses it as invalid_args and the model is told
        call_id = raw.get("id") or "call_" + hashlib.sha256(f"{i}:{raw['function']['name']}:{text}".encode()).hexdigest()[:12]
        calls.append(ToolCall(id=call_id, name=raw["function"]["name"], arguments=args if isinstance(args, dict) else {}))
        raw_calls.append({**raw, "id": call_id})
    usage = data.get("usage") or {}
    return LLMReply(content=message.get("content"), tool_calls=calls, provider=provider, model=model,
                    message={"role": "assistant", "content": message.get("content") or "",
                             **({"tool_calls": raw_calls} if raw_calls else {})},
                    usage={k: int(usage.get(k) or 0) for k in ("prompt_tokens", "completion_tokens", "total_tokens")})


def _wait(response: httpx.Response | None, attempt: int) -> float | None:
    """Seconds before the next try; None when the server asks for longer than MAX_WAIT (a daily quota): skip on."""
    found = response.headers.get("retry-after", "").strip() if response is not None else ""
    m = RETRY_DELAY.search(response.text) if response is not None and not found else None
    asked = float(found) if found.replace(".", "", 1).isdigit() else float(m[1]) if m else None
    if asked is not None:
        return asked if asked <= MAX_WAIT else None
    return random.uniform(0, min(MAX_DELAY, BASE_DELAY * 2 ** attempt))


class LLMClient:
    def __init__(self, config: Mapping[str, str], *, now: str, log: Callable[[dict[str, Any]], None] = lambda event: None,
                 forbidden: tuple[str, ...] = (), transport: httpx.AsyncBaseTransport | None = None,
                 sleep: Callable[[float], Any] = asyncio.sleep, chains: dict[str, list[tuple[str, str]]] | None = None):
        self.config, self.now, self.log, self.forbidden = config, now, log, tuple(f for f in forbidden if f)
        self.transport, self.sleep, self.chains = transport, sleep, chains or CHAINS
        self.replay = config.get("REPLAY") == "1"
        self.cassettes = ROOT / config.get("CASSETTE_DIR", "cassettes")
        self.budget, self.used = int(config.get("LLM_TOKEN_BUDGET") or DEFAULT_BUDGET), 0

    def chain(self, role: str) -> list[tuple[str, str, str, str]]:
        out = []
        for prefix, model_key in self.chains[role]:
            key, url, model = (self.config.get(k) for k in (f"{prefix}_API_KEY", f"{prefix}_BASE_URL", model_key))
            if key and url and model:
                out.append((prefix.lower(), url.rstrip("/") + "/chat/completions", key, model))
        return out

    async def chat(self, role: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                   tool_choice: Any = None, schema: dict[str, Any] | None = None) -> LLMReply:
        body: dict[str, Any] = {"messages": messages, **({"tools": tools} if tools else {}),
                                **({"tool_choice": tool_choice} if tool_choice else {})}
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "reply", "schema": schema}}
        if any(f in json.dumps(body, ensure_ascii=False) for f in self.forbidden):
            raise LLMError("refused: the request holds the run id (D-106)")
        key, started, notes = cassette.cassette_key(role, body, self.now), time.perf_counter(), []
        if self.replay:
            stored = cassette.load(self.cassettes, key)
            if stored is None:
                raise CassetteMiss(f"REPLAY=1 and no cassette {key[:16]} for this {role} request")
            reply, source = LLMReply.model_validate(stored["reply"]), "replayed"
        else:
            if self.used >= self.budget:
                raise BudgetExceeded(f"token budget {self.budget} used up ({self.used})")
            reply, notes = await self._live(role, body)
            cassette.save(self.cassettes, key, role, body, reply.model_dump())
            source = "recorded"
        self.used += reply.usage.get("total_tokens", 0)
        self.log({"role": role, "provider": reply.provider, "model": reply.model, **reply.usage,
                  "ms": round((time.perf_counter() - started) * 1000), "cassette": key[:16], "source": source,
                  "notes": notes, "used": self.used})
        return reply

    async def _live(self, role: str, body: dict[str, Any]) -> tuple[LLMReply, list[str]]:
        chain, notes = self.chain(role), []
        if not chain:
            raise LLMUnavailable(f"no provider configured for the {role} role")
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, transport=self.transport) as http:
            for provider, url, key, model in chain:
                for attempt in range(1, TRIES + 1):
                    response = None
                    try:
                        response = await http.post(url, json={"model": model, **body, "temperature": 0},
                                                   headers={"Authorization": f"Bearer {key}"})
                        if response.status_code == 200:
                            return _parse(response.json(), provider, model), notes
                        problem = f"HTTP {response.status_code} {response.text[:160]!r}"
                    except httpx.TransportError as exc:
                        problem = type(exc).__name__
                    notes.append(f"{provider}/{model} try {attempt}: {problem}")
                    wait = _wait(response, attempt)
                    if wait is None or (response is not None and response.status_code not in RETRYABLE):
                        break  # a wrong model id or key, or a quota that resets in hours: the next model, at once
                    if attempt < TRIES:
                        await self.sleep(wait)
        raise LLMUnavailable("every configured model failed: " + "; ".join(notes))
