"""Chaos profiles (part 9): per profile the fault appears, the same seed reproduces it, reset clears it and
chaos off changes nothing; only ops-agent is faulted; admin traffic is exempt. Risks 0.4, N.18, N.19, N.98,
N.102 to N.108; decisions D-094, D-095."""

import threading
import time

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from acme import chaos
from acme.app import create_app
from tests.acme.conftest import make_client
from tests.acme.htmlutil import Page
from tests.acme.test_admin import H, TOKEN, data
from tests.acme.test_api import INVOICE, assert_typed_error, count, post_invoice
from tests.acme.test_ui import INVOICE_FORM, token_of


@pytest.fixture(autouse=True)
def admin_token(monkeypatch):
    monkeypatch.setenv("ACME_ADMIN_TOKEN", TOKEN)


@pytest.fixture
def admin(db_file):
    return TestClient(create_app(db_file), follow_redirects=False, headers=H)


def set_chaos(admin, profile, seed=0):
    return data(admin.post("/__admin/chaos", params={"profile": profile, "seed": seed}))


def events(admin):
    return data(admin.get("/__admin/chaos/events"))


def effects(admin):
    return [(e["effect"], e["channel"], e["method"], e["path"], e["attempt"]) for e in events(admin)["items"]]


def seed_where(rule) -> int:
    return next(s for s in range(10_000) if rule(s))


def flaky(seed, n):
    return chaos.fires("flaky_500", seed, n, chaos.FLAKY_RATE)


def ticket(client, kind="laptop", employee_id=None, world=None):
    return client.post("/api/it-tickets", json={"type": kind, "employee_id": employee_id or world["employee"]["id"]})


def mail(client, i):
    return client.post("/api/mail/send", headers={"Idempotency-Key": f"mail-{i}"},
                       json={"to": "finance@acme.example", "subject": f"Note {i}", "body": "Hello"})


def ui_invoice_form(client, **overrides):
    token = token_of(client.get("/invoices/new").text)
    return client.post("/invoices/new", data={**INVOICE_FORM, "idempotency_token": token, **overrides})


# --- rename_submit_button (0.2, 2.1) ----------------------------------------------------------------


def test_rename_changes_the_button_name_and_not_the_behaviour(db, admin, agent):
    set_chaos(admin, "rename_submit_button")
    buttons = Page(agent.get("/invoices/new").text).buttons
    assert "Submit invoice" in buttons and "Save invoice" not in buttons
    r = ui_invoice_form(agent)
    assert r.status_code == 303 and r.headers["location"].startswith("/invoices/")
    assert db.execute("SELECT COUNT(*) FROM invoices WHERE invoice_no = 'INV-3001'").fetchone()[0] == 1
    assert events(admin)["fired"] is True
    assert {e[0] for e in effects(admin)} == {"label_renamed"}


def test_rename_reproduces_and_reset_clears_it(admin, agent, db_file):
    for _ in range(2):
        set_chaos(admin, "rename_submit_button", seed=5)
        assert "Submit invoice" in Page(agent.get("/invoices/new").text).buttons
        assert effects(admin) == [("label_renamed", "ui", "GET", "/invoices/new", None)]
        data(admin.post("/__admin/reset"))
        assert events(admin)["items"] == []
        agent = make_client(db_file, "ops-agent")  # reset drops sessions
        assert "Save invoice" in Page(agent.get("/invoices/new").text).buttons


# --- flaky_500 (N.19, N.103) ----------------------------------------------------------------------


def test_flaky_500_fails_before_anything_is_written_and_the_retry_passes(db, admin, agent, world):
    set_chaos(admin, "flaky_500", seed_where(lambda s: flaky(s, 1) and not flaky(s, 2)))
    before = {t: count(db, t) for t in ("it_tickets", "audit_log", "meta")}
    clock_before = db.execute("SELECT value FROM meta WHERE key = 'now'").fetchone()[0]
    r = ticket(agent, world=world)
    assert_typed_error(r, 500, "server_error")
    assert "chaos" not in r.text.lower()  # looks exactly like a real 500
    assert {t: count(db, t) for t in before} == before
    assert db.execute("SELECT value FROM meta WHERE key = 'now'").fetchone()[0] == clock_before
    assert ticket(agent, world=world).status_code == 201  # the same write again is a retry: never faulted twice
    assert count(db, "it_tickets") == before["it_tickets"] + 1
    assert effects(admin) == [("server_error", "api", "POST", "/api/it-tickets", 1)]


