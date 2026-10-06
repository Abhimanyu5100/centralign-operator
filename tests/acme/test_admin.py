"""Admin endpoints (part 8): token rule, reset, snapshot, state hash, diff, chaos. Risks N.90 to N.100, 0.3, 0.4, 6.4, 7.6."""

import json

import pytest
from fastapi.testclient import TestClient

from acme import services as s
from acme.app import create_app
from acme.db import connect
from acme.seed import reset, state_hash
from acme.web import is_admin_path
from tests.acme.conftest import PASSWORDS, make_client
from tests.acme.test_api import INVOICE, assert_typed_error, count, post_invoice

TOKEN = "harness-token-for-tests"
H = {"X-Admin-Token": TOKEN}
ADMIN_ROUTES = {("POST", "/__admin/reset"), ("GET", "/__admin/state_hash"), ("POST", "/__admin/snapshot"),
                ("GET", "/__admin/diff"), ("GET", "/__admin/chaos"), ("POST", "/__admin/chaos"),
                ("GET", "/__admin/chaos/events")}


@pytest.fixture(autouse=True)
def admin_token(monkeypatch):
    monkeypatch.setenv("ACME_ADMIN_TOKEN", TOKEN)


@pytest.fixture
def admin(db_file):
    """A client with no session at all, only the token header."""
    return TestClient(create_app(db_file), follow_redirects=False, headers=H)


def data(r, status=200):
    assert r.status_code == status, r.text
    body = r.json()
    assert body["ok"] is True and body["error_type"] is None
    return body["data"]


def snap(admin) -> str:
    return data(admin.post("/__admin/snapshot"), 201)["snapshot"]


def diff(admin, since):
    return data(admin.get("/__admin/diff", params={"since": since}))


# --- the token rule (N.90, N.91) -----------------------------------------------------------------


def admin_requests(client, **kw):
    for method, path in sorted(ADMIN_ROUTES):
        yield method, path, client.request(method, path, params={"since": "x", "profile": "none"}, **kw)


def test_the_openapi_walk_finds_exactly_the_admin_routes(app_for_walk):
    found = {(m.upper(), p) for p, ms in app_for_walk.openapi()["paths"].items() if is_admin_path(p) for m in ms}
    assert found == ADMIN_ROUTES


@pytest.fixture
def app_for_walk(db_file):
    return create_app(db_file)


@pytest.mark.parametrize("headers", [{}, {"X-Admin-Token": ""}, {"X-Admin-Token": "wrong"},
                                     {"X-Admin-Token": TOKEN + "x"}, {"X-Admin-Token": TOKEN[:-1]},
                                     {"X-Admin-Token": TOKEN.upper()}, {"Authorization": f"Bearer {TOKEN}"}])
def test_every_admin_route_refuses_a_missing_or_wrong_token(db_file, headers):
    client = TestClient(create_app(db_file), follow_redirects=False)
    for method, path, r in admin_requests(client, headers=headers):
        assert_typed_error(r, 403, "forbidden")


def test_a_non_ascii_token_is_a_403_not_a_500(db_file):
    client = TestClient(create_app(db_file), follow_redirects=False)
    for method, path, r in admin_requests(client, headers={"X-Admin-Token": "tökén".encode("utf-8")}):
        assert_typed_error(r, 403, "forbidden")


def test_the_token_in_the_query_string_is_ignored(db_file):
    client = TestClient(create_app(db_file), follow_redirects=False)
    assert_typed_error(client.get("/__admin/state_hash", params={"token": TOKEN, "X-Admin-Token": TOKEN}), 403, "forbidden")


@pytest.mark.parametrize("env", [None, ""])
def test_an_unset_or_empty_token_variable_closes_every_admin_route(db_file, monkeypatch, env):
    if env is None:
        monkeypatch.delenv("ACME_ADMIN_TOKEN")
    else:
        monkeypatch.setenv("ACME_ADMIN_TOKEN", env)
    client = TestClient(create_app(db_file), follow_redirects=False)
    for headers in ({}, {"X-Admin-Token": ""}, {"X-Admin-Token": "anything"}):
        for method, path, r in admin_requests(client, headers=headers):
            assert_typed_error(r, 403, "forbidden")


