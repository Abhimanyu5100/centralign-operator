"""The JSON API (part 4). Risks 3.4, 3.5, 7.3, N.21, N.22, N.25, N.34, N.45, N.50-N.55, register 0.10.

States are built through the service layer only (N.28); the API is exercised through the real app."""

import inspect
import re
import threading
from pathlib import Path

import pytest

from acme import api, idempotency, services as s
from acme.models import EmployeeIn, PaymentIn
from acme.seed import reset, state_hash
from acme.web import ERROR_TYPES, api_error
from tests.acme.conftest import make_client
from tests.acme.htmlutil import Page
from tests.acme.test_services import invoice_in

INVOICE = dict(vendor_id=2, invoice_no="INV-4001", po_number="PO-9", invoice_date="2026-10-01",
               due_date="2026-10-31", amount_paise=1_850_000, tax_paise=282_203)


def count(db, table):
    return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def post_invoice(client, body=None, key="key-1", **headers):
    hdrs = {"Idempotency-Key": key} if key is not None else {}
    return client.post("/api/invoices", json=body or INVOICE, headers={**hdrs, **headers})


def assert_typed_error(r, status, error_type):
    assert r.status_code == status, r.text
    body = r.json()
    assert set(body) == {"ok", "error_type", "detail", "data"}
    assert body["ok"] is False and body["error_type"] == error_type and body["detail"]
    return body


# --- reads ---------------------------------------------------------------------------------------


def test_reads_return_the_typed_shape(agent, world):
    for path in ("/api/vendors", "/api/vendors?q=sharma", "/api/vendors/1", "/api/invoices", "/api/invoices/1",
                 "/api/invoices?vendor=3&status=approved", "/api/approvals?status=pending",
                 f"/api/approvals/{world['approval']['id']}", "/api/payments", f"/api/payments/{world['payment']['id']}",
                 f"/api/payments?invoice={world['ok']['id']}", "/api/employees?q=priya",
                 f"/api/employees/{world['employee']['id']}", "/api/it-tickets",
                 f"/api/it-tickets?employee={world['employee']['id']}", f"/api/it-tickets/{world['ticket']['id']}",
                 "/api/audit"):
        r = agent.get(path)
        assert r.status_code == 200, path
        assert r.json()["ok"] is True and r.json()["error_type"] is None, path


def test_vendor_filter_takes_an_id_and_names_resolve_through_vendor_search(agent):
    vendor = agent.get("/api/vendors?q=Verma").json()["data"]["items"]
    assert [v["name"] for v in vendor] == ["Verma Traders"]
    items = agent.get(f"/api/invoices?vendor={vendor[0]['id']}").json()["data"]["items"]
    assert sorted(i["invoice_no"] for i in items) == ["INV-778", "INV-778A"]  # the T4 near-duplicates
    assert_typed_error(agent.get("/api/invoices?vendor=Verma"), 422, "invalid_request")


def test_invoice_detail_carries_vendor_approvals_and_payments(agent, world):
    data = agent.get(f"/api/invoices/{world['ok']['id']}").json()["data"]
    assert data["vendor_name"] == "Rao Packaging Industries"
    assert [p["id"] for p in data["payments"]] == [world["payment"]["id"]]
    over = agent.get(f"/api/invoices/{world['over']['id']}").json()["data"]
    assert [a["id"] for a in over["approvals"]] == [world["approval"]["id"]]


def test_bad_filters_and_paths_are_typed_invalid_request(agent):
    body = assert_typed_error(agent.get("/api/invoices?status=nope"), 422, "invalid_request")
    assert body["detail"].startswith("Unknown status 'nope'. Use one of:") and body["data"] == {"field": "status"}
    assert_typed_error(agent.get("/api/invoices/abc"), 422, "invalid_request")
    assert_typed_error(agent.get("/api/payments?invoice=0"), 422, "invalid_request")