def test_flaky_500_on_an_idempotent_write_stores_no_key_so_the_retry_writes(db, admin, agent):
    set_chaos(admin, "flaky_500", seed_where(lambda s: flaky(s, 1)))
    invoices = count(db, "invoices")
    assert_typed_error(post_invoice(agent, key="k-flaky"), 500, "server_error")
    assert count(db, "invoices") == invoices and count(db, "idempotency_keys") == 0
    r = post_invoice(agent, key="k-flaky")
    assert r.status_code == 201 and "Idempotent-Replayed" not in r.headers


def test_flaky_500_on_the_ui_shows_the_error_page_and_writes_nothing(db, admin, agent, world):
    set_chaos(admin, "flaky_500", seed_where(lambda s: flaky(s, 1)))
    form = {"type": "accounts", "employee_id": str(world["employee"]["id"])}
    tickets = count(db, "it_tickets")
    r = agent.post("/it-tickets/new", data=form)
    assert r.status_code == 500 and "nothing was saved" in r.text and count(db, "it_tickets") == tickets
    assert agent.post("/it-tickets/new", data=form).status_code == 303
    assert effects(admin) == [("server_error", "ui", "POST", "/it-tickets/new", 1)]


def failing_attempts(admin, agent, seed, n=12):
    set_chaos(admin, "flaky_500", seed)
    return [i for i in range(1, n + 1) if mail(agent, i).status_code == 500]


def test_flaky_500_same_seed_same_failing_requests_and_reset_clears(admin, db_file):
    seed = seed_where(lambda s: sum(flaky(s, i) for i in range(1, 13)) >= 2)
    runs = []
    for _ in range(2):
        data(admin.post("/__admin/reset"))
        assert events(admin)["items"] == [] and data(admin.get("/__admin/chaos"))["active"] is False
        runs.append((failing_attempts(admin, make_client(db_file, "ops-agent"), seed), events(admin)["items"]))
    assert runs[0] == runs[1]  # the same attempts fail and the event logs are identical
    assert runs[0][0] == [i for i in range(1, 13) if flaky(seed, i)]
    other = seed_where(lambda s: [i for i in range(1, 13) if flaky(s, i)] != runs[0][0])
    data(admin.post("/__admin/reset"))
    assert failing_attempts(admin, make_client(db_file, "ops-agent"), other) != runs[0][0]


def test_setting_the_profile_again_restarts_the_schedule(admin, agent):
    seed = seed_where(lambda s: flaky(s, 1) and not flaky(s, 2))
    set_chaos(admin, "flaky_500", seed)
    assert mail(agent, 1).status_code == 500
    set_chaos(admin, "flaky_500", seed)
    assert mail(agent, 2).status_code == 500  # attempt numbering starts again at 1 (N.108)


def test_the_flaky_schedule_is_a_pure_function_near_thirty_percent():
    hits = [flaky(7, n) for n in range(1, 2001)]
    assert hits == [flaky(7, n) for n in range(1, 2001)]
    assert 0.26 < sum(hits) / len(hits) < 0.34
    assert chaos.fires("flaky_500", 1, 1, 0.0) is False and chaos.fires("flaky_500", 1, 1, 1.0) is True


# --- commit_then_timeout (3.5, D-008, N.106) -------------------------------------------------------


def test_commit_then_timeout_commits_then_holds_the_response_once(db, admin, agent, world, monkeypatch):
    monkeypatch.setenv("ACME_CHAOS_TIMEOUT_DELAY_SECONDS", "0.4")
    set_chaos(admin, "commit_then_timeout")
    tickets = count(db, "it_tickets")
    start = time.monotonic()
    assert ticket(agent, world=world).status_code == 201
    assert time.monotonic() - start >= 0.4
    assert count(db, "it_tickets") == tickets + 1
    start = time.monotonic()
    assert ticket(agent, "accounts", world=world).status_code == 201
    assert time.monotonic() - start < 0.4  # fires once per activation
    assert effects(admin) == [("response_delayed", "api", "POST", "/api/it-tickets", 1)]


