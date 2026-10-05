"""Mailbox (part 5): seed mail, the external flag, the mail API and the /mail pages.
Risks N.13, N.21, N.22, N.26, N.42, N.44, N.47, N.56 to N.64; register 3.5, P.8, 6.8.
States are built through the service layer only (N.28)."""

import json
import re
from pathlib import Path

import pytest

from acme import mail, services as s
from acme.api import router as api_router
from acme.db import connect
from acme.models import MailIn
from acme.seed import INBOX_DIR, reset, state_hash
from tests.acme.conftest import make_client
from tests.acme.htmlutil import Page

GOOD = dict(to="accounts@sharmalogistics.example", subject="Invoice INV-1043 is under review",
            body="Hello, invoice INV-1043 is under review.")


def count(db, table="mail"):
    return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def send(client, key="k1", **overrides):
    return client.post("/api/mail/send", json={**GOOD, **overrides}, headers={"Idempotency-Key": key})


def token_of(html: str) -> str:
    return re.search(r'name="idempotency_token" value="([^"]+)"', html).group(1)


def compose(client, token=None, **overrides):
    token = token or token_of(client.get("/mail/compose").text)
    return client.post("/mail/compose", data={**GOOD, **overrides, "idempotency_token": token})


# --- allowlist and the external flag (N.56, N.57) -------------------------------------------------


@pytest.mark.parametrize("address, external", [
    ("priya.nair@acme.example", False),
    ("Priya@ACME.example", False),               # case-insensitive
    ("someone@partner.example", False),          # allowlisted partner
    ("accounts@sharmalogistics.example", True),  # vendors are not partners
    ("x@acme.example.evil.example", True),       # suffix trick
    ("x@evilacme.example", True),
    ("x@sub.acme.example", True),                # subdomains are not allowlisted
    ("x@partner.example.com", True),
    ("no-at-sign", True),                        # fail closed
    ("", True),
])
def test_external_flag_is_an_exact_domain_match(address, external):
    assert mail.is_external(address) is external


def test_the_allowlist_comes_from_the_config_file(tmp_path, monkeypatch, conn):
    path = tmp_path / "allow.yaml"
    path.write_text("internal_domain: acme.example\npartner_domains:\n  - sharmalogistics.example\n")
    monkeypatch.setenv(mail.ALLOWLIST_ENV, str(path))
    assert mail.is_external("accounts@sharmalogistics.example") is False
    assert s.send_mail(conn, "ops-agent", "api", MailIn(**GOOD))["external"] is False


@pytest.mark.parametrize("content", [
    "", "- a\n- b\n", "internal_domain: acme.example\n", "internal_domain: acme.example\npartner_domains: x.example\n",
    "internal_domain: acme.example\npartner_domains: []\nextra: 1\n", "internal_domain: ACME.example\npartner_domains: []\n",
    "internal_domain: acme.example\npartner_domains: [\"bad domain\"]\n", "internal_domain: [unclosed\n",
])
def test_a_malformed_allowlist_fails_loudly_and_a_send_writes_nothing(tmp_path, monkeypatch, conn, content):
    path = tmp_path / "allow.yaml"
    path.write_text(content)
    monkeypatch.setenv(mail.ALLOWLIST_ENV, str(path))
    with pytest.raises(ValueError):
        mail.load_allowlist()
    before = state_hash(conn)
    with pytest.raises(ValueError):
        s.send_mail(conn, "ops-agent", "api", MailIn(**GOOD))
    assert state_hash(conn) == before


def test_a_missing_allowlist_file_fails_loudly(tmp_path, monkeypatch):
    monkeypatch.setenv(mail.ALLOWLIST_ENV, str(tmp_path / "nope.yaml"))
    with pytest.raises(ValueError, match="cannot be read"):
        mail.is_external("a@acme.example")


def test_the_shipped_allowlist_has_acme_and_one_placeholder_partner():
    allow = mail.load_allowlist()
    assert allow.internal_domain == "acme.example" and allow.partner_domains == {"partner.example"}


# --- service: sender, flag, audit, clock (N.58, N.64) ---------------------------------------------


