"""Prompt freeze (Day 5 plan, N.187): every input that reaches an LLM request is part of the cassette key, so a
change to any of them makes the recorded runs miss on replay. This test pins one hash over all of them. When it
fails: re-record the affected tasks live (`make run TASK=...`), check them in replay (`REPLAY=1`), record the edit as
a decision row with its re-record list, then update PINNED. Frozen 2026-10-09 (end of Day 5.2)."""

import hashlib
import importlib
import inspect
import json

from agent import executor, feasibility, planner, run
from agent.memory.knowledge import SOP_DIR
from agent.tools.api import CATALOG_PATH
from tests.agent.acme_fixtures import drive, sandbox  # noqa: F401  (sandbox is a fixture)

judge = importlib.import_module("agent.verifier.judge")  # the module (agent.verifier exports the function)
PINNED = "5e978633e60ddebbc10950de1f79bb0f774597b5328a6c4b47a027c3f6ad550e"


def prompt_inputs(registry) -> str:
    constants = [executor.SYSTEM, executor.GATHER, executor.ACT, executor.FACTS_TOOL, executor.MAX_CHARS,
                 feasibility.PROMPT, feasibility.SCHEMA, planner.PROMPT, planner.REPLAN, judge.PROMPT, judge.SCHEMA,
                 judge.MAX_CHARS]
    builders = [executor.brief, executor.prune, executor.Executor.tools, executor.Executor.offered,
                executor.Executor.show, executor.Executor.act, executor.Executor.execute, feasibility.probe,
                feasibility.understand, planner.read_tools, planner.plan_errors, planner.replan_errors, planner.make_plan,
                run._work, judge.judge]  # plan_errors and replan_errors: their problems reach the planner on a retry
    knowledge = [p.read_text(encoding="utf-8") for p in sorted(SOP_DIR.glob("*.md"))]
    knowledge += [CATALOG_PATH.read_text(encoding="utf-8"),
                  (CATALOG_PATH.parent / "policies.yaml").read_text(encoding="utf-8")]
    tools = [(s.name, s.description, s.args_model.model_json_schema()) for s in registry.specs()]
    return json.dumps([constants, [inspect.getsource(f) for f in builders], knowledge, tools], default=str)


def test_no_prompt_input_changed_since_the_freeze(sandbox):
    agent_run = sandbox.run()
    digest = hashlib.sha256(prompt_inputs(agent_run.registry).encode()).hexdigest()
    drive(agent_run, lambda run: run.begin())
    assert digest == PINNED, (f"a prompt input changed after the freeze (now {digest}): re-record the affected "
                              "cassettes, record the edit as a decision row, then update PINNED")
