"""Login, roles and sessions (D-037, D-043; risks N.32 to N.37, P.9, 3.4)."""

import re

import pytest
from fastapi import Depends
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from acme import auth, services as s
from acme.app import PUBLIC_PATHS, create_app, require_login
from acme.db import connect
from acme.models import ApprovalIn, DecisionIn
from acme.seed import reset, state_hash
from acme.web import is_admin_path
from tests.acme.test_services import invoice_in


class FakeTime:
    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return FakeTime()


@pytest.fixture
def db_file(tmp_path):
    path = tmp_path / "acme.db"
    conn = connect(path)
    reset(conn, "base")
    conn.close()
    return path


@pytest.fixture
def app(db_file, clock):
    return create_app(db_file, clock)


@pytest.fixture
def client(app):
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def db(db_file):
    conn = connect(db_file)
    yield conn
    conn.close()


def login(client, user="ops-agent", password=None):
    password = password or auth.DEV_PASSWORDS[user]
    return client.post("/api/login", json={"username": user, "password": password})


# --- login (D-037) ----------------------------------------------------------------------------------


def test_json_login_sets_an_httponly_lax_cookie_and_returns_actor_and_role(client):
    r = login(client)
    assert r.status_code == 200
    assert r.json()["data"] == {"actor": "ops-agent", "role": "ops_agent", "expires_in": 8 * 3600}
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    assert "secure" not in cookie  # accepted: plain http on localhost (register row 0.11)


@pytest.mark.parametrize("user,role", [("ops-agent", "ops_agent"), ("meera", "finance_manager"), ("admin", "admin")])
def test_each_login_user_gets_its_role(client, user, role):
    login(client, user)
    assert client.get("/api/whoami").json()["data"] == {"actor": user, "role": role}


def test_default_ttl_is_eight_hours():
    assert auth.session_ttl_seconds() == 8 * 3600


def test_failed_logins_look_identical_and_set_no_cookie(client):
    wrong_password = login(client, "ops-agent", "nope")
    unknown_user = login(client, "mallory", "nope")
    system_user = login(client, "system", "anything")  # an Acme-internal actor cannot log in
    for r in (wrong_password, unknown_user, system_user):
        assert r.status_code == 401
        assert "set-cookie" not in r.headers
    assert wrong_password.json() == unknown_user.json() == system_user.json()
    assert wrong_password.json()["error_type"] == "invalid_credentials"


def test_password_from_environment_replaces_the_dev_default(client, monkeypatch):
    monkeypatch.setenv("ACME_PASSWORD_MEERA", "s3cret-from-env")
    assert login(client, "meera").status_code == 401  # dev default no longer works
    assert login(client, "meera", "s3cret-from-env").status_code == 200


@pytest.mark.parametrize("body", [{"username": 1, "password": "x"}, {"username": "meera"}, ["meera"]])
def test_malformed_login_bodies_are_400_not_500(client, body):
    assert client.post("/api/login", json=body).status_code == 400


def test_non_json_login_body_is_400(client):
    r = client.post("/api/login", content=b"not json", headers={"content-type": "application/json"})
    assert r.status_code == 400


def test_form_login_redirects_with_the_same_cookie_attributes_as_json_login(client):
    json_cookie = login(client).headers["set-cookie"]
    r = client.post("/api/login", data={"username": "ops-agent", "password": auth.DEV_PASSWORDS["ops-agent"],
                                        "next": "/"})
    assert r.status_code == 303 and r.headers["location"] == "/"

    def attributes(header):  # everything after the value, minus the expiry date
        return sorted(p.strip().lower() for p in header.split(";")[1:] if "expires" not in p.lower())

    assert attributes(r.headers["set-cookie"]) == attributes(json_cookie)


def test_form_login_failure_rerenders_the_page_with_an_alert(client):
    r = client.post("/api/login", data={"username": "ops-agent", "password": "bad", "next": "/"})
    assert r.status_code == 401 and 'role="alert"' in r.text and "set-cookie" not in r.headers