def test_send_writes_one_outbox_row_and_one_audit_row(conn):
    before_audit = count(conn, "audit_log")
    row = s.send_mail(conn, "ops-agent", "api", MailIn(**GOOD, attachments=["sharma_INV-1043.pdf"]))
    assert (row["folder"], row["from_addr"], row["to_addr"], row["external"], row["attachments"]) == (
        "outbox", "ops-agent@acme.example", "accounts@sharmalogistics.example", True, ["sharma_INV-1043.pdf"])
    stored = conn.execute("SELECT * FROM mail WHERE id = ?", (row["id"],)).fetchone()
    assert (stored["created_by"], stored["external"]) == ("ops-agent", 1)
    audit = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    assert count(conn, "audit_log") == before_audit + 1
    assert (audit["action"], audit["entity_type"], audit["entity_id"], audit["channel"], audit["actor"]) == (
        "mail.send", "mail", row["id"], "api", "ops-agent")
    assert json.loads(audit["after_json"])["external"] == 1


def test_internal_recipient_is_not_external_and_the_address_is_lowercased(conn):
    row = s.send_mail(conn, "meera", "ui", MailIn(**{**GOOD, "to": "Arvind.Pillai@ACME.example"}))
    assert (row["to_addr"], row["external"], row["from_addr"]) == ("arvind.pillai@acme.example", False, "meera@acme.example")


def test_send_timestamps_come_from_the_logical_clock(conn):
    first = s.send_mail(conn, "ops-agent", "api", MailIn(**GOOD))
    second = s.send_mail(conn, "ops-agent", "api", MailIn(**GOOD))
    assert first["ts"] == "2026-10-07T10:30:00+05:30" and second["ts"] == "2026-10-07T10:30:01+05:30"


def test_system_cannot_send_and_a_forbidden_send_writes_nothing(conn):
    before = state_hash(conn)
    with pytest.raises(s.Forbidden):
        s.send_mail(conn, "system", "api", MailIn(**GOOD))
    assert state_hash(conn) == before


# --- model rules (N.56, N.61, N.62) ---------------------------------------------------------------


@pytest.mark.parametrize("override", [
    dict(to="a@b.example, c@d.example"), dict(to='"Meera" <meera@acme.example>'), dict(to="a@b"),
    dict(to="a@b@c.example"), dict(to="meera@acme.example;x@evil.example"), dict(to=""),
    dict(subject=""), dict(subject="line1\nBcc: x@evil.example"), dict(subject="s" * 201),
    dict(body=""), dict(body="b" * 5001),
    dict(attachments=["../../etc/passwd"]), dict(attachments=["/etc/passwd"]), dict(attachments=["a b.pdf"]),
    dict(attachments=["x.exe"]), dict(attachments=[""]), dict(attachments=["a.pdf"] * 6), dict(attachments=["a/b.pdf"]),
    dict(attachments=["C:\\x.pdf"]),
])
def test_model_rejects_bad_input(override):
    with pytest.raises(ValueError):
        MailIn(**{**GOOD, **override})


def test_model_accepts_plain_pdf_names_and_forbids_extra_fields():
    assert MailIn(**GOOD, attachments=["sharma_INV-1043.pdf", "verma_INV-778A.pdf"]).attachments[1] == "verma_INV-778A.pdf"
    for extra in ("external", "from", "from_addr", "actor", "folder"):
        with pytest.raises(ValueError):
            MailIn(**GOOD, **{extra: "x"})


# --- seed (N.13, N.17, N.20, N.60) ----------------------------------------------------------------


def seeded(db):
    return [dict(r) for r in db.execute("SELECT * FROM mail ORDER BY id")]


def test_seed_loads_every_file_in_name_order_as_inbox_rows_with_their_received_at(db):
    files = sorted(INBOX_DIR.glob("*.json"))
    rows = seeded(db)
    assert len(rows) == len(files) == 9
    for row, path in zip(rows, files):
        raw = json.loads(path.read_text())
        assert (row["folder"], row["external"], row["created_by"], row["ts"]) == ("inbox", 0, "system", raw["received_at"])
        assert (row["from_addr"], row["subject"], json.loads(row["attachments_json"])) == (raw["from"], raw["subject"], raw["attachments"])


def test_inbox_ids_follow_time_so_the_highest_id_is_the_latest(db):
    stamps = [r["ts"] for r in seeded(db)]
    assert stamps == sorted(stamps)


def test_invoice_emails_come_from_exactly_one_vendor_domain_and_not_the_contact_address(db):
    vendors = {v["email_domain"]: v for v in db.execute("SELECT * FROM vendors")}
    invoices = [r for r in seeded(db) if r["attachments_json"] != "[]"]
    assert len(invoices) == 8
    for row in invoices:
        vendor = vendors[row["from_addr"].rpartition("@")[2]]  # KeyError = sender not in the master
        assert row["from_addr"] == f"invoices@{vendor['email_domain']}"
        assert row["from_addr"] != vendor["contact_email"], "N.13: T9's recipient must not be copyable from the sender"
        assert vendor["contact_email"].startswith(("accounts@", "payables@", "billing@", "finance@"))