@pytest.mark.parametrize("user", ["ops-agent", "meera"])
def test_a_valid_session_without_the_token_is_still_403(db_file, user):
    client = make_client(db_file, user)
    for method, path, r in admin_requests(client):
        assert_typed_error(r, 403, "forbidden")


@pytest.mark.parametrize("user", ["ops-agent", "meera"])
def test_a_session_does_not_replace_the_token_but_the_token_needs_no_session(db_file, user):
    assert make_client(db_file, user).get("/__admin/state_hash", headers=H).status_code == 200
    assert TestClient(create_app(db_file)).get("/__admin/state_hash", headers=H).status_code == 200


def test_a_route_added_later_under_the_admin_prefix_is_token_protected_without_asking(db_file):
    app = create_app(db_file)

    @app.get("/__admin/added_later")
    def added_later():
        return {"ok": True}

    client = TestClient(app, follow_redirects=False)
    assert_typed_error(client.get("/__admin/added_later"), 403, "forbidden")
    assert client.get("/__admin/added_later", headers=H).status_code == 200


def test_the_prefix_rule_is_exact():
    assert is_admin_path("/__admin") and is_admin_path("/__admin/reset") and is_admin_path("/__admin/")
    assert not is_admin_path("/__administrator") and not is_admin_path("/x/__admin/reset")
    assert not is_admin_path("/api/__admin")


def test_non_admin_routes_still_need_a_session_not_the_token(db_file):
    client = TestClient(create_app(db_file), follow_redirects=False, headers=H)
    assert client.get("/api/whoami").status_code == 401
    assert client.get("/invoices").status_code == 303


def test_unknown_and_wrong_method_admin_requests_are_typed_json(admin):
    assert_typed_error(admin.get("/__admin/nope"), 404, "not_found")
    assert_typed_error(admin.get("/__admin/reset"), 405, "invalid_request")


# --- reset (0.3, N.95, N.96) ---------------------------------------------------------------------


def test_reset_returns_the_same_hash_as_the_seed_module_and_is_repeatable(admin, tmp_path):
    first = data(admin.post("/__admin/reset", params={"seed": "t9", "now": "2026-10-08T09:00:00+05:30"}))
    again = data(admin.post("/__admin/reset", params={"seed": "t9", "now": "2026-10-08T09:00:00+05:30"}))
    other = connect(tmp_path / "other.db")
    assert first["state_hash"] == again["state_hash"] == reset(other, "t9", "2026-10-08T09:00:00+05:30")
    assert data(admin.get("/__admin/state_hash")) == {"state_hash": first["state_hash"], "now": "2026-10-08T09:00:00+05:30"}


def test_reset_defaults_to_the_base_seed_and_the_default_now(admin, db):
    out = data(admin.post("/__admin/reset"))
    assert (out["seed"], out["now"]) == ("base", "2026-10-07T10:30:00+05:30")


def test_reset_drops_sessions_snapshots_and_chaos(db_file, admin):
    agent = make_client(db_file, "ops-agent")
    old = snap(admin)
    data(admin.post("/__admin/chaos", params={"profile": "flaky_500", "seed": 3}))
    data(admin.post("/__admin/reset"))
    assert_typed_error(agent.get("/api/whoami"), 401, "session_expired")
    assert_typed_error(admin.get("/__admin/diff", params={"since": old}), 404, "not_found")
    assert data(admin.get("/__admin/chaos"))["profile"] == "none"


