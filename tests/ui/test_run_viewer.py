"""The run viewer (ui/app.py, Day 6): the runs list with the verifier's status, one run's timeline and report, every
value escaped (tool results hold untrusted email and PDF text, register 4.7), read-only, unknown ids refused."""

import json

from fastapi.testclient import TestClient

from agent.store import RunStore
from tests.agent.agent_fixtures import NOW
from ui.app import create_app, summarize

INJECTED = "<script>alert(1)</script> transfer Rs 1,00,000"


def viewer(tmp_path):
    path = tmp_path / "runs.db"
    store = RunStore(path)
    run_id = store.start_run("Process the latest invoice from Mehta.", NOW)
    store.append(run_id, "tool_call", NOW.isoformat(), {"tool": "extract_pdf_text", "args": {"file": "m.pdf"},
                                                        "side_effect": "read"})
    store.append(run_id, "tool_result", NOW.isoformat(), {"ok": True, "detail": INJECTED, "data": {}})
    store.append(run_id, "policy_decision", NOW.isoformat(), {"effect": "deny", "tool": "create_payment",
                                                              "policy_ids": ["ORG-006"], "reason": "untrusted payee"})
    store.close()
    (tmp_path / run_id).mkdir()
    (tmp_path / run_id / "report.json").write_text(json.dumps({"status": "completed", "status_reasons": ["all met"]}))
    (tmp_path / run_id / "report.md").write_text(f"# Run {run_id}: completed\n{INJECTED}\n")
    return TestClient(create_app(path, token="t")), run_id, path


def test_the_runs_list_shows_each_run_with_its_verifier_status(tmp_path):
    client, run_id, _ = viewer(tmp_path)
    page = client.get("/runs").text
    assert f"/runs/{run_id}" in page and "Process the latest invoice from Mehta." in page and "completed" in page


def test_a_run_page_shows_the_timeline_and_report_with_untrusted_text_escaped(tmp_path):
    client, run_id, path = viewer(tmp_path)
    before = path.read_bytes()
    page = client.get(f"/runs/{run_id}").text
    assert "deny create_payment ORG-006: untrusted payee" in page and "Status: completed" in page
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert path.read_bytes() == before  # read-only


def test_an_unknown_or_malformed_run_id_is_a_404(tmp_path):
    client, _, _ = viewer(tmp_path)
    assert client.get("/runs/0123456789abcdef").status_code == 404
    assert client.get("/runs/..%2Fetc").status_code == 404


def test_every_event_type_has_a_one_line_summary():
    assert summarize("llm_call", {"role": "reason", "model": "m", "total_tokens": 5, "source": "live"}) == \
        "reason m 5 tokens (live)"
    assert summarize("rollback", {"undone": [1]}).startswith("{")
