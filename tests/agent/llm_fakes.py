"""A scripted stand-in for the LLM client: each `chat` returns the next scripted reply (or calls it with the
messages), and every request is kept so a test can look at what the model was shown. No network, no cassettes."""

import json
from typing import Any

from agent.llm.client import LLMReply, ToolCall


def say(text: str) -> LLMReply:
    return LLMReply(content=text, message={"role": "assistant", "content": text}, provider="fake", model="fake")


def calls(*pairs: tuple[str, dict[str, Any]]) -> LLMReply:
    """One turn with these tool calls, in order."""
    tool_calls = [ToolCall(id=f"c{i}", name=name, arguments=args) for i, (name, args) in enumerate(pairs)]
    raw = [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
           for c in tool_calls]
    return LLMReply(tool_calls=tool_calls, message={"role": "assistant", "content": "", "tool_calls": raw},
                    provider="fake", model="fake")


class FakeLLM:
    def __init__(self, *replies: Any):
        self.replies, self.requests = list(replies), []

    async def chat(self, role: str, messages: list[dict[str, Any]], tools: Any = None, tool_choice: Any = None,
                   schema: Any = None) -> LLMReply:
        self.requests.append({"role": role, "messages": [dict(m) for m in messages], "tools": tools})
        if not self.replies:
            raise AssertionError("the fake LLM ran out of scripted replies")
        reply = self.replies.pop(0)
        return reply(messages) if callable(reply) else reply

    def tool_texts(self) -> list[str]:
        """The tool messages of the last request, in order."""
        return [m["content"] for m in self.requests[-1]["messages"] if m["role"] == "tool"]
