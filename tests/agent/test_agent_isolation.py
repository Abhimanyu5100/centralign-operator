"""Static isolation rules for agent/. Each scan also runs on a planted violation, so it is never vacuous (N.124).

- agent/ never imports or opens bench/ (decision 11, N.10)
- business time only from ctx.now, never the wall clock (1.9, N.125)
- only agent/config.py reads the environment (N.30, N.92)
- no agent tool touches Acme's database or /__admin: sqlite3 only in the run store, no such strings, no
  registered tool spec names them (ORG-004 structural half, D-085, 3.9)
- agent/ does not import acme/ (Acme knowledge comes from acme/knowledge files, not Acme's code)
- every tool a `tool_in` policy rule names is registered (N.77)
"""

import ast
import json
from pathlib import Path

import pytest

from agent.policy.gate import PolicyGate
from agent.policy.loader import load_policies
from agent.policy.models import PolicyFile, ToolIn
from agent.tools.registry import Registry, ToolSpec, build_registry
from tests.agent.agent_fixtures import registry_with, spec

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "agent"
SOURCES = sorted(p for p in AGENT.rglob("*.py") if "__pycache__" not in p.parts)


def _strings(tree: ast.AST) -> list[str]:
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _imports(tree: ast.AST) -> list[str]:
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names += [f"{node.module or ''}.{a.name}" for a in node.names] + [node.module or ""]
    return names


def _top(name: str) -> str:
    return name.split(".")[0]


def bench_violations(tree: ast.AST) -> list[str]:
    found = [n for n in _imports(tree) if _top(n) == "bench"]
    return found + [s for s in _strings(tree) if "bench" in s.lower()]


WALL_CLOCK_METHODS = {"now", "utcnow", "today"}
TIME_FUNCTIONS = {"time", "time_ns", "localtime", "gmtime", "ctime"}


def wall_clock_violations(tree: ast.AST) -> list[str]:
    found = [n for n in _imports(tree) if n in {f"time.{f}" for f in TIME_FUNCTIONS}]
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr, owner = node.func.attr, node.func.value
            if attr in WALL_CLOCK_METHODS:
                found.append(ast.unparse(node))
            elif attr in TIME_FUNCTIONS and isinstance(owner, ast.Name) and owner.id == "time":
                found.append(ast.unparse(node))
    return found


ENV_NAMES = {"environ", "environb", "getenv", "getenvb", "putenv", "unsetenv"}


def env_violations(tree: ast.AST) -> list[str]:
    found = [n for n in _imports(tree) if n.split(".")[-1] in ENV_NAMES or _top(n) == "dotenv"]
    return found + [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in ENV_NAMES]


FORBIDDEN_TARGETS = ("__admin", "acme.db", "acme/data")


def database_violations(tree: ast.AST) -> list[str]:
    found = [n for n in _imports(tree) if _top(n) == "sqlite3"]
    return found + [s for s in _strings(tree) if any(t in s.lower() for t in FORBIDDEN_TARGETS)]


def acme_import_violations(tree: ast.AST) -> list[str]:
    return [n for n in _imports(tree) if _top(n) == "acme"]


SCANS = {  # scan -> (files allowed to break it, planted violations that must be caught, look-alikes that must not)
    "bench": (bench_violations, set(),
              ["import bench.tasks", "from bench.checkers import engine", "open('bench/tasks/T1.yaml')",
               "importlib.import_module('bench.checkers')", "ROOT / 'Bench'"],
              ["# comment about bench is fine", "x = 'benefit'"]),
    "wall clock": (wall_clock_violations, set(),
                   ["datetime.now()", "datetime.datetime.now(tz)", "date.today()", "datetime.utcnow()",
                    "time.time()", "from time import time", "time.localtime()"],
                   ["ctx.now", "time.perf_counter()", "x = now"]),
    "environment": (env_violations, {"config.py"},
                    ["os.environ['X']", "os.getenv('X')", "from os import environ", "from dotenv import load_dotenv",
                     "os.putenv('X', '1')"],
                    ["config['X']", "import os.path"]),
    "database": (database_violations, {"store.py"},
                 ["import sqlite3", "from sqlite3 import connect", "p = 'acme/data/acme.db'", "url = '/__admin/reset'",
                  "'/__ADMIN/x'"],
                 ["p = 'runs/runs.db'", "'/api/invoices'"]),
    "acme import": (acme_import_violations, set(), ["import acme.web", "from acme import services"],
                    ["from agent.policy import loader"]),
}


def _source_violations(scan: str) -> dict[str, list[str]]:
    check, allowed, _, _ = SCANS[scan]
    found = {}
    for path in SOURCES:
        rel = path.relative_to(AGENT).as_posix()
        if rel in allowed:
            continue
        hits = check(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        if hits:
            found[rel] = hits
    return found


@pytest.mark.parametrize("scan", SCANS)
def test_agent_source_passes_the_scan(scan):
    assert SOURCES, "no agent sources found"
    assert _source_violations(scan) == {}


@pytest.mark.parametrize("scan,planted", [(s, p) for s, v in SCANS.items() for p in v[2]])
def test_a_planted_violation_is_caught(scan, planted):
    assert SCANS[scan][0](ast.parse(planted))


@pytest.mark.parametrize("scan,lookalike", [(s, p) for s, v in SCANS.items() for p in v[3]])
def test_a_lookalike_is_not_flagged(scan, lookalike):
    assert not SCANS[scan][0](ast.parse(lookalike))


def test_the_allowed_files_exist():
    # an exemption for a file that was renamed or removed would silently exempt nothing
    for _, allowed, _, _ in SCANS.values():
        assert all((AGENT / rel).is_file() for rel in allowed)


# --- registered tools: no spec names Acme's database or /__admin (D-085) ---------------------------------------


def spec_target_violations(tool: ToolSpec) -> list[str]:
    text = json.dumps([tool.llm_schema(), tool.undo, tool.no_undo_reason,
                       [c.description for c in tool.preconditions + tool.postconditions]]).lower()
    return [t for t in FORBIDDEN_TARGETS if t in text]


def test_no_registered_tool_names_the_acme_database_or_admin_paths():
    # vacuous until Day 2.2 registers the first real tools (N.124); the fixture below keeps the check honest
    assert {t.name: spec_target_violations(t) for t in build_registry().specs() if spec_target_violations(t)} == {}


@pytest.mark.parametrize("description", ["Reset Acme through /__admin/reset.", "Read rows from acme/data/acme.db."])
def test_a_tool_that_names_a_forbidden_target_is_caught(description):
    assert spec_target_violations(spec(description=description))


# --- every tool a policy names is registered (N.77) ------------------------------------------------------------


def missing_policy_tools(policies: PolicyFile, registry: Registry) -> list[str]:
    registered = {t.name for t in registry.specs()}
    named = {name for rule in policies.rules for cond in rule.when if isinstance(cond, ToolIn) for name in cond.tools}
    return sorted(named - registered)


def test_every_tool_named_by_a_policy_is_registered():
    # policies.yaml has no tool_in rule today, so this holds trivially until one is added (N.77)
    assert missing_policy_tools(load_policies(), build_registry()) == []


def test_a_policy_naming_an_unregistered_tool_is_caught():
    policies = PolicyFile.model_validate({"schema_version": 0, "rules": [
        {"id": "ORG-901", "level": "org", "enforced_by": "runtime", "effect": "deny", "message": "test",
         "when": [{"type": "tool_in", "tools": ["echo", "no_such_tool"]}]}]})
    assert missing_policy_tools(policies, registry_with(PolicyGate(), spec())) == ["no_such_tool"]
