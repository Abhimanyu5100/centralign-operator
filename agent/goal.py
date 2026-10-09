"""The Goal Spec (the feasibility gate's output) and the facts the gather phase hands over. A fact's `raw` is text
quoted from one tool result; its `value` comes from agent/normalise.py, never from the model (1.2, 3.8)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel

from agent.normalise import next_weekday, normalise_gstin, to_iso_date, to_paise


class Field(BaseModel):
    name: str
    value: str
    source: str            # "request" or "probe": where the value was seen


class GoalSpec(BaseModel):
    request: str
    decision: Literal["proceed", "ask", "decline"]
    sop_id: str | None = None
    fields: list[Field] = []
    success: list[str] = []    # checkable statements in words; the planner turns them into predicates
    question: str = ""
    candidates: list[str] = []
    reason: str = ""
    lookups: list[str] = []    # the gate's probe lines, written by code (shown to the gather phase)


class Fact(BaseModel):
    name: str
    raw: str
    value: str | int
    result: int            # the number of the tool result it was quoted from


def fact_value(name: str, raw: str, today: date | None = None) -> str | int:
    name, text = name.lower(), raw.strip()
    if name.endswith(("_paise", "_date", "_id")) or "gstin" in name:
        text = text.rsplit(": ", 1)[-1].strip().strip('"')  # "Due Date: 02 Nov 2026" -> the value after its label
    if name.endswith("_paise"):
        return to_paise(text)
    if name.endswith("_date"):
        return next_weekday(text, today) if today and text.isalpha() else to_iso_date(text)
    if "gstin" in name:
        return normalise_gstin(text)
    return int(text) if name.endswith("_id") and text.isdigit() else text