def test_the_row_is_readable_while_the_response_is_held(db_file, admin, world, monkeypatch):
    monkeypatch.setenv("ACME_CHAOS_TIMEOUT_DELAY_SECONDS", "1.5")
    set_chaos(admin, "commit_then_timeout")
    writer, reader = make_client(db_file, "ops-agent"), make_client(db_file, "ops-agent")
    before = len(reader.get("/api/it-tickets").json()["data"]["items"])
    result = {}
    thread = threading.Thread(target=lambda: result.update(r=ticket(writer, world=world)))
    thread.start()
    deadline = time.monotonic() + 1.2
    while time.monotonic() < deadline and len(reader.get("/api/it-tickets").json()["data"]["items"]) == before:
        time.sleep(0.05)
    assert thread.is_alive(), "the response should still be held"
    assert len(reader.get("/api/it-tickets").json()["data"]["items"]) == before + 1
    thread.join()
    assert result["r"].status_code == 201


def test_commit_then_timeout_on_a_ui_approval_request(db, admin, agent, world, monkeypatch):
    monkeypatch.setenv("ACME_CHAOS_TIMEOUT_DELAY_SECONDS", "0.3")
    set_chaos(admin, "commit_then_timeout")
    approvals = count(db, "approvals")
    start = time.monotonic()
    r = agent.post(f"/invoices/{world['over']['id']}/request-approval", data={"reason": "over limit"})
    assert r.status_code == 303 and time.monotonic() - start >= 0.3 and count(db, "approvals") == approvals + 1
    assert effects(admin) == [("response_delayed", "ui", "POST", f"/invoices/{world['over']['id']}/request-approval", 1)]


def test_commit_then_timeout_skips_other_writes_and_rejected_ones(db, admin, agent, world, monkeypatch):
    monkeypatch.setenv("ACME_CHAOS_TIMEOUT_DELAY_SECONDS", "0.3")
    set_chaos(admin, "commit_then_timeout")
    start = time.monotonic()
    assert post_invoice(agent).status_code == 201  # invoices are not eligible (D-008)
    assert agent.post(f"/api/employees/{world['employee']['id']}/cancel").status_code == 200
    assert ticket(agent, world=world).status_code == 409  # rejected: nothing committed, fault not spent
    assert time.monotonic() - start < 0.3 and events(admin)["fired"] is False
    other = agent.post("/api/employees", json={"name": "New Person", "email": "new.person@acme.example",
                                               "role": "Analyst", "department": "Finance", "manager_id": 1,
                                               "start_date": "2026-10-12"}).json()["data"]
    assert ticket(agent, employee_id=other["id"]).status_code == 201
    assert events(admin)["fired"] is True and effects(admin)[0][0] == "response_delayed"


def leaves(routes):
    """Every route, including those inside the `_IncludedRouter` wrappers that `app.routes` does not expand."""
    for r in routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            yield from leaves(inner.routes)
        elif isinstance(r, APIRoute):
            yield r


def test_the_timeout_endpoints_exist():
    routes = {f"{'api' if r.path.startswith('/api/') else 'ui'}:{m} {r.path}"
              for r in leaves(create_app().routes) for m in r.methods}
    assert chaos.TIMEOUT_ENDPOINTS <= routes


# --- silent_drop_write (4.4, N.105) ---------------------------------------------------------------


def test_silent_drop_rolls_back_everything_and_still_says_saved(db, admin, agent):
    set_chaos(admin, "silent_drop_write")
    before = {t: count(db, t) for t in ("invoices", "audit_log", "idempotency_keys")}
    r = ui_invoice_form(agent)
    assert r.status_code == 303 and r.headers["location"] == "/invoices"
    toast = agent.get(r.headers["location"]).text
    assert "INV-3001 saved with status" in toast
    assert {t: count(db, t) for t in before} == before
    assert effects(admin) == [("write_dropped", "ui", "POST", "/invoices/new", 1)]
    assert post_invoice(agent).status_code == 201  # the next write (any channel) commits: the flag did not leak
    assert ui_invoice_form(agent, invoice_no="INV-3002").headers["location"].startswith("/invoices/")
    assert count(db, "invoices") == before["invoices"] + 2 and len(effects(admin)) == 1


def test_silent_drop_never_touches_the_api(db, admin, agent):
    set_chaos(admin, "silent_drop_write")
    assert post_invoice(agent).status_code == 201 and events(admin)["fired"] is False


