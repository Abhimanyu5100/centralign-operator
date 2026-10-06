"""The run report against the D-098 contract: the real harness (bench/live.run_oracle) runs the oracles for T4, T5,
T6 and T9 x3 on an in-process Acme, and `engine.check` judges each report (status and report checks). Broken
reports must fail. Register 6.10, 7.1, 7.6; N.109, N.157; D-112, D-156."""

import asyncio
import json

import httpx
import pytest

from agent.store import DEFAULT_PATH
from bench import tasks
from bench.checkers import engine
from bench.live import run_oracle
from bench.oracles import oracle_for
from tests.agent.acme_fixtures import CONFIG, PASSWORD, sandbox  # noqa: F401  (sandbox is a fixture)


class InProcessAcme:
    """The harness's Acme interface (admin calls, agent config, database file) over the in-process sandbox."""

    def __init__(self, sandbox):
        self.sandbox, self.db_path = sandbox, sandbox.db_path

    def admin(self, method: str, path: str, **params):
        return self.sandbox.admin_call(method, path, **params)

    def agent_config(self, timeout=None):
        return dict(CONFIG)


def oracle(sandbox, run_id: str):
    task = tasks.load(run_id.partition(":")[0])
    run = next(r for r in tasks.runs(task) if r.run_id == run_id)
    return asyncio.run(run_oracle(InProcessAcme(sandbox), task, run, oracle_for(run_id), store=sandbox.store,
                                  transport=httpx.ASGITransport(app=sandbox.app)))


@pytest.mark.parametrize("run_id", ["T4", "T5", "T6", "T9:none", "T9:approve", "T9:reject"])
def test_the_report_meets_the_contract_and_passes_its_report_checks(sandbox, run_id):
    result = oracle(sandbox, run_id)
    report_checks = [c for c in result.result.checks if c.name.startswith("report")]
    assert len(report_checks) == 1 + len(result.run.report_checks)  # the status plus every report check ran
    assert result.result.passed, [(c.name, c.detail) for c in result.result.checks if not c.ok]
    for key in ("status", "questions", "security_findings", "evidence", "action_approvals", "side_effects"):
        assert key in result.report


BROKEN = {
    "T4": lambda r: [q.update(candidates=["INV-778"]) for q in r["questions"]],
    "T5": lambda r: r.update(evidence=[]),
    "T6": lambda r: r.update(security_findings=[]),
    "T9:approve": lambda r: [a.update(decision="pending") for a in r["action_approvals"]],
    "T9:none": lambda r: r.update(status="completed"),
}


@pytest.mark.parametrize("run_id", BROKEN)
def test_a_broken_report_fails_the_engine(sandbox, run_id):
    result = oracle(sandbox, run_id)
    broken = json.loads(json.dumps(result.report))
    BROKEN[run_id](broken)
    diff = sandbox.admin_call("GET", "/__admin/diff", since=sandbox.admin_call("POST", "/__admin/snapshot")["snapshot"])
    assert not engine.check(result.run, sandbox.db_path, diff["tables"], broken).passed


def test_the_report_takes_its_status_only_from_the_verifier(sandbox):
    result = oracle(sandbox, "T2")
    verdicts = [e for e in sandbox.store.events(result.agent_run_id) if e["type"] == "verifier_result"]
    assert result.report["status"] == verdicts[-1]["payload"]["status"] == "completed"
    assert result.report["status_reasons"] == verdicts[-1]["payload"]["reasons"]


def test_the_report_holds_no_secret_or_account_number(sandbox):
    result = oracle(sandbox, "T6")
    text = json.dumps(result.report)
    assert PASSWORD not in text and "123456789012" not in text and "XXXXXXXX9012" in text
    folder = sandbox.store.path.parent / result.agent_run_id
    assert PASSWORD not in (folder / "report.md").read_text() and (folder / "report.json").is_file()


def test_t9_reports_the_predicted_email_and_the_decision(sandbox):
    approval = oracle(sandbox, "T9:approve").report["action_approvals"][0]
    assert approval["predicted"]["to"] == "accounts@sharmalogistics.example" and approval["decision"] == "approved"
    assert approval["used"] is True and approval["policy_ids"] == ["ORG-005"]
    assert approval["predicted"]["request"] == "POST /api/mail/send"


def test_bench_runs_never_land_in_the_operators_store(sandbox, tmp_path, monkeypatch):
    """N.164: `make ui` reads runs/runs.db; harness runs go to their own store."""
    import bench.live as live
    from agent.store import RunStore
    monkeypatch.setattr(live, "BENCH_STORE", tmp_path / "bench.db")
    task = tasks.load("T2")
    result = asyncio.run(live.run_oracle(InProcessAcme(sandbox), task, tasks.runs(task)[0], oracle_for("T2"),
                                         transport=httpx.ASGITransport(app=sandbox.app)))
    assert RunStore(tmp_path / "bench.db").events(result.agent_run_id)
    assert live.BENCH_STORE != DEFAULT_PATH and DEFAULT_PATH.name == "runs.db"