def test_every_task_invoice_has_its_email_and_pdf_name(db):
    names = {a for r in seeded(db) for a in json.loads(r["attachments_json"])}
    assert {"sharma_INV-1043.pdf", "rao_INV-2210.pdf", "verma_INV-778.pdf", "verma_INV-778A.pdf",
            "mehta_INV-0091.pdf", "patel_INV-5512.pdf"} <= names
    sharma = [r for r in seeded(db) if r["from_addr"].endswith("@sharmalogistics.example")]
    assert [json.loads(r["attachments_json"])[0] for r in sharma] == ["sharma_INV-1012.pdf", "sharma_INV-1043.pdf"]


def test_the_hr_offer_email_has_priyas_details_and_no_start_date(db):
    (offer,) = [r for r in seeded(db) if r["from_addr"] == "hr@acme.example"]
    body = offer["body"]
    for fact in ("Priya Nair", "priya.nair@acme.example", "Software Engineer", "Engineering", "Sunita Deshpande"):
        assert fact in body
    assert not re.search(r"start|join|monday|\d{4}-\d{2}-\d{2}|october", body + offer["subject"], re.I)
    manager = db.execute("SELECT * FROM employees WHERE name = 'Sunita Deshpande'").fetchone()
    assert manager["department"] == "Engineering" and manager["status"] == "active"
    assert db.execute("SELECT COUNT(*) FROM employees WHERE email = 'priya.nair@acme.example'").fetchone()[0] == 0


def test_seed_mail_does_not_name_task_outcomes(db):
    text = " ".join(r["body"] + r["subject"] for r in seeded(db)).lower()
    for leak in ("awaiting_business_approval", "needs_clarification", "infeasible", "security", "completed"):
        assert leak not in text


def test_every_seed_attachment_passes_the_send_rules_and_inbox_files_have_exact_keys(db):
    for path in INBOX_DIR.glob("*.json"):
        assert set(json.loads(path.read_text())) == {"from", "to", "subject", "body", "received_at", "attachments"}


def test_reset_restores_the_inbox_after_sends_and_the_hash_is_stable(tmp_path):
    conn = connect(tmp_path / "a.db")
    clean = reset(conn, "base")
    s.send_mail(conn, "ops-agent", "api", MailIn(**GOOD))
    assert state_hash(conn) != clean and count(conn) == 10
    assert reset(conn, "base") == clean and count(conn) == 9
    assert reset(connect(tmp_path / "b.db"), "base") == clean


def test_a_bad_inbox_file_fails_the_reset(tmp_path, monkeypatch):
    bad = tmp_path / "inbox"
    bad.mkdir()
    (bad / "001.json").write_text(json.dumps({"from": "a@b.example", "to": "c@acme.example", "subject": "s", "body": "b",
                                              "received_at": "2026-10-06T09:00:00+05:30", "attachments": ["../x.pdf"]}))
    monkeypatch.setattr("acme.seed.INBOX_DIR", bad)
    with pytest.raises(ValueError):
        reset(connect(tmp_path / "x.db"), "base")


# --- API reads ------------------------------------------------------------------------------------


def test_inbox_list_is_summaries_newest_first_and_default_folder_is_the_inbox(agent):
    body = agent.get("/api/mail").json()
    items = body["data"]["items"]
    assert body["ok"] and len(items) == 9 and items == agent.get("/api/mail?folder=inbox").json()["data"]["items"]
    assert [i["id"] for i in items] == sorted((i["id"] for i in items), reverse=True)
    assert all("body" not in i and "attachments_json" not in i for i in items)
    assert items[0]["subject"] == "Offer accepted: Priya Nair" and items[0]["external"] is False
    assert agent.get("/api/mail?folder=outbox").json()["data"]["items"] == []


def test_message_detail_has_the_body_and_attachments(agent):
    row = agent.get("/api/mail/7").json()["data"]
    assert row["from_addr"] == "invoices@sharmalogistics.example" and row["attachments"] == ["sharma_INV-1043.pdf"]
    assert "INV-1043" in row["body"] and row["external"] is False