def test_login_page_is_public_and_labelled(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert 'for="username"' in r.text and 'for="password"' in r.text and "Sign in" in r.text


@pytest.mark.parametrize("bad_next", ["//evil.test", "https://evil.test/x", "/\\evil.test", "evil", ""])
def test_next_must_be_a_same_site_path(client, bad_next):
    r = client.post("/api/login", data={"username": "ops-agent", "password": auth.DEV_PASSWORDS["ops-agent"],
                                        "next": bad_next})
    assert r.headers["location"] == "/"


def test_next_keeps_a_valid_path(client):
    r = client.post("/api/login", data={"username": "meera", "password": auth.DEV_PASSWORDS["meera"],
                                        "next": "/invoices?status=pending"})
    assert r.headers["location"] == "/invoices?status=pending"


# --- unauthenticated and expired (3.4, N.36) ---------------------------------------------------------


def test_api_without_cookie_is_401_login_required(client):
    r = client.get("/api/whoami")
    assert r.status_code == 401 and r.json()["error_type"] == "login_required"
    assert r.headers["content-type"].startswith("application/json")


def test_ui_without_cookie_redirects_to_login_with_next(client):
    r = client.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/login?next=%2F"


def test_garbage_cookie_is_session_expired(client):
    client.cookies.set(auth.COOKIE_NAME, "garbage")
    assert client.get("/api/whoami").json()["error_type"] == "session_expired"


def test_every_non_public_route_requires_login(app, client):
    """Walks every route from the OpenAPI schema, which includes routes added through `include_router`
    (those sit inside an `_IncludedRouter` that `app.routes` does not expand). Path parameters get a sample value."""
    probed = []
    for template, methods in app.openapi()["paths"].items():
        if template in PUBLIC_PATHS or is_admin_path(template):  # admin routes: token rule, tests/acme/test_admin.py
            continue
        path = re.sub(r"\{[^}]+\}", "1", template)
        for method in methods:
            r = client.request(method.upper(), path)
            expected = 401 if path.startswith("/api/") else 303
            assert r.status_code == expected, f"{method.upper()} {template} served without a session"
            probed.append((method.upper(), template))
    # the walk really covered the app-level routes and the UI router's routes (read and write)
    for expected in [("GET", "/api/whoami"), ("GET", "/"), ("GET", "/invoices/{invoice_id}"),
                     ("POST", "/invoices/new"), ("POST", "/approvals/{approval_id}/decide")]:
        assert expected in probed, f"{expected} was not probed"


def test_the_openapi_walk_sees_every_registered_route(app):
    """Guards the walk itself: if a route is hidden from the schema the login test above would skip it."""
    def leaves(routes):
        for r in routes:
            inner = getattr(r, "original_router", None)
            if inner is not None:
                yield from leaves(inner.routes)
            elif hasattr(r, "path"):
                yield r
    registered = {(r.path, m) for r in leaves(app.routes) for m in getattr(r, "methods", set()) - {"HEAD"}
                  if getattr(r, "include_in_schema", True)}
    in_schema = {(p, m.upper()) for p, ms in app.openapi()["paths"].items() for m in ms}
    assert registered <= in_schema


def test_a_route_added_later_without_its_own_check_is_still_protected(app, client):
    app.add_api_route("/api/forgotten", lambda: {"secret": 1})  # no Depends(require_login) of its own
    app.add_api_route("/forgotten-page", lambda: {"secret": 1})
    assert client.get("/api/forgotten").status_code == 401
    assert client.get("/forgotten-page").status_code == 303
    login(client)
    assert client.get("/api/forgotten").status_code == 200


def test_public_paths_are_exactly_the_login_flow():
    assert PUBLIC_PATHS == {"/login", "/api/login", "/api/logout", "/healthz"}


def test_session_expires_on_the_wall_clock(client, clock):
    login(client)
    clock.now += auth.session_ttl_seconds() - 1
    assert client.get("/api/whoami").status_code == 200
    clock.now += 2
    r = client.get("/api/whoami")
    assert r.status_code == 401 and r.json()["error_type"] == "session_expired"


def test_ttl_is_configurable(client, clock, monkeypatch):
    monkeypatch.setenv("ACME_SESSION_TTL_SECONDS", "60")
    login(client)
    clock.now += 61
    assert client.get("/api/whoami").status_code == 401


def test_logout_revokes_the_session(client):
    login(client)
    token = client.cookies.get(auth.COOKIE_NAME)
    assert client.post("/api/logout").status_code == 200
    client.cookies.set(auth.COOKIE_NAME, token)  # replay the old cookie
    assert client.get("/api/whoami").json()["error_type"] == "session_expired"


def test_logout_without_a_session_is_fine(client):
    assert client.post("/api/logout").status_code == 200


def test_revoke_invalidates_a_session(client, db):
    login(client)
    auth.revoke(db, client.cookies.get(auth.COOKIE_NAME))
    assert client.get("/api/whoami").status_code == 401


def test_request_count_is_per_session(app, db):
    a, b = TestClient(app), TestClient(app)
    login(a)
    login(b, "meera")
    for _ in range(3):
        a.get("/api/whoami")
    b.get("/api/whoami")
    counts = {r["actor"]: r["request_count"] for r in db.execute("SELECT actor, request_count FROM sessions")}
    assert counts == {"ops-agent": 3, "meera": 1}


def test_a_request_is_counted_once_even_with_several_dependencies(client, db):
    login(client)
    client.get("/")  # the app-wide check and the route's own Depends(require_login)
    assert db.execute("SELECT request_count FROM sessions").fetchone()[0] == 1


# --- sessions stay out of Acme's state (N.32) --------------------------------------------------------


def test_login_whoami_and_logout_do_not_change_state_hash_or_audit(client, db):
    before = state_hash(db)
    audit_before = db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    login(client)
    client.get("/api/whoami")
    client.post("/api/logout")
    assert state_hash(db) == before
    assert db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == audit_before


def test_reset_wipes_sessions_so_old_cookies_stop_working(client, db):
    login(client)
    assert client.get("/api/whoami").status_code == 200
    reset(db, "base")
    r = client.get("/api/whoami")
    assert r.status_code == 401 and r.json()["error_type"] == "session_expired"
    assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_reset_gives_the_same_hash_with_a_session_in_between(client, db):
    first = state_hash(db)
    login(client)
    assert reset(db, "base") == first


# --- secrets (N.35) ----------------------------------------------------------------------------------


def test_only_the_token_hash_is_stored(client, db):
    r = login(client)
    token = client.cookies.get(auth.COOKIE_NAME)
    dump = " ".join(str(v) for row in db.execute("SELECT * FROM sessions") for v in tuple(row))
    assert token not in dump and auth._hash(token) in dump
    assert token not in r.text  # the cookie is the only place the token travels


def test_passwords_never_appear_in_responses(client):
    for r in (login(client), login(client, "ops-agent", "wrong-pw-123"), client.get("/api/whoami")):
        assert auth.DEV_PASSWORDS["ops-agent"] not in r.text and "wrong-pw-123" not in r.text


# --- identity comes from the session only (P.9, N.34, N.22) -------------------------------------------


@pytest.fixture
def approve_route(app, db):
    """Stand-in for the part-4 approval endpoint: the actor comes from the session, as in real routes."""
    invoice = s.submit_invoice(db, "ops-agent", "api",
                               invoice_in(invoice_no="INV-9001", amount_paise=6_240_000, tax_paise=951_864))
    approval = s.request_approval(db, "ops-agent", "api", ApprovalIn(entity_type="invoice", entity_id=invoice["id"]))

    @app.post("/test/approve")
    def approve(actor: str = Depends(require_login)):
        conn = connect(app.state.db_path)
        try:
            s.decide_approval(conn, actor, "api", approval["id"], DecisionIn(decision="approve"))
        except s.AcmeError as exc:
            return JSONResponse({"detail": exc.message}, exc.status_code)
        finally:
            conn.close()
        return {"actor": actor}

    return "/test/approve"


def test_spoofed_actor_in_body_query_or_header_is_ignored_and_acme_returns_403(client, approve_route):
    login(client, "ops-agent")
    r = client.post(approve_route + "?actor=meera&user=admin", json={"actor": "meera", "role": "admin"},
                    headers={"X-User": "admin", "X-Actor": "meera", "Authorization": "Bearer meera"})
    assert r.status_code == 403
    assert client.get("/api/whoami", headers={"X-User": "admin"}).json()["data"]["actor"] == "ops-agent"


def test_the_real_approver_succeeds_through_the_same_route(client, approve_route):
    login(client, "meera")
    r = client.post(approve_route)
    assert r.status_code == 200 and r.json() == {"actor": "meera"}