@pytest.mark.parametrize("params, field", [
    ({"seed": "nope"}, "seed"),
    ({"now": "2026-10-07T10:30:00"}, "now"),             # no offset
    ({"now": "2026-10-07T10:30:00+00:00"}, "now"),       # UTC
    ({"now": "yesterday"}, "now"),
])
def test_reset_with_bad_parameters_is_a_typed_422_and_changes_nothing(admin, db, params, field):
    before = state_hash(db)
    body = assert_typed_error(admin.post("/__admin/reset", params=params), 422, "invalid_input")
    assert body["data"] == {"field": field}
    assert state_hash(db) == before


def test_a_plus_in_a_url_arrives_as_a_space_and_the_error_says_how_to_fix_it(admin, db):
    r = admin.post("/__admin/reset?seed=base&now=2026-10-07T10:30:00+05:30")
    assert "%2B" in assert_typed_error(r, 422, "invalid_input")["detail"]
    assert data(admin.post("/__admin/reset?seed=base&now=2026-10-07T10:30:00%2B05:30"))["now"] == "2026-10-07T10:30:00+05:30"


def test_a_reader_during_a_reset_sees_the_old_state_or_the_new_one_never_a_mix(db_file, admin):
    admin.post("/__admin/reset", params={"seed": "base"})
    reader = connect(db_file)
    old_hash = state_hash(reader)
    reader.execute("BEGIN")
    reader.execute("SELECT COUNT(*) FROM vendors").fetchone()          # the read transaction starts here
    new_hash = data(admin.post("/__admin/reset", params={"seed": "t9"}))["state_hash"]
    assert new_hash != old_hash
    assert state_hash(reader) == old_hash                              # every table still from before
    reader.execute("COMMIT")
    assert state_hash(reader) == new_hash                              # and now every table from after
    reader.close()


# --- state hash ----------------------------------------------------------------------------------


def test_state_hash_ignores_logins_snapshots_and_chaos_but_sees_a_write(db_file, admin, db):
    before = data(admin.get("/__admin/state_hash"))["state_hash"]
    make_client(db_file, "meera")
    snap(admin)
    data(admin.post("/__admin/chaos", params={"profile": "rename_submit_button"}))
    assert data(admin.get("/__admin/state_hash"))["state_hash"] == before == state_hash(db)
    post_invoice(make_client(db_file, "ops-agent"))
    assert data(admin.get("/__admin/state_hash"))["state_hash"] != before


# --- snapshot and diff (6.4, N.93, N.94) ---------------------------------------------------------


def test_a_diff_of_an_unchanged_state_is_empty(admin):
    since = snap(admin)
    out = diff(admin, since)
    assert out["unchanged"] is True and out["tables"] == {} and out["state_hash"] == out["snapshot_state_hash"]


def test_the_diff_shows_added_changed_rows_per_table_in_id_order(db_file, admin):
    agent, meera = make_client(db_file, "ops-agent"), make_client(db_file, "meera")
    since = snap(admin)
    over = post_invoice(agent, {**INVOICE, "invoice_no": "INV-OVER", "amount_paise": 6_240_000}, key="a")
    assert over.status_code == 201
    post_invoice(agent, {**INVOICE, "invoice_no": "INV-SMALL"}, key="b")
    invoice_id = over.json()["data"]["id"]
    approval = agent.post("/api/approvals", json={"entity_type": "invoice", "entity_id": invoice_id})
    assert approval.status_code == 201, approval.text
    assert meera.post(f"/api/approvals/{approval.json()['data']['id']}/decide", json={"decision": "approve"}).status_code == 200

    out = diff(admin, since)
    assert out["unchanged"] is False
    assert [r["invoice_no"] for r in out["tables"]["invoices"]["added"]] == ["INV-OVER", "INV-SMALL"]
    assert out["tables"]["invoices"]["added"][0]["status"] == "approved"   # added rows show the final state
    assert set(out["tables"]) == {"invoices", "approvals", "audit_log"}
    ids = [r["id"] for r in out["tables"]["audit_log"]["added"]]
    assert ids == sorted(ids) and len(ids) >= 5


