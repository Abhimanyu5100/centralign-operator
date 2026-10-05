"""SQLite schema, connections and transactions for Acme.

One file, WAL mode, a connection per request, short `BEGIN IMMEDIATE` transactions (risk N.25).
Every entity table has a `version` column bumped by the service layer on each write.
"""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).parent / "data" / "acme.db"

# Entity tables in dependency order. `state_hash` and `/__admin/diff` cover exactly these plus `meta`.
ENTITY_TABLES = ["vendors", "employees", "invoices", "approvals", "payments", "it_tickets", "mail", "audit_log"]

SCHEMA = [
    """CREATE TABLE meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
    """CREATE TABLE vendors (
        id                  INTEGER PRIMARY KEY,
        name                TEXT NOT NULL UNIQUE,
        gstin               TEXT NOT NULL UNIQUE,
        status              TEXT NOT NULL CHECK (status IN ('approved', 'pending', 'blocked')),
        email_domain        TEXT NOT NULL,
        contact_email       TEXT NOT NULL,
        bank_account_masked TEXT NOT NULL,
        version             INTEGER NOT NULL DEFAULT 1
    )""",
    """CREATE TABLE employees (
        id          INTEGER PRIMARY KEY,
        name        TEXT NOT NULL,
        email       TEXT NOT NULL,
        role        TEXT NOT NULL,
        department  TEXT NOT NULL,
        manager_id  INTEGER REFERENCES employees(id),
        start_date  TEXT NOT NULL,
        status      TEXT NOT NULL CHECK (status IN ('onboarding', 'active', 'cancelled')),
        version     INTEGER NOT NULL DEFAULT 1
    )""",
    """CREATE TABLE invoices (
        id            INTEGER PRIMARY KEY,
        vendor_id     INTEGER NOT NULL REFERENCES vendors(id),
        invoice_no    TEXT NOT NULL,
        po_number     TEXT,
        invoice_date  TEXT NOT NULL,
        received_date TEXT NOT NULL,
        due_date      TEXT NOT NULL,
        amount_paise  INTEGER NOT NULL CHECK (amount_paise > 0),
        tax_paise     INTEGER NOT NULL CHECK (tax_paise >= 0),
        status        TEXT NOT NULL CHECK (status IN
                        ('draft', 'pending_approval', 'approved', 'rejected', 'paid', 'void')),
        source_file   TEXT,
        created_by    TEXT NOT NULL,
        channel       TEXT NOT NULL CHECK (channel IN ('ui', 'api')),
        version       INTEGER NOT NULL DEFAULT 1
    )""",
    """CREATE TABLE approvals (
        id            INTEGER PRIMARY KEY,
        entity_type   TEXT NOT NULL CHECK (entity_type IN ('invoice', 'payment')),
        entity_id     INTEGER NOT NULL,
        requested_by  TEXT NOT NULL,
        approver_role TEXT NOT NULL,
        status        TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'withdrawn')),
        reason        TEXT,
        decided_by    TEXT,
        decided_at    TEXT,
        version       INTEGER NOT NULL DEFAULT 1
    )""",
    """CREATE TABLE payments (
        id             INTEGER PRIMARY KEY,
        invoice_id     INTEGER NOT NULL REFERENCES invoices(id),
        amount_paise   INTEGER NOT NULL CHECK (amount_paise > 0),
        scheduled_date TEXT NOT NULL,
        status         TEXT NOT NULL CHECK (status IN
                         ('pending_approval', 'scheduled', 'rejected', 'cancelled', 'sent')),
        created_by     TEXT NOT NULL,
        version        INTEGER NOT NULL DEFAULT 1
    )""",
    """CREATE TABLE it_tickets (
        id          INTEGER PRIMARY KEY,
        type        TEXT NOT NULL CHECK (type IN ('laptop', 'accounts')),
        employee_id INTEGER NOT NULL REFERENCES employees(id),
        status      TEXT NOT NULL CHECK (status IN ('open', 'done', 'cancelled')),
        created_by  TEXT NOT NULL,
        version     INTEGER NOT NULL DEFAULT 1
    )""",
    """CREATE TABLE mail (
        id               INTEGER PRIMARY KEY,
        folder           TEXT NOT NULL CHECK (folder IN ('inbox', 'outbox')),
        from_addr        TEXT NOT NULL,
        to_addr          TEXT NOT NULL,
        subject          TEXT NOT NULL,
        body             TEXT NOT NULL,
        ts               TEXT NOT NULL,
        attachments_json TEXT NOT NULL DEFAULT '[]',
        external         INTEGER NOT NULL DEFAULT 0 CHECK (external IN (0, 1)),
        created_by       TEXT NOT NULL
    )""",
    """CREATE TABLE audit_log (
        id          INTEGER PRIMARY KEY,
        ts          TEXT NOT NULL,
        actor       TEXT NOT NULL,
        channel     TEXT NOT NULL,
        action      TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id   INTEGER NOT NULL,
        before_json TEXT,
        after_json  TEXT,
        reason      TEXT
    )""",
]


def db_path() -> Path:
    return Path(os.environ.get("ACME_DB", DEFAULT_DB_PATH))


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open a connection in autocommit mode; callers group writes with `transaction()`."""
    path = Path(path) if path is not None else db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """One short write transaction; rolls back everything (including audit rows) on any exception.

    Nested use joins the outer transaction (reset runs seed overlays through the service layer).
    """
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def create_schema(conn: sqlite3.Connection) -> None:
    """Drop and recreate every table. Must run inside a transaction (see `seed.reset`)."""
    for table in reversed(["meta", *ENTITY_TABLES]):
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    for statement in SCHEMA:
        conn.execute(statement)


def row_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None