def test_missing_entities_unknown_routes_and_wrong_methods_keep_the_typed_shape(agent):
    assert_typed_error(agent.get("/api/invoices/9999"), 404, "not_found")
    assert_typed_error(agent.post("/api/invoices/9999/void"), 404, "not_found")
    assert_typed_error(agent.get("/api/nope"), 404, "not_found")
    assert_typed_error(agent.get("/api/invoices/1/void"), 405, "invalid_request")


# --- writes and idempotency (3.5, N.45, N.52) -----------------------------------------------------


def test_invoice_write_goes_through_the_service_as_channel_api(db, agent):
    r = post_invoice(agent)
    assert r.status_code == 201 and "Idempotent-Replayed" not in r.headers
    data = r.json()["data"]
    assert (data["channel"], data["created_by"], data["status"]) == ("api", "ops-agent", "approved")
    channels = {row[0] for row in db.execute("SELECT channel FROM audit_log WHERE entity_type='invoice' AND entity_id=?",
                                             (data["id"],))}
    assert channels == {"api"}


def test_replay_returns_the_original_status_and_body_with_the_header_and_writes_once(db, agent):
    first = post_invoice(agent)
    after_first, rows = state_hash(db), count(db, "invoices")
    second = post_invoice(agent)
    assert (first.status_code, second.status_code) == (201, 201)
    assert second.json() == first.json()
    assert second.headers["Idempotent-Replayed"] == "true"
    assert count(db, "invoices") == rows and state_hash(db) == after_first


def test_replay_returns_the_original_response_even_after_the_row_changed(db, agent):
    first = post_invoice(agent).json()["data"]
    s.void_invoice(db, "ops-agent", "api", first["id"])
    replay = post_invoice(agent).json()["data"]
    assert replay["status"] == "approved"  # the original response, not current state: read back to see "void"
    assert agent.get(f"/api/invoices/{first['id']}").json()["data"]["status"] == "void"


@pytest.mark.parametrize("headers", [{}, {"Idempotency-Key": ""}])
def test_missing_key_is_400_before_any_write(db, agent, headers):
    before, audit = count(db, "invoices"), count(db, "audit_log")
    r = agent.post("/api/invoices", json=INVOICE, headers=headers)
    body = assert_typed_error(r, 400, "idempotency_key_required")
    assert body["data"] == {"field": "idempotency_key"}
    assert (count(db, "invoices"), count(db, "audit_log")) == (before, audit)


def test_same_key_with_a_different_body_is_409_key_reused(db, agent):
    post_invoice(agent)
    rows = count(db, "invoices")
    assert_typed_error(post_invoice(agent, {**INVOICE, "invoice_no": "INV-4002"}), 409, "idempotency_key_reused")
    assert count(db, "invoices") == rows


def test_too_long_key_is_invalid_input(agent):
    assert_typed_error(post_invoice(agent, key="k" * 201), 422, "invalid_input")


def test_a_ui_form_token_and_an_api_key_with_the_same_text_are_separate_writes(db, agent):
    ui = agent.post("/invoices/new", data={"vendor_id": "2", "invoice_no": "INV-4100", "invoice_date": "2026-10-01",
                                           "due_date": "2026-10-31", "amount": "100.00", "tax": "0",
                                           "idempotency_token": "shared-text"})
    api_r = post_invoice(agent, {**INVOICE, "invoice_no": "INV-4101"}, key="shared-text")
    assert ui.status_code == 303 and api_r.status_code == 201 and "Idempotent-Replayed" not in api_r.headers
    keys = db.execute("SELECT endpoint FROM idempotency_keys WHERE key='shared-text' ORDER BY endpoint").fetchall()
    assert [k[0] for k in keys] == ["api:POST /api/invoices", "ui:POST /invoices/new"]


def test_payment_write_is_idempotent_too(db, agent, world):
    s.cancel_payment(db, "ops-agent", "api", world["payment"]["id"])
    body = {"invoice_id": world["ok"]["id"]}
    first = agent.post("/api/payments", json=body, headers={"Idempotency-Key": "pay-1"})
    rows = count(db, "payments")
    second = agent.post("/api/payments", json=body, headers={"Idempotency-Key": "pay-1"})
    assert (first.status_code, second.status_code) == (201, 201)
    assert second.headers["Idempotent-Replayed"] == "true" and count(db, "payments") == rows
    assert_typed_error(agent.post("/api/payments", json=body), 400, "idempotency_key_required")


