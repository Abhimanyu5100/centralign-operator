"""The shared idempotency store (risks N.27, N.45, 3.5; Part 4 reuses it for `Idempotency-Key`)."""

import pytest

from acme import idempotency as idem, services as s
from acme.idempotency import KeyReused
from acme.seed import reset, state_hash
from tests.acme.test_services import invoice_in


def count(conn, table="invoices"):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def submit_once(conn, key="k1", actor="ops-agent", endpoint="api:POST /api/invoices", data=None):
    data = data or invoice_in()
    return idem.run(conn, actor, endpoint, key, data, lambda: s.submit_invoice(conn, actor, "api", data))


def test_same_key_and_data_replays_the_first_response_and_writes_once(conn):
    before = count(conn)
    first, replayed_first = submit_once(conn)
    second, replayed_second = submit_once(conn)
    assert (replayed_first, replayed_second) == (False, True)
    assert second == first
    assert count(conn) == before + 1


def test_replay_adds_no_audit_rows_and_does_not_tick_the_clock(conn):
    submit_once(conn)
    audit_rows, now = count(conn, "audit_log"), conn.execute("SELECT value FROM meta WHERE key='now'").fetchone()[0]
    submit_once(conn)
    assert count(conn, "audit_log") == audit_rows
    assert conn.execute("SELECT value FROM meta WHERE key='now'").fetchone()[0] == now


def test_same_key_with_different_data_is_a_conflict_not_a_second_write(conn):
    submit_once(conn)
    before = count(conn)
    with pytest.raises(KeyReused) as exc:
        submit_once(conn, data=invoice_in(invoice_no="INV-2211"))
    assert exc.value.status_code == 409 and exc.value.field == "idempotency_key"
    assert count(conn) == before


def test_a_ui_token_and_an_api_key_with_the_same_text_never_collide(conn):
    api, _ = submit_once(conn, key="abc", endpoint="api:POST /api/invoices")
    ui, replayed = submit_once(conn, key="abc", endpoint="ui:POST /invoices/new",
                               data=invoice_in(invoice_no="INV-2211"))
    assert replayed is False and ui["id"] != api["id"]


def test_keys_are_scoped_by_user(conn):
    first, _ = submit_once(conn, key="abc", actor="ops-agent")
    other, replayed = submit_once(conn, key="abc", actor="admin", data=invoice_in(invoice_no="INV-2212"))
    assert replayed is False and other["id"] != first["id"]
    assert other["created_by"] == "admin"


def test_a_failed_write_does_not_store_the_key_so_a_corrected_retry_with_the_same_key_works(conn):
    bad = invoice_in(due_date="2026-09-01")  # before the invoice date
    with pytest.raises(s.Invalid):
        submit_once(conn, key="retry", data=bad)
    assert count(conn, "idempotency_keys") == 0
    row, replayed = submit_once(conn, key="retry")
    assert replayed is False and row["invoice_no"] == "INV-2210"


def test_reset_clears_the_store_so_a_key_cannot_replay_an_earlier_run(conn):
    first, _ = submit_once(conn, key="same")
    assert count(conn, "idempotency_keys") == 1
    reset(conn, "base")
    assert count(conn, "idempotency_keys") == 0
    again, replayed = submit_once(conn, key="same")
    assert replayed is False and again["id"] == first["id"]  # a fresh write: ids restart after reset


def test_the_store_is_outside_the_state_hash(conn):
    before = state_hash(conn)
    idem.run(conn, "ops-agent", "api:POST /noop", "k", {"a": 1}, lambda: {"ok": True})  # writes nothing else
    assert count(conn, "idempotency_keys") == 1
    assert state_hash(conn) == before


@pytest.mark.parametrize("key", ["", "k" * 201])
def test_key_length_is_validated(conn, key):
    with pytest.raises(s.Invalid) as exc:
        submit_once(conn, key=key)
    assert exc.value.field == "idempotency_key"


def test_two_connections_with_the_same_key_write_once(tmp_path):
    from acme.db import connect
    path = tmp_path / "a.db"
    a, b = connect(path), connect(path)
    reset(a, "base")
    _, first = submit_once(a, key="race")
    _, second = submit_once(b, key="race")
    assert (first, second) == (False, True)
    assert count(a) == count(b)