def test_a_change_to_an_existing_row_carries_before_and_after(db_file, db, admin):
    agent, meera = make_client(db_file, "ops-agent"), make_client(db_file, "meera")
    over = post_invoice(agent, {**INVOICE, "invoice_no": "INV-OVER", "amount_paise": 6_240_000}, key="a").json()["data"]
    approval = agent.post("/api/approvals", json={"entity_type": "invoice", "entity_id": over["id"]}).json()["data"]
    since = snap(admin)
    assert meera.post(f"/api/approvals/{approval['id']}/decide", json={"decision": "approve"}).status_code == 200
    changed = diff(admin, since)["tables"]
    (inv,) = changed["invoices"]["changed"]
    assert (inv["id"], inv["before"]["status"], inv["after"]["status"]) == (over["id"], "pending_approval", "approved")
    assert inv["after"]["version"] == inv["before"]["version"] + 1
    assert changed["invoices"]["added"] == [] and changed["invoices"]["removed"] == []
    assert changed["approvals"]["changed"][0]["after"]["status"] == "approved"


def test_the_diff_is_byte_identical_when_asked_twice(db_file, admin):
    since = snap(admin)
    post_invoice(make_client(db_file, "ops-agent"))
    assert admin.get("/__admin/diff", params={"since": since}).content == admin.get("/__admin/diff", params={"since": since}).content


def test_logins_and_a_replayed_idempotency_key_add_nothing_to_the_diff(db_file, admin):
    agent = make_client(db_file, "ops-agent")
    assert post_invoice(agent, key="same").status_code == 201
    since = snap(admin)
    make_client(db_file, "meera")
    assert agent.get("/api/whoami").status_code == 200
    replay = post_invoice(agent, key="same")
    assert replay.status_code == 201 and replay.headers["Idempotent-Replayed"] == "true"
    out = diff(admin, since)
    assert out["unchanged"] is True and out["tables"] == {}


def test_the_diff_audit_rows_are_the_audit_api_rows(db_file, admin):
    agent = make_client(db_file, "ops-agent")
    last = agent.get("/api/audit").json()["data"]["next_since"]
    since = snap(admin)
    post_invoice(agent, {**INVOICE, "invoice_no": "INV-A"}, key="a")
    via_diff = diff(admin, since)["tables"]["audit_log"]["added"]
    via_api = agent.get("/api/audit", params={"since": last}).json()["data"]["items"]
    assert [r["id"] for r in via_diff] == [r["id"] for r in via_api]


def test_an_unknown_missing_or_stale_snapshot_id_is_refused(admin):
    old = snap(admin)
    assert_typed_error(admin.get("/__admin/diff", params={"since": "deadbeef"}), 404, "not_found")
    assert_typed_error(admin.get("/__admin/diff"), 422, "invalid_request")
    data(admin.post("/__admin/reset"))
    assert_typed_error(admin.get("/__admin/diff", params={"since": old}), 404, "not_found")
    fresh = snap(admin)
    assert fresh != old and diff(admin, fresh)["unchanged"] is True


def test_snapshot_ids_are_random_not_counters(admin):
    ids = {snap(admin) for _ in range(5)}
    assert len(ids) == 5 and all(len(i) == 16 and int(i, 16) >= 0 for i in ids)


# --- bank details stay masked (7.6, N.100) -------------------------------------------------------

LONG, SHORT = "98765432101234", "1234"


@pytest.mark.parametrize("number, masked", [
    (LONG, "XXXXXXXXXX1234"), ("123456789", "XXXXX6789"), ("12345678", "XXXXXXXX"), (SHORT, "XXXX"), ("123", "XXXX"),
])
def test_the_mask_shows_the_last_four_digits_only_for_numbers_longer_than_eight(number, masked):
    assert s._mask_account(number) == masked