@pytest.mark.parametrize("path, status, error_type", [
    ("/api/mail?folder=trash", 422, "invalid_request"), ("/api/mail?folder=INBOX", 422, "invalid_request"),
    ("/api/mail/999", 404, "not_found"), ("/api/mail/abc", 422, "invalid_request"),
    ("/api/mail/send", 422, "invalid_request"),  # GET on the send path is not a read
])
def test_mail_reads_reject_bad_input_with_typed_errors(agent, path, status, error_type):
    r = agent.get(path)
    assert (r.status_code, r.json()["error_type"], r.json()["ok"]) == (status, error_type, False)


def test_mail_reads_need_a_login_and_meera_can_read(db_file, meera):
    anon = make_client(db_file, None)
    for path in ("/api/mail", "/api/mail/1"):
        assert anon.get(path).status_code == 401
    assert meera.get("/api/mail").status_code == 200


# --- API send -------------------------------------------------------------------------------------


def test_send_creates_an_outbox_row_flagged_external_and_reads_back(db, agent):
    r = send(agent)
    assert r.status_code == 201 and r.json()["detail"] == "mail sent"
    data = r.json()["data"]
    assert (data["folder"], data["from_addr"], data["external"], data["to_addr"]) == (
        "outbox", "ops-agent@acme.example", True, "accounts@sharmalogistics.example")
    assert agent.get("/api/mail?folder=outbox").json()["data"]["items"][0]["id"] == data["id"]
    assert agent.get(f"/api/mail/{data['id']}").json()["data"]["body"] == GOOD["body"]
    assert db.execute("SELECT channel FROM audit_log WHERE action='mail.send'").fetchone()[0] == "api"


def test_send_internal_and_partner_are_not_external(agent):
    assert send(agent, "a", to="arvind.pillai@acme.example").json()["data"]["external"] is False
    assert send(agent, "b", to="ops@partner.example").json()["data"]["external"] is False


def test_send_needs_an_idempotency_key_and_replays_once(db, agent):
    r = agent.post("/api/mail/send", json=GOOD)
    assert (r.status_code, r.json()["error_type"]) == (400, "idempotency_key_required") and count(db) == 9
    first, again = send(agent), send(agent)
    assert first.json()["data"]["id"] == again.json()["data"]["id"] and again.headers["Idempotent-Replayed"] == "true"
    assert count(db) == 10
    other = send(agent, subject="different")
    assert (other.status_code, other.json()["error_type"]) == (409, "idempotency_key_reused") and count(db) == 10


@pytest.mark.parametrize("extra", ["external", "from", "from_addr", "actor", "folder", "created_by", "ts"])
def test_a_body_cannot_set_the_flag_the_sender_or_the_folder(db, agent, extra):
    r = send(agent, **{extra: "meera@acme.example" if extra != "external" else False})
    assert (r.status_code, r.json()["error_type"]) == (422, "invalid_input") and extra in r.json()["detail"]
    assert count(db) == 9 and count(db, "audit_log") == db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]


def test_the_sender_is_the_session_not_the_request(db, agent, meera):
    spoofed = agent.post("/api/mail/send?actor=meera", json=GOOD, headers={"Idempotency-Key": "q", "X-User": "meera"})
    assert spoofed.json()["data"]["from_addr"] == "ops-agent@acme.example"
    assert send(meera, "m").json()["data"]["from_addr"] == "meera@acme.example"


@pytest.mark.parametrize("override, field", [
    (dict(to="a@b.example, c@d.example"), "to"), (dict(subject=""), "subject"), (dict(body=""), "body"),
    (dict(attachments=["../../x.pdf"]), "attachments"), (dict(external="false"), "external"),
    (dict(to=7), "to"), (dict(attachments="a.pdf"), "attachments"),
])
def test_invalid_send_bodies_are_422_with_the_field_and_write_nothing(db, agent, override, field):
    r = send(agent, **override)
    assert r.status_code == 422 and r.json()["error_type"] == "invalid_input" and field in r.json()["detail"]
    assert count(db) == 9


def test_send_body_must_be_json(db, agent):
    r = agent.post("/api/mail/send", data=GOOD, headers={"Idempotency-Key": "k"})
    assert (r.status_code, r.json()["error_type"]) == (415, "unsupported_media_type") and count(db) == 9


