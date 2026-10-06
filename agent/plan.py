"""The plan a run follows: the planner's output from Day 4, and the verifier's input (D-131).

In Phase A each oracle passes a hand-written plan in as data. Day 3.1 needs only the SOP the run follows: with no
SOP (`sop_id` None) every write needs an action approval (ORG-009, D-081). Milestones and their predicates arrive
with the verifier in Day 3.2.
"""

from pydantic import BaseModel, ConfigDict, Field


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sop_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{1,40}$")
