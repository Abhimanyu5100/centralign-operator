"""Reset, state hash and the logical clock (risks N.12, N.17, N.20, N.25, N.29; register 0.3)."""

import re
from pathlib import Path

import pytest

from acme import clock, services
from acme.db import connect
from acme.models import ItTicketIn
from acme.seed import reset, state_hash


def test_two_resets_give_the_same_hash(tmp_path):
    first = reset(connect(tmp_path / "a.db"), "base")
    second = reset(connect(tmp_path / "b.db"), "base")
    assert first == second


@pytest.mark.parametrize("seed", ["base", "t8", "t9"])
def test_reset_over_a_used_database_restores_the_seed(tmp_path, seed):
    conn = connect(tmp_path / "acme.db")
    clean = reset(conn, seed)
    services.create_it_ticket(conn, "ops-agent", "api", ItTicketIn(type="laptop", employee_id=5))
    assert state_hash(conn) != clean
    assert reset(conn, seed) == clean


def test_different_now_or_seed_changes_the_hash(make_conn):
    base = state_hash(make_conn("base"))
    assert state_hash(make_conn("base", "2026-10-08T10:30:00+05:30")) != base
    assert state_hash(make_conn("t9")) != base


def test_reset_rejects_unknown_seed_and_non_ist_now(tmp_path):
    conn = connect(tmp_path / "acme.db")
    with pytest.raises(ValueError, match="unknown seed"):
        reset(conn, "t99")
    with pytest.raises(ValueError, match=r"\+05:30"):
        reset(conn, "base", "2026-10-07T10:30:00+00:00")


def test_acme_never_reads_the_wall_clock():
    """N.12/N.17: only the logical clock may supply dates and times."""
    pattern = re.compile(r"datetime\.now|date\.today|time\.time\(|utcnow|localtime")
    offenders = [
        str(path) for path in Path("acme").rglob("*.py") if pattern.search(path.read_text())
    ]
    assert offenders == []


@pytest.mark.parametrize("seed", ["base", "t8", "t9"])
def test_clock_starts_at_frozen_now_after_any_seed(make_conn, seed):
    conn = make_conn(seed)
    assert clock.now(conn) == clock.DEFAULT_NOW


def test_each_write_is_stamped_then_ticks_one_second(conn):
    first = services.create_it_ticket(conn, "ops-agent", "api", ItTicketIn(type="laptop", employee_id=5))
    second = services.create_it_ticket(conn, "ops-agent", "api", ItTicketIn(type="accounts", employee_id=5))
    stamps = [r["ts"] for r in conn.execute(
        "SELECT ts FROM audit_log WHERE entity_type = 'it_ticket' AND entity_id IN (?, ?) ORDER BY id",
        (first["id"], second["id"]))]
    assert stamps == ["2026-10-07T10:30:00+05:30", "2026-10-07T10:30:01+05:30"]
    assert clock.now(conn) == "2026-10-07T10:30:02+05:30"


def test_failed_write_does_not_tick_or_audit(conn):
    audit_before = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    with pytest.raises(services.NotFound):
        services.create_it_ticket(conn, "ops-agent", "api", ItTicketIn(type="laptop", employee_id=999))
    assert clock.now(conn) == clock.DEFAULT_NOW
    assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == audit_before


def test_base_seed_has_no_audit_rows_and_overlays_do(make_conn):
    """Base rows are the pre-existing world; overlays go through the service layer (N.29)."""
    assert make_conn("base").execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0
    actions = [r["action"] for r in make_conn("t9").execute("SELECT action FROM audit_log ORDER BY id")]
    assert actions == ["invoice.submit", "approval.request"]


def test_t9_seed_is_t1_end_state(make_conn):
    conn = make_conn("t9")
    invoice = conn.execute("SELECT * FROM invoices WHERE invoice_no = 'INV-1043'").fetchone()
    assert (invoice["status"], invoice["amount_paise"], invoice["vendor_id"]) == ("pending_approval", 6_240_000, 1)
    assert invoice["created_by"] == "ops-agent"
    pending = conn.execute(
        "SELECT * FROM approvals WHERE entity_type = 'invoice' AND entity_id = ? AND status = 'pending'",
        (invoice["id"],)).fetchall()
    assert len(pending) == 1 and pending[0]["approver_role"] == "finance_manager"
    # Overlay writes happened the day before the frozen now.
    assert conn.execute("SELECT MIN(ts) FROM audit_log").fetchone()[0] == "2026-10-06T16:00:00+05:30"


def test_t8_seed_has_inv1043_approved_without_payment(make_conn):
    conn = make_conn("t8")
    invoice = conn.execute("SELECT * FROM invoices WHERE invoice_no = 'INV-1043'").fetchone()
    assert invoice["status"] == "approved"
    assert conn.execute("SELECT COUNT(*) FROM payments WHERE invoice_id = ?", (invoice["id"],)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM approvals WHERE status = 'pending'").fetchone()[0] == 0


def test_t4_near_duplicates_present_in_every_seed(make_conn):
    for seed in ("base", "t8", "t9"):
        rows = make_conn(seed).execute(
            "SELECT invoice_no, amount_paise, invoice_date, status FROM invoices WHERE vendor_id = 3 ORDER BY id"
        ).fetchall()
        assert [tuple(r) for r in rows] == [
            ("INV-778", 3_675_000, "2026-09-24", "approved"),
            ("INV-778A", 3_675_000, "2026-09-25", "approved"),
        ]


def test_no_vendor_resembles_kapoor_steel(conn):
    """T5 needs Kapoor Steel to be absent, not hidden behind a near-name."""
    names = [r["name"].lower() for r in conn.execute("SELECT name FROM vendors")]
    assert not any("kapoor" in n or "kapur" in n or "steel" in n for n in names)


def test_reset_while_another_connection_is_open(tmp_path):
    """N.25: reset happens in-place in one transaction; an open reader sees the new state after it."""
    path = tmp_path / "acme.db"
    reader = connect(path)
    writer = connect(path)
    reset(writer, "base")
    services.create_it_ticket(writer, "ops-agent", "api", ItTicketIn(type="laptop", employee_id=5))
    assert reader.execute("SELECT COUNT(*) FROM it_tickets").fetchone()[0] == 5
    reset(writer, "base")
    assert reader.execute("SELECT COUNT(*) FROM it_tickets").fetchone()[0] == 4