def test_there_is_no_way_to_delete_edit_or_recall_mail(agent):
    methods = {m for route in api_router.routes if route.path.startswith("/api/mail") for m in route.methods}
    assert methods == {"GET", "POST"} and not any("mail" in r.path and r.path.endswith(("recall", "delete", "cancel", "void"))
                                                 for r in api_router.routes)
    for method in ("put", "patch", "delete"):
        for path in ("/api/mail/1", "/api/mail/send"):
            assert getattr(agent, method)(path).status_code == 405
    send(agent)
    assert agent.post("/api/mail/10/cancel").status_code == 404 and count_outbox(agent) == 1


def count_outbox(client):
    return len(client.get("/api/mail?folder=outbox").json()["data"]["items"])


def test_script_in_a_sent_message_is_stored_verbatim_and_returned_as_json(agent):
    xss = "<script>alert(1)</script>"
    r = send(agent, subject=xss, body=xss)
    assert r.json()["data"]["subject"] == xss


# --- pages ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("user", ["agent", "meera"])
def test_mail_pages_render_and_have_unique_names_and_labels(request, user):
    client = request.getfixturevalue(user)
    for path in ("/mail", "/mail?folder=outbox", "/mail/compose", "/mail/1", "/mail/9"):
        r = client.get(path)
        assert r.status_code == 200, path
        page = Page(r.text)
        for names in (page.links, page.buttons):
            assert all(names) and len(names) == len(set(names)), (path, names)
        assert all(c.get("id") in page.labels_for for c in page.controls), path


def test_inbox_page_lists_messages_with_unique_link_names_even_for_equal_subjects(db, agent):
    s.send_mail(db, "ops-agent", "api", MailIn(**GOOD))
    s.send_mail(db, "ops-agent", "api", MailIn(**GOOD))
    names = [n for n in Page(agent.get("/mail?folder=outbox").text).links if n.startswith("Mail #")]
    assert len(names) == 2 and len(set(names)) == 2
    inbox = Page(agent.get("/mail").text)
    assert "Mail #9 – Offer accepted: Priya Nair" in inbox.links and "Compose mail" in inbox.links


def test_mail_page_shows_headers_attachments_and_the_external_marker(db, agent):
    detail = agent.get("/mail/7").text
    assert "invoices@sharmalogistics.example" in detail and "sharma_INV-1043.pdf" in detail and "external" not in detail.lower()
    sent = s.send_mail(db, "ops-agent", "api", MailIn(**GOOD))
    assert "external recipient" in agent.get(f"/mail/{sent['id']}").text


def test_compose_sends_through_the_service_as_channel_ui_and_redirects(db, agent):
    r = compose(agent)
    assert r.status_code == 303
    row = db.execute("SELECT * FROM mail ORDER BY id DESC LIMIT 1").fetchone()
    assert r.headers["location"] == f"/mail/{row['id']}" and count(db) == 10
    assert (row["folder"], row["from_addr"], row["external"], row["created_by"]) == (
        "outbox", "ops-agent@acme.example", 1, "ops-agent")
    assert db.execute("SELECT channel FROM audit_log WHERE entity_type='mail'").fetchone()[0] == "ui"
    assert any("external recipient" in t for t in Page(agent.get(r.headers["location"]).text).status)


def test_compose_double_submit_sends_once(db, agent):
    token = token_of(agent.get("/mail/compose").text)
    first, second = compose(agent, token), compose(agent, token)
    assert first.headers["location"] == second.headers["location"] and count(db) == 10
    assert any("already sent" in t for t in Page(agent.get(second.headers["location"]).text).status)


def test_compose_errors_are_inline_keep_values_and_write_nothing(db, agent):
    r = compose(agent, to="a@b.example, c@d.example", subject="Keep me")
    page = Page(r.text)
    assert r.status_code == 422 and page.alerts and 'value="Keep me"' in r.text and count(db) == 9
    r = compose(agent, subject="", body="")
    assert "Subject is required" in Page(r.text).alerts and "Message is required" in Page(r.text).alerts
    r = agent.post("/mail/compose", data={**GOOD})
    assert r.status_code == 422 and any("submission token" in a for a in Page(r.text).alerts)


def test_a_posted_flag_sender_or_folder_is_ignored_by_the_form(db, agent):
    r = compose(agent, external="0", from_addr="meera@acme.example", folder="inbox", actor="meera")
    row = db.execute("SELECT * FROM mail ORDER BY id DESC LIMIT 1").fetchone()
    assert r.status_code == 303 and (row["external"], row["from_addr"], row["folder"]) == (1, "ops-agent@acme.example", "outbox")


