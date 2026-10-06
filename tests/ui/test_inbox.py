"""The action-approval inbox (ui/app.py): cards with the predicted outcome, approve and reject with the form token,
the JSON twin the scripted approver uses. Register P.4, P.5, N.150."""

import pytest
from fastapi.testclient import TestClient

from agent.policy.approvals import ApprovalStore
from agent.store import RunStore
from tests.agent.agent_fixtures import NOW
from ui.app import create_app

PREDICTED = {"tool": "send_mail", "args": {"to": "accounts@sharmalogistics.example", "subject": "Under review",
                                           "body": "<script>alert(1)</script> INV-1043 is under review"},
             "request": "POST /api/mail/send", "side_effect": "external_comms", "channel": "api",
             "effect": "external comms through POST /api/mail/send; sent mail cannot be recalled"}


@pytest.fixture
def inbox(tmp_path):
    path = tmp_path / "runs.db"
    store = RunStore(path)
    run_id = store.start_run("Email Sharma Logistics that invoice INV-1043 is under review.", NOW)
    approval_id = ApprovalStore(store).request(run_id, "f" * 64, ["ORG-005"], "ORG-005 require_approval: external",
                                               PREDICTED)
    store.close()
    client = TestClient(create_app(path, token="t0ken"))
    yield client, approval_id, path


def status_of(path, approval_id) -> str:
    store = RunStore(path)
    try:
        return ApprovalStore(store).get(approval_id).status
    finally:
        store.close()


def test_the_inbox_shows_each_pending_call_with_its_predicted_outcome_escaped(inbox):
    client, approval_id, _ = inbox
    page = client.get("/").text
    for text in ("accounts@sharmalogistics.example", "POST /api/mail/send", "external_comms", "Held by ORG-005",
                 "sent mail cannot be recalled", "Email Sharma Logistics", f"Approve {approval_id}",
                 f"Reject {approval_id}"):
        assert text in page
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page


def test_approving_through_the_form_needs_the_token(inbox):
    client, approval_id, path = inbox
    for token in ("", "wrong"):
        response = client.post(f"/approvals/{approval_id}/approve", data={"token": token}, follow_redirects=False)
        assert response.status_code == 403 and status_of(path, approval_id) == "pending"
    response = client.post(f"/approvals/{approval_id}/approve", data={"token": "t0ken", "by": "abhi"},
                           follow_redirects=False)
    assert response.status_code == 303 and status_of(path, approval_id) == "approved"
    assert "approved by abhi" in client.get("/").text


def test_deciding_twice_is_refused(inbox):
    client, approval_id, path = inbox
    assert client.post(f"/approvals/{approval_id}/reject", data={"token": "t0ken"}, follow_redirects=False).status_code == 303
    again = client.post(f"/approvals/{approval_id}/approve", data={"token": "t0ken"}, follow_redirects=False)
    assert again.status_code == 409 and status_of(path, approval_id) == "rejected"


def test_the_json_twin_lists_with_the_token_and_decides(inbox):
    client, approval_id, path = inbox
    listing = client.get("/api/approvals", params={"status": "pending"}).json()["data"]
    assert [a["approval_id"] for a in listing["items"]] == [approval_id] and listing["token"] == "t0ken"
    assert listing["items"][0]["predicted"]["args"]["to"] == "accounts@sharmalogistics.example"
    response = client.post(f"/api/approvals/{approval_id}/approve", json={"token": listing["token"], "by": "bench"})
    assert response.status_code == 200 and response.json()["data"]["status"] == "approved"
    assert client.get("/api/approvals", params={"status": "pending"}).json()["data"]["items"] == []


@pytest.mark.parametrize("path, body, status", [
    ("/api/approvals/A-nope/approve", {"token": "t0ken"}, 404),
    ("/api/approvals/{id}/approve", {"token": "nope"}, 403),
    ("/api/approvals/{id}/approve", {"token": "t0ken", "decision": "x"}, 422),  # strict body
    ("/api/approvals/{id}/maybe", {"token": "t0ken"}, 422),
])
def test_bad_decisions_are_typed_and_change_nothing(inbox, path, body, status):
    client, approval_id, db = inbox
    assert client.post(path.format(id=approval_id), json=body).status_code == status
    assert status_of(db, approval_id) == "pending"


def test_a_random_token_is_made_when_none_is_given(tmp_path):
    first, second = create_app(tmp_path / "a.db"), create_app(tmp_path / "b.db")
    assert len(first.state.token) >= 24 and first.state.token != second.state.token