def test_silent_drop_reproduces_and_reset_clears(admin, db_file):
    logs = []
    for _ in range(2):
        data(admin.post("/__admin/reset"))
        set_chaos(admin, "silent_drop_write", seed=3)
        agent = make_client(db_file, "ops-agent")
        agent.post("/it-tickets/new", data={"type": "laptop", "employee_id": "1"})
        logs.append(events(admin)["items"])
    assert logs[0] == logs[1] and [e["effect"] for e in logs[0]] == ["write_dropped"]
    data(admin.post("/__admin/reset"))
    assert events(admin)["items"] == []


# --- session_expiry_at_step_N (3.4, D-044, N.108) --------------------------------------------------


def test_session_expiry_lets_n_requests_through_then_401(admin, db_file):
    set_chaos(admin, "session_expiry_at_step_3")
    agent = make_client(db_file, "ops-agent")
    for _ in range(3):
        assert agent.get("/api/whoami").status_code == 200
    assert_typed_error(agent.get("/api/whoami"), 401, "session_expired")
    assert_typed_error(agent.get("/api/whoami"), 401, "session_expired")  # revoked for good
    assert effects(admin) == [("session_expired", "api", "GET", "/api/whoami", 4)]
    again = make_client(db_file, "ops-agent")
    for _ in range(10):  # once per activation
        assert again.get("/api/whoami").status_code == 200


def test_session_expiry_on_the_ui_redirects_to_login(admin, db_file):
    set_chaos(admin, "session_expiry_at_step_2")
    agent = make_client(db_file, "ops-agent")
    assert agent.get("/invoices").status_code == agent.get("/payments").status_code == 200
    r = agent.get("/approvals")
    assert r.status_code == 303 and r.headers["location"].startswith("/login?next=")
    assert effects(admin) == [("session_expired", "ui", "GET", "/approvals", 3)]


def test_session_expiry_counts_per_session_not_globally(admin, db_file):
    set_chaos(admin, "session_expiry_at_step_2")
    first, second = make_client(db_file, "ops-agent"), make_client(db_file, "ops-agent")
    for _ in range(2):
        assert first.get("/api/whoami").status_code == second.get("/api/whoami").status_code == 200
    assert first.get("/api/whoami").status_code == 401
    assert second.get("/api/whoami").status_code == 200  # already fired once this activation


def test_session_expiry_reproduces_and_reset_clears(admin, db_file):
    logs = []
    for _ in range(2):
        data(admin.post("/__admin/reset"))
        set_chaos(admin, "session_expiry_at_step_1", seed=9)
        agent = make_client(db_file, "ops-agent")
        assert [agent.get("/api/whoami").status_code for _ in range(3)] == [200, 401, 401]
        logs.append(events(admin)["items"])
    assert logs[0] == logs[1]
    data(admin.post("/__admin/reset"))
    agent = make_client(db_file, "ops-agent")
    assert [agent.get("/api/whoami").status_code for _ in range(3)] == [200, 200, 200]


# --- scope: ops-agent only, admin exempt, chaos off changes nothing (N.104) -----------------------


@pytest.mark.parametrize("profile", ["flaky_500", "session_expiry_at_step_1", "commit_then_timeout",
                                     "silent_drop_write"])
def test_meera_is_never_faulted(db, admin, db_file, world, profile, monkeypatch):
    monkeypatch.setenv("ACME_CHAOS_TIMEOUT_DELAY_SECONDS", "5")
    set_chaos(admin, profile, seed_where(lambda s: all(flaky(s, n) for n in (1, 2, 3))))
    meera = make_client(db_file, "meera")
    for _ in range(3):
        assert meera.get("/api/whoami").status_code == 200
    start = time.monotonic()
    r = meera.post(f"/approvals/{world['approval']['id']}/decide", data={"decision": "approve", "reason": "ok"})
    assert r.status_code == 303 and time.monotonic() - start < 1
    assert db.execute("SELECT status FROM approvals WHERE id = ?", (world["approval"]["id"],)).fetchone()[0] == "approved"
    assert events(admin)["items"] == [] and count(db, "chaos_attempts") == 0


def test_admin_calls_are_exempt_from_counters_and_faults(db, admin, db_file):
    set_chaos(admin, "session_expiry_at_step_2")
    agent = make_client(db_file, "ops-agent")
    for _ in range(20):
        admin.get("/__admin/state_hash"), admin.get("/__admin/chaos/events"), admin.post("/__admin/snapshot")
    assert [agent.get("/api/whoami").status_code for _ in range(3)] == [200, 200, 401]
    set_chaos(admin, "flaky_500", seed_where(lambda s: flaky(s, 1)))
    for _ in range(5):
        assert admin.post("/__admin/snapshot").status_code == 201
    assert count(db, "chaos_attempts") == 0