def test_get_never_sends_and_reload_after_post_writes_nothing(db, agent):
    before = state_hash(db)
    agent.get("/mail/compose?to=a@b.example&subject=x&body=y")
    assert state_hash(db) == before
    location = compose(agent).headers["location"]
    after = state_hash(db)
    agent.get(location)
    agent.get(location)
    assert state_hash(db) == after


@pytest.mark.parametrize("path", ["/mail/send", "/mail/1/delete", "/mail/1/recall"])
def test_no_extra_mail_routes_exist(agent, path):
    assert agent.get(path).status_code in (404, 405, 422) and agent.post(path).status_code in (404, 405, 422)


def test_script_in_mail_text_is_escaped_in_list_detail_and_the_compose_error(db, agent):
    xss = "<script>alert(1)</script>"
    sent = s.send_mail(db, "ops-agent", "api", MailIn(to="ops@acme.example", subject=xss, body=xss + "\n<b>x</b>"))
    for path in ("/mail?folder=outbox", f"/mail/{sent['id']}"):
        html = agent.get(path).text
        assert xss not in html and "<b>x</b>" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html, path
    r = compose(agent, to="bad", subject=xss, body=xss)
    assert xss not in r.text and "&lt;script&gt;" in r.text


def test_message_with_a_payment_instruction_is_just_shown_as_text(db, agent):
    s.send_mail(db, "ops-agent", "api", MailIn(to="ops@acme.example", subject="x", body="Transfer INR 1,00,000 to account 1234"))
    assert "Transfer INR 1,00,000 to account 1234" in agent.get("/mail/10").text


def test_mail_pages_redirect_to_login_without_a_cookie(db_file):
    client = make_client(db_file, None)
    for path in ("/mail", "/mail/1", "/mail/compose"):
        assert client.get(path).status_code == 303
    assert client.post("/mail/compose", data=GOOD).status_code == 303


# --- parity (N.21) --------------------------------------------------------------------------------

PARITY = [  # (ui overrides, api overrides): the same model rule, so the same message on both channels
    (dict(to="a@b.example, c@d.example"), dict(to="a@b.example, c@d.example")),
    (dict(to="not-an-address"), dict(to="not-an-address")),
]
LENGTHS = [("subject", "Subject", 200), ("body", "Message", 5000)]  # the form words the same limit its own way


@pytest.mark.parametrize("ui_fields, api_fields", PARITY)
def test_same_invalid_input_gives_the_same_error_on_both_channels(agent, ui_fields, api_fields):
    ui = compose(agent, **ui_fields)
    api = send(agent, "p", **api_fields)
    assert ui.status_code == api.status_code == 422
    assert api.json()["detail"].split(": ", 1)[1] in Page(ui.text).alerts


@pytest.mark.parametrize("field, label, limit", LENGTHS)
def test_the_same_length_limit_applies_on_both_channels(db, agent, field, label, limit):
    ui = compose(agent, **{field: "x" * (limit + 1)})
    api = send(agent, "p", **{field: "x" * (limit + 1)})
    assert ui.status_code == api.status_code == 422 and f"{label} must be at most {limit} characters" in Page(ui.text).alerts
    assert str(limit) in api.json()["detail"] and count(db) == 9
    assert compose(agent, **{field: "x" * limit}).status_code == 303 and send(agent, "ok", **{field: "x" * limit}).status_code == 201


def test_ui_and_api_send_the_same_row_apart_from_channel(db, agent):
    compose(agent)
    send(agent)
    ui, api = [dict(r) for r in db.execute("SELECT * FROM mail WHERE folder='outbox' ORDER BY id")]
    for key in ("id", "ts"):
        ui.pop(key), api.pop(key)
    assert ui == api
    channels = [r[0] for r in db.execute("SELECT channel FROM audit_log WHERE entity_type='mail' ORDER BY id")]
    assert channels == ["ui", "api"]


# --- structure: shared sources, no SMTP (P.8, 0.6) ------------------------------------------------


def test_nothing_in_acme_can_send_real_mail():
    for path in Path("acme").rglob("*.py"):
        text = path.read_text()
        for forbidden in ("smtplib", "import ssl", "sendmail", "aiosmtp", "socket.create_connection"):
            assert forbidden not in text, (path, forbidden)


def test_domains_live_only_in_the_allowlist_file_not_in_mail_code():
    source = Path("acme/mail.py").read_text()
    assert "acme.example" not in source and "partner.example" not in source
