"""Asking and refusing as run steps (register 1.5, 1.7; Day 3 plan A4).

`ask_user` records a question with its candidates and `declare_infeasible` records a refusal with its evidence.
Both change nothing in the company (side effect `read`) and both END the run: the scripted agent stops after
them, and the Day 4 executor will too. The run's status still comes from the verifier, which checks that nothing
was written (`needs_clarification`, `infeasible`); the report lists the question or the refusal from these events.
"""

from pydantic import BaseModel, ConfigDict, Field

from agent.tools.registry import RunContext, ToolResult, ToolSpec

ENDING_TOOLS = {"ask_user": "asked", "declare_infeasible": "infeasible"}


class AskArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=500, description="One clear question for the requester")
    candidates: list[str] = Field(default_factory=list, max_length=10,
                                  description="The options found, e.g. the matching invoice numbers")


class InfeasibleArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=500, description="Why the request cannot be done")
    evidence: list[str] = Field(default_factory=list, max_length=10,
                                description="What the reads showed, e.g. 'find_vendors q=<name>: no match'")


async def ask_user(args: AskArgs, ctx: RunContext) -> ToolResult:
    return ToolResult(ok=True, detail="question recorded; the run ends here and waits for the answer",
                      data={"question": args.question, "candidates": args.candidates})


async def declare_infeasible(args: InfeasibleArgs, ctx: RunContext) -> ToolResult:
    return ToolResult(ok=True, detail="refusal recorded; the run ends here",
                      data={"reason": args.reason, "evidence": args.evidence})


def ask_tools() -> list[ToolSpec]:
    return [
        ToolSpec(name="ask_user", description="Ask the requester one question when a required value is unknown or "
                                              "ambiguous; ends the run.",
                 args_model=AskArgs, side_effect="read", channel="code", fn=ask_user),
        ToolSpec(name="declare_infeasible", description="Decline a request the reads show cannot be done, citing "
                                                        "them; ends the run.",
                 args_model=InfeasibleArgs, side_effect="read", channel="code", fn=declare_infeasible),
    ]