def scripted_run(agent):
    """A mixed run on both channels, built on the seed only; returns what the client saw."""
    out = [Page(agent.get("/invoices/new").text).buttons, ui_invoice_form(agent).status_code]
    big = post_invoice(agent, {**INVOICE, "invoice_no": "INV-BIG", "amount_paise": 9_000_000, "tax_paise": 0})
    out += [big.status_code, ticket(agent, employee_id=1).status_code,
            agent.post(f"/invoices/{big.json()['data']['id']}/request-approval", data={"reason": "x"}).status_code]
    return out + [agent.get("/api/whoami").status_code for _ in range(3)]


def test_chaos_off_changes_nothing(admin, db_file, monkeypatch):
    """The same run with no profile ever set, and after every profile was set then cleared: same responses,
    same state hash, no events, no delay."""
    monkeypatch.setenv("ACME_CHAOS_TIMEOUT_DELAY_SECONDS", "5")
    start = time.monotonic()
    plain = scripted_run(make_client(db_file, "ops-agent"))
    plain_hash = data(admin.get("/__admin/state_hash"))["state_hash"]
    data(admin.post("/__admin/reset"))
    for profile in [*chaos.PROFILES, "session_expiry_at_step_1"]:
        set_chaos(admin, profile, seed_where(lambda s: flaky(s, 1)))
        set_chaos(admin, "none")
    assert scripted_run(make_client(db_file, "ops-agent")) == plain
    assert data(admin.get("/__admin/state_hash"))["state_hash"] == plain_hash
    assert events(admin)["items"] == [] and time.monotonic() - start < 5
    assert "Save invoice" in plain[0] and plain[1:5] == [303, 201, 201, 303]


# --- events endpoint, planned profiles, inventory (N.98, D-095) -----------------------------------


def test_events_say_whether_the_active_profile_fired(admin, agent):
    assert events(admin) | {"items": None} == {**data(admin.get("/__admin/chaos")), "fired": False,
                                               "fired_count": 0, "first_fired_at": None, "items": None}
    set_chaos(admin, "silent_drop_write")
    assert events(admin)["fired"] is False
    ui_invoice_form(agent)
    out = events(admin)
    assert out["fired"] is True and out["fired_count"] == 1 and out["first_fired_at"]
    set_chaos(admin, "rename_submit_button")  # a new activation: not fired yet, old event kept until reset
    out = events(admin)
    assert out["fired"] is False and [e["effect"] for e in out["items"]] == ["write_dropped"]


@pytest.mark.parametrize("profile", chaos.PLANNED)
def test_day_3_profiles_are_refused_with_a_typed_422(admin, profile):
    r = admin.post("/__admin/chaos", params={"profile": profile})
    assert_typed_error(r, 422, "invalid_input")
    assert "Day 3" in r.json()["detail"]


def test_every_ui_post_route_passes_the_chaos_route_class():
    posts = [r for r in leaves(create_app().routes) if "POST" in r.methods
             and not r.path.startswith(("/api/", "/__admin"))]
    assert len(posts) >= 15
    for route in posts:
        assert isinstance(route, chaos.ChaosRoute), route.path


EFFECT_TESTS = {
    "rename_submit_button": test_rename_changes_the_button_name_and_not_the_behaviour,
    "flaky_500": test_flaky_500_fails_before_anything_is_written_and_the_retry_passes,
    "commit_then_timeout": test_commit_then_timeout_commits_then_holds_the_response_once,
    "silent_drop_write": test_silent_drop_rolls_back_everything_and_still_says_saved,
    "session_expiry_at_step_N": test_session_expiry_lets_n_requests_through_then_401,
}


def test_every_implemented_profile_has_an_effect_test():
    """N.98: a profile Acme accepts must have a test proving it does something."""
    assert set(EFFECT_TESTS) == set(chaos.WIRED_PROFILES) | {"session_expiry_at_step_N"}
    assert set(chaos.WIRED_PROFILES) == set(chaos.PROFILES)
    assert all(callable(t) and t.__name__.startswith("test_") for t in EFFECT_TESTS.values())