@pytest.mark.parametrize("number", [LONG, SHORT, "12345678"])
def test_update_vendor_bank_audits_a_masked_value_and_no_endpoint_returns_the_number(db_file, db, admin, number):
    agent = make_client(db_file, "ops-agent")
    last = agent.get("/api/audit").json()["data"]["next_since"]
    since = snap(admin)
    row = s.update_vendor_bank(db, "admin", 4, number)
    assert number not in json.dumps(row)

    (audit_row,) = db.execute("SELECT * FROM audit_log WHERE action = 'vendor.update_bank'").fetchall()
    assert number not in " ".join(str(v) for v in dict(audit_row).values())
    assert json.loads(audit_row["after_json"])["bank_account_masked"] == s._mask_account(number)
    assert json.loads(audit_row["before_json"])["bank_account_masked"] == "XXXXXXXX6602"

    api_text = agent.get("/api/audit", params={"since": last}).text
    diff_text = admin.get("/__admin/diff", params={"since": since}).text
    vendor_text = agent.get("/api/vendors/4").text + agent.get("/vendors/4").text
    for text in (api_text, diff_text, vendor_text):
        assert number not in text
    assert s._mask_account(number) in diff_text


# --- chaos (0.4, N.97, N.98) ---------------------------------------------------------------------


def test_chaos_is_none_until_set(admin):
    assert data(admin.get("/__admin/chaos")) == {"profile": "none", "seed": 0, "active": False, "params": {}, "wired": False}


@pytest.mark.parametrize("profile, params", [
    ("rename_submit_button", {}), ("flaky_500", {}), ("commit_then_timeout", {}), ("silent_drop_write", {}),
    ("session_expiry_at_step_1", {"step": 1}), ("session_expiry_at_step_12", {"step": 12}),
    ("session_expiry_at_step_999", {"step": 999}),
])
def test_chaos_set_and_get_round_trip(admin, profile, params):
    out = data(admin.post("/__admin/chaos", params={"profile": profile, "seed": 7}), 200)
    assert out == {"profile": profile, "seed": 7, "active": True, "params": params, "wired": True}
    assert data(admin.get("/__admin/chaos")) == out


def test_setting_a_new_profile_replaces_the_old_one_and_none_clears_it(admin):
    admin.post("/__admin/chaos", params={"profile": "flaky_500"})
    admin.post("/__admin/chaos", params={"profile": "silent_drop_write", "seed": 2})
    assert data(admin.get("/__admin/chaos"))["profile"] == "silent_drop_write"
    admin.post("/__admin/chaos", params={"profile": "none"})
    assert data(admin.get("/__admin/chaos"))["active"] is False


@pytest.mark.parametrize("profile", ["", "nope", "Flaky_500", "flaky_500 ", "session_expiry_at_step_0",
                                     "session_expiry_at_step_1000", "session_expiry_at_step_01",
                                     "session_expiry_at_step_x", "session_expiry_at_step_-1", "session_expiry_at_step_"])
def test_an_unknown_profile_or_a_bad_step_is_a_422_and_keeps_the_current_profile(admin, profile):
    admin.post("/__admin/chaos", params={"profile": "flaky_500"})
    assert_typed_error(admin.post("/__admin/chaos", params={"profile": profile}), 422, "invalid_input")
    assert data(admin.get("/__admin/chaos"))["profile"] == "flaky_500"


@pytest.mark.parametrize("seed", ["-1", "x", "1.5", str(2**31)])
def test_a_bad_chaos_seed_is_a_422(admin, seed):
    assert_typed_error(admin.post("/__admin/chaos", params={"profile": "flaky_500", "seed": seed}), 422, "invalid_request")


def test_a_chaos_profile_is_not_part_of_the_hash_or_the_diff(admin):
    before, since = data(admin.get("/__admin/state_hash"))["state_hash"], snap(admin)
    admin.post("/__admin/chaos", params={"profile": "flaky_500"})
    assert data(admin.get("/__admin/state_hash"))["state_hash"] == before
    assert diff(admin, since)["unchanged"] is True