def test_approvals_and_it_tickets_take_no_key_so_a_retry_duplicates(db, agent, world):
    """Deliberate (register 3.5): read-before-retry is the only protection here."""
    invoice = s.submit_invoice(db, "ops-agent", "api", invoice_in(invoice_no="INV-4200", amount_paise=6_000_000))
    approvals, tickets = count(db, "approvals"), count(db, "it_tickets")
    for _ in range(2):
        assert agent.post("/api/approvals", json={"entity_type": "invoice", "entity_id": invoice["id"]}).status_code == 201
        assert agent.post("/api/it-tickets", json={"type": "accounts",
                                                   "employee_id": world["employee"]["id"]}).status_code == 201
    assert (count(db, "approvals"), count(db, "it_tickets")) == (approvals + 2, tickets + 2)


def test_employee_write(db, agent):
    r = agent.post("/api/employees", json=dict(name="Api Hire", email="api.hire@acme.example", role="Analyst",
                                                department="Finance", manager_id=1, start_date="2026-10-12"))
    assert r.status_code == 201 and r.json()["data"]["status"] == "onboarding"


# --- strict bodies (N.51), media type (0.10) ------------------------------------------------------


@pytest.mark.parametrize("override, field", [
    ({"vendor_id": True}, "vendor_id"),
    ({"amount_paise": "6240000"}, "amount_paise"),
    ({"amount_paise": 6240000.0}, "amount_paise"),
    ({"invoice_date": "01/10/2026"}, "invoice_date"),
])
def test_lax_coercions_are_rejected_with_the_field_named(db, agent, override, field):
    before = state_hash(db)
    body = assert_typed_error(post_invoice(agent, {**INVOICE, **override}), 422, "invalid_input")
    assert body["data"]["field"] == field and body["detail"].startswith(f"{field}: ")
    assert state_hash(db) == before


def test_spoofed_actor_in_the_body_is_rejected_by_the_strict_schema_and_nothing_is_written(db, agent):
    before, rows = state_hash(db), count(db, "invoices")
    body = assert_typed_error(post_invoice(agent, {**INVOICE, "actor": "meera"}), 422, "invalid_input")
    assert body["data"]["field"] == "actor" and "Extra inputs are not permitted" in body["detail"]
    assert count(db, "invoices") == rows and state_hash(db) == before


def test_spoofed_actor_in_query_or_header_is_ignored(db, agent):
    r = agent.post("/api/invoices?actor=meera", json=INVOICE,
                   headers={"Idempotency-Key": "spoof", "X-User": "meera", "X-Actor": "admin"})
    assert r.status_code == 201 and r.json()["data"]["created_by"] == "ops-agent"


def test_spoofed_actor_cannot_decide_an_approval(db, agent, world):
    before = state_hash(db)
    r = agent.post(f"/api/approvals/{world['approval']['id']}/decide?actor=meera", json={"decision": "approve"},
                   headers={"X-User": "meera"})
    assert_typed_error(r, 403, "forbidden")
    assert state_hash(db) == before


@pytest.mark.parametrize("payload", ['not json', '[1, 2]', '"text"', ''])
def test_a_body_that_is_not_a_json_object_is_400(agent, payload):
    r = agent.post("/api/invoices", content=payload, headers={"Content-Type": "application/json",
                                                               "Idempotency-Key": "bad-body"})
    assert_typed_error(r, 400, "invalid_request")


def test_form_encoded_write_is_415_and_json_with_charset_is_fine(db, agent):
    rows = count(db, "invoices")
    r = agent.post("/api/invoices", data={k: str(v) for k, v in INVOICE.items()}, headers={"Idempotency-Key": "f"})
    assert_typed_error(r, 415, "unsupported_media_type")
    assert count(db, "invoices") == rows
    import json
    ok = agent.post("/api/invoices", content=json.dumps(INVOICE),
                    headers={"Content-Type": "application/json; charset=utf-8", "Idempotency-Key": "cs"})
    assert ok.status_code == 201


