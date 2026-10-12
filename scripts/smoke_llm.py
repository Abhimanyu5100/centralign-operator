"""LLM smoke test through agent/llm/client.py (`make smoke`): per configured model, a plain call, a forced tool call,
the tool result sent back (a second turn), JSON-schema output, and a long-ish input. Prints one table: what worked,
latency, tokens, whether tool-call ids came back empty, rate-limit headers from the responses, and any 429 body.

It never prints a request header or a key. Cassettes go to cassettes/smoke/ (ignored by git). Live: spends a few
requests per model.
"""

import asyncio
import json
import re
import sys
import time

import httpx

from agent.config import load_config
from agent.llm.client import LLMClient, LLMError

MODELS = [("GEMINI", "GEMINI_MODEL"), ("GEMINI", "GEMINI_FLASH2_MODEL"), ("GEMINI", "GEMINI_LITE_MODEL"),
          ("GEMINI", "GEMINI_LITE2_MODEL"), ("GROQ", "GROQ_PLAN_MODEL"), ("GROQ", "GROQ_JUDGE_MODEL"),
          ("GROQ", "GROQ_COMPACTION_MODEL"), ("OPENROUTER", "OPENROUTER_FALLBACK_MODEL")]
TOOL = {"type": "function", "function": {
    "name": "record_invoice", "description": "Record an invoice number and its total.",
    "parameters": {"type": "object", "additionalProperties": False, "required": ["invoice_no", "amount_paise"],
                   "properties": {"invoice_no": {"type": "string", "description": "Invoice number"},
                                  "amount_paise": {"type": "integer", "description": "Total in paise"}}}}}
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["decision", "reason"],
          "properties": {"decision": {"type": "string", "enum": ["proceed", "ask", "decline"]},
                         "reason": {"type": "string"}}}


class Spy(httpx.AsyncBaseTransport):
    """Keeps each response's body and rate-limit headers (never the request's headers)."""

    def __init__(self):
        self.inner, self.bodies, self.limits = httpx.AsyncHTTPTransport(), [], {}

    async def handle_async_request(self, request):
        response = await self.inner.handle_async_request(request)
        await response.aread()
        self.limits.update({k: v for k, v in response.headers.items() if k.lower().startswith(("x-ratelimit", "retry"))})
        self.bodies.append((response.status_code, response.content.decode(errors="replace")))
        return response


async def probe(config, prefix: str, model_key: str) -> dict:
    spy, events = Spy(), []
    client = LLMClient({**config, "REPLAY": "0", "CASSETTE_DIR": "cassettes/smoke"}, now="2026-10-09T00:00:00+05:30",
                       log=events.append, transport=spy, chains={"reason": [(prefix, model_key)]})
    row: dict = {"model": config.get(model_key, "-")}

    async def step(name, call):
        started = time.perf_counter()
        try:
            row[name] = await call()
        except LLMError as exc:
            row[name] = f"FAIL {str(exc)[:120]}"
        row[name + "_s"] = round(time.perf_counter() - started, 1)

    ask = [{"role": "user", "content": "Reply with exactly the word pong."}]
    await step("plain", lambda: _plain(client, ask))
    turn = [{"role": "user", "content": "Invoice INV-77 totals Rs 1,250.50. Record it with the tool."}]
    replies = []

    async def tool():
        reply = await client.chat("reason", turn, tools=[TOOL],
                                  tool_choice={"type": "function", "function": {"name": "record_invoice"}})
        replies.append(reply)
        call = reply.tool_calls[0] if reply.tool_calls else None
        raw_ids = [c.get("id") for b in spy.bodies[-1:] for c in _calls(b[1])]
        row["empty_ids"] = any(not i for i in raw_ids) if raw_ids else "n/a"
        return f"ok {call.arguments}" if call and call.arguments == {"invoice_no": "INV-77", "amount_paise": 125050} \
            else f"WRONG {call.arguments if call else reply.content!r}"
    await step("tool", tool)

    async def round_trip():
        if not replies or not replies[0].tool_calls:
            return "skipped"
        call = replies[0].tool_calls[0]
        reply = await client.chat("reason", [*turn, replies[0].message,
                                             {"role": "tool", "tool_call_id": call.id, "content": '{"ok": true}'}],
                                  tools=[TOOL])
        return "ok" if reply.content and not reply.tool_calls else f"WRONG {reply.content!r} {len(reply.tool_calls)} calls"
    await step("round_trip", round_trip)

    async def schema():
        reply = await client.chat("reason", [{"role": "user", "content": "Vendor Kapoor Steel is not in the vendor "
                                              "master. Should we pay its invoice? Answer as JSON."}], schema=SCHEMA)
        data = json.loads(reply.content or "")
        return f"ok {data['decision']}" if set(data) == {"decision", "reason"} else f"WRONG {data}"
    await step("schema", schema)

    lines = 500 if prefix == "GEMINI" else 220  # about 6,000 and 2,700 tokens: under Groq's 8K TPM
    text = "\n".join(f"Line {i}: item widget, quantity 3, unit price Rs 40." if i != lines // 2 else
                     f"Line {i}: the reference code is 7341." for i in range(lines))
    await step("long", lambda: _contains(client, [{"role": "user", "content": text + "\n\nWhat is the reference code? "
                                                   "Reply with the number only."}], "7341"))
    row["prompt_tokens"] = [e["prompt_tokens"] for e in events]
    row["limits"] = spy.limits
    row["errors"] = [b for b in spy.bodies if b[0] != 200]
    return row


def _calls(body: str) -> list[dict]:
    try:
        return json.loads(body)["choices"][0]["message"].get("tool_calls") or []
    except (ValueError, KeyError, IndexError, TypeError):
        return []


async def _plain(client, messages):
    reply = await client.chat("reason", messages)
    return "ok" if "pong" in (reply.content or "").lower() else f"WRONG {reply.content!r}"


async def _contains(client, messages, wanted):
    reply = await client.chat("reason", messages)
    return "ok" if wanted in (reply.content or "") else f"WRONG {reply.content!r}"


async def main() -> int:
    config = load_config()
    rows = []
    only = {k for a in sys.argv[1:] for k in a.split(",")}  # e.g. GEMINI_MODEL: probe only these model keys
    for prefix, model_key in MODELS:
        if only and model_key not in only:
            continue
        if not (config.get(f"{prefix}_API_KEY") and config.get(f"{prefix}_BASE_URL") and config.get(model_key)):
            print(f"skip {model_key}: not configured")
            continue
        rows.append(await probe(config, prefix, model_key))
    cols = ["model", "plain", "tool", "empty_ids", "round_trip", "schema", "long", "prompt_tokens"]
    print("| " + " | ".join(cols) + " |\n|" + " --- |" * len(cols))
    for r in rows:
        print("| " + " | ".join(str(r.get(c, "")) + (f" ({r[c + '_s']} s)" if c + "_s" in r else "") for c in cols) + " |")
    for r in rows:
        print(f"\n{r['model']} rate-limit headers: {r['limits'] or 'none'}")
        for status, body in r["errors"]:
            quota = re.findall(r'"(?:quotaMetric|quotaId|quotaValue|retryDelay)": "([^"]+)"', body)
            print(f"  HTTP {status}: {', '.join(quota) or body[:300]}")
    return 0 if rows and all(str(r.get(c, "ok")).startswith(("ok", "n/a")) or c == "empty_ids"
                             for r in rows for c in ("plain", "tool", "round_trip", "schema", "long")) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