def test_ui_form_login_still_works_because_api_login_is_exempt_from_the_json_rule(db_file):
    """D-037: the /login page posts form-encoded to /api/login."""
    client = make_client(db_file, None)
    r = client.post("/api/login", data={"username": "ops-agent", "password": "ops-agent-dev-pw", "next": "/invoices"})
    assert r.status_code == 303 and r.headers["location"] == "/invoices"
    assert client.get("/invoices").status_code == 200


# --- roles, undo (N.22, 7.3) ---------------------------------------------------------------------


def test_meera_decides_through_the_api_and_the_audit_says_meera_via_api(db, meera, world):
    r = meera.post(f"/api/approvals/{world['approval']['id']}/decide", json={"decision": "approve"})
    assert r.status_code == 200 and r.json()["data"]["status"] == "approved"
    rows = db.execute("SELECT DISTINCT actor, channel FROM audit_log WHERE action IN ('invoice.approve', "
                      "'approval.decide')").fetchall()
    assert [tuple(r) for r in rows] == [("meera", "api")]


def test_undo_endpoints_compensate_and_are_audited_as_api(db, agent, world):
    for path in (f"/api/payments/{world['payment']['id']}/cancel", f"/api/invoices/{world['ok']['id']}/void",
                 f"/api/approvals/{world['approval']['id']}/withdraw",
                 f"/api/it-tickets/{world['ticket']['id']}/cancel", f"/api/employees/{world['employee']['id']}/cancel"):
        assert agent.post(path).status_code == 200, path
    statuses = {t: db.execute(f"SELECT status FROM {t} WHERE id=?", (world[k]["id"],)).fetchone()[0]
                for t, k in (("payments", "payment"), ("invoices", "ok"), ("approvals", "approval"),
                             ("it_tickets", "ticket"), ("employees", "employee"))}
    assert statuses == {"payments": "cancelled", "invoices": "void", "approvals": "withdrawn",
                        "it_tickets": "cancelled", "employees": "cancelled"}


def test_undo_twice_is_a_409_that_states_the_current_status_and_writes_nothing(db, agent, world):
    path = f"/api/invoices/{world['ok']['id']}/void"
    s.cancel_payment(db, "ops-agent", "api", world["payment"]["id"])
    assert agent.post(path).status_code == 200
    audit = count(db, "audit_log")
    body = assert_typed_error(agent.post(path), 409, "conflict")
    assert "void" in body["detail"] and count(db, "audit_log") == audit


def test_undo_on_someone_elses_record_is_403(db, agent):
    assert_typed_error(agent.post("/api/invoices/3/void"), 403, "forbidden")  # entered by the human clerk
    assert db.execute("SELECT status FROM invoices WHERE id=3").fetchone()[0] == "approved"


def test_expired_session_on_a_write_is_401_json_and_writes_nothing(db, agent):
    reset(db, "base")  # wipes sessions, as at the start of every run
    rows = count(db, "invoices")
    r = post_invoice(agent)
    assert r.status_code == 401 and r.headers["content-type"].startswith("application/json")
    assert r.json()["error_type"] == "session_expired" and count(db, "invoices") == rows


def test_unexpected_failure_is_a_typed_500_that_leaks_nothing_and_rolls_back(db, db_file, monkeypatch):
    client = make_client(db_file, "ops-agent", raise_server_exceptions=False)
    rows, audit = count(db, "invoices"), count(db, "audit_log")
    real = s.submit_invoice

    def boom(conn, *args):
        real(conn, *args)  # the write happens inside the transaction, then the failure
        raise RuntimeError("secret internals")

    monkeypatch.setattr(s, "submit_invoice", boom)
    r = post_invoice(client)
    body = assert_typed_error(r, 500, "server_error")
    assert "secret" not in r.text and "Read back before retrying" in body["detail"]
    assert (count(db, "invoices"), count(db, "audit_log"), count(db, "idempotency_keys")) == (rows, audit, 0)


# --- audit (N.53) --------------------------------------------------------------------------------


def all_ids(db):
    return [r[0] for r in db.execute("SELECT id FROM audit_log ORDER BY id")]


def test_audit_since_returns_later_rows_in_id_order_for_all_actors(db, agent):
    since = (all_ids(db) or [0])[-1]
    post_invoice(agent)  # below the limit: ops-agent submit + system auto-approval
    items = agent.get(f"/api/audit?since={since}").json()["data"]["items"]
    assert [(i["actor"], i["action"], i["channel"]) for i in items] == [
        ("ops-agent", "invoice.submit", "api"), ("system", "invoice.auto_approve", "api")]
    assert items[1]["reason"] == "ORG-001 below limit"
    assert items[1]["before"]["status"] == "pending_approval" and items[1]["after"]["status"] == "approved"
    assert [i["id"] for i in items] == sorted(i["id"] for i in items)


def test_audit_paging_covers_every_row_exactly_once(db, agent, world):
    since, seen = 0, []
    while True:
        data = agent.get(f"/api/audit?since={since}&limit=2").json()["data"]
        seen += [i["id"] for i in data["items"]]
        since = data["next_since"]
        if not data["has_more"]:
            break
    assert seen == all_ids(db) and len(seen) > 2


def test_audit_past_the_end_is_empty_and_keeps_since(db, agent, world):
    last = all_ids(db)[-1]
    data = agent.get(f"/api/audit?since={last}").json()["data"]
    assert data == {"items": [], "has_more": False, "next_since": last}


@pytest.mark.parametrize("query", ["since=-1", "since=abc", "limit=0", "limit=1001"])
def test_audit_rejects_bad_parameters(agent, query):
    assert_typed_error(agent.get(f"/api/audit?{query}"), 422, "invalid_request")


def test_audit_never_shows_a_full_bank_account_and_meera_can_read_it(db, meera):
    s.update_vendor_bank(db, "admin", 1, "000123456789012")
    text = meera.get("/api/audit").text
    assert "000123456789012" not in text and "9012" in text


# --- error types are one fixed list (N.50) --------------------------------------------------------


def _subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from _subclasses(sub)


def test_every_service_error_declares_a_listed_error_type():
    assert s.AcmeError.error_type in ERROR_TYPES
    for cls in _subclasses(s.AcmeError):
        assert cls.error_type in ERROR_TYPES, cls


def test_an_undeclared_error_type_cannot_be_sent():
    with pytest.raises(ValueError):
        api_error(400, "something_new", "x")


def test_the_error_type_list_is_exactly_what_the_spec_documents():
    spec = Path("docs/acme-spec.md").read_text()
    section = spec[spec.index("## API"):]
    section = section[:section.index("\n## ", 5)]
    documented = re.findall(r"^\| `([a-z_]+)` \|", section, re.M)
    assert tuple(documented) == ERROR_TYPES


# --- channel parity and concurrency (N.21, N.25, N.54) --------------------------------------------


def ui_invoice(client, **fields):
    form = {"vendor_id": "2", "invoice_no": "INV-P", "invoice_date": "2026-10-01", "due_date": "2026-10-31",
            "amount": "18500.00", "tax": "2822.03", "idempotency_token": fields.pop("token", "ui-tok"), **fields}
    return client.post("/invoices/new", data=form)


PARITY = [  # (ui form overrides, api body overrides)
    ({"due_date": "2026-09-01"}, {"due_date": "2026-09-01"}),
    ({"amount": "100.00", "tax": "200.00"}, {"amount_paise": 10_000, "tax_paise": 20_000}),
    ({"invoice_no": "INV-DUP"}, {"invoice_no": "INV-DUP"}),
    ({"invoice_date": "2026-10-09"}, {"invoice_date": "2026-10-09"}),
]


@pytest.mark.parametrize("ui_fields, api_fields", PARITY)
def test_same_invalid_input_gives_the_same_error_on_both_channels(db, agent, ui_fields, api_fields):
    s.submit_invoice(db, "ops-agent", "api", invoice_in(invoice_no="INV-DUP"))
    ui = ui_invoice(agent, **ui_fields)
    api_r = post_invoice(agent, {**INVOICE, "invoice_no": "INV-P", **api_fields}, key="parity")
    assert ui.status_code == api_r.status_code
    assert api_r.json()["detail"] in Page(ui.text).alerts


def test_parity_for_payments_employees_and_filters(db, agent, world):
    ui = agent.post("/payments/new", data={"invoice_id": str(world["over"]["id"]), "idempotency_token": "p"})
    api_r = agent.post("/api/payments", json={"invoice_id": world["over"]["id"]}, headers={"Idempotency-Key": "p"})
    assert ui.status_code == api_r.status_code == 409 and api_r.json()["detail"] in Page(ui.text).alerts
    emp = dict(name="X", email="x@gmail.com", role="r", department="d", manager_id=1, start_date="2026-10-12")
    ui = agent.post("/employees/new", data={**emp, "manager_id": "1"})
    api_r = agent.post("/api/employees", json=emp)
    assert ui.status_code == api_r.status_code == 422 and api_r.json()["detail"] in Page(ui.text).alerts
    ui = agent.get("/invoices?status=nope")
    api_r = agent.get("/api/invoices?status=nope")
    assert ui.status_code == api_r.status_code == 422 and api_r.json()["detail"] in Page(ui.text).alerts


def run_together(*calls):
    barrier, results = threading.Barrier(len(calls)), [None] * len(calls)

    def run(i, call):
        barrier.wait()
        results[i] = call()

    threads = [threading.Thread(target=run, args=(i, c)) for i, c in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


@pytest.mark.parametrize("attempt", range(5))
def test_ui_and_api_submitting_the_same_invoice_at_once_give_one_row_and_one_409(db, db_file, attempt):
    ui_client, api_client = make_client(db_file, "ops-agent"), make_client(db_file, "ops-agent")
    number = f"INV-RACE-{attempt}"
    ui, api_r = run_together(lambda: ui_invoice(ui_client, invoice_no=number, token=f"t{attempt}"),
                             lambda: post_invoice(api_client, {**INVOICE, "invoice_no": number}, key=f"k{attempt}"))
    assert sorted([ui.status_code, api_r.status_code]) in ([201, 409], [303, 409]), (ui.status_code, api_r.status_code)
    assert db.execute("SELECT COUNT(*) FROM invoices WHERE invoice_no=?", (number,)).fetchone()[0] == 1


@pytest.mark.parametrize("attempt", range(5))
def test_two_api_calls_with_one_key_at_once_write_once(db, db_file, attempt):
    a, b = make_client(db_file, "ops-agent"), make_client(db_file, "ops-agent")
    body = {**INVOICE, "invoice_no": f"INV-KEY-{attempt}"}
    first, second = run_together(lambda: post_invoice(a, body, key=f"same-{attempt}"),
                                 lambda: post_invoice(b, body, key=f"same-{attempt}"))
    assert first.status_code == second.status_code == 201 and first.json() == second.json()
    assert sorted(r.headers.get("Idempotent-Replayed", "") for r in (first, second)) == ["", "true"]
    assert db.execute("SELECT COUNT(*) FROM invoices WHERE invoice_no=?", (body["invoice_no"],)).fetchone()[0] == 1


# --- structure: thin routers, one write path (N.45, N.55) -----------------------------------------


def test_every_api_write_goes_through_the_one_write_helper():
    posts = [r for r in api.router.routes if "POST" in r.methods]
    assert len(posts) == 12
    for route in posts:
        assert "_write" in route.endpoint.__code__.co_names, route.path


def test_the_api_router_has_no_sql_and_no_second_idempotency_store():
    source = inspect.getsource(api)
    for forbidden in ("INSERT", "UPDATE ", "DELETE ", "idempotency_keys", "execute("):
        assert forbidden not in source, forbidden
    assert "idempotency.run(" in source
