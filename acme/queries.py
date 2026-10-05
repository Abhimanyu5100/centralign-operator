"""Read-only queries shared by the UI pages and (part 4) the read API. No writes, no audit, no clock tick.

Rows are plain dicts, newest id first except where a natural order is stated. Vendor bank details are
already masked in the table, so nothing here can leak a full account number (register 7.6).
"""

import json
import sqlite3

from acme.services import BadRequest

INVOICE_STATUSES = ["draft", "pending_approval", "approved", "rejected", "paid", "void"]
APPROVAL_STATUSES = ["pending", "approved", "rejected", "withdrawn"]
PAYMENT_STATUSES = ["pending_approval", "scheduled", "rejected", "cancelled", "sent"]
EMPLOYEE_STATUSES = ["onboarding", "active", "cancelled"]
TICKET_STATUSES = ["open", "done", "cancelled"]


def valid_status(value: str | None, options: list[str]) -> str | None:
    """Shared by UI and API filters, so both reject an unknown status with the same message (N.21)."""
    if not value:
        return None
    if value not in options:
        raise BadRequest(f"Unknown status {value!r}. Use one of: {', '.join(options)}", "status")
    return value


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params)]


def list_vendors(conn: sqlite3.Connection, q: str | None = None) -> list[dict]:
    if q:
        return _rows(conn, "SELECT * FROM vendors WHERE name LIKE ? ESCAPE '\\' ORDER BY name",
                     (f"%{_like(q)}%",))
    return _rows(conn, "SELECT * FROM vendors ORDER BY name")


def list_invoices(conn: sqlite3.Connection, vendor_id: int | None = None, status: str | None = None) -> list[dict]:
    where, params = [], []
    if vendor_id is not None:
        where.append("i.vendor_id = ?")
        params.append(vendor_id)
    if status:
        where.append("i.status = ?")
        params.append(status)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    return _rows(conn, f"SELECT i.*, v.name AS vendor_name FROM invoices i JOIN vendors v ON v.id = i.vendor_id "
                       f"{clause} ORDER BY i.id DESC", tuple(params))


def list_approvals(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    where, params = ("WHERE status = ?", (status,)) if status else ("", ())
    rows = _rows(conn, f"SELECT * FROM approvals {where} ORDER BY id DESC", params)
    for row in rows:
        row["entity_label"] = entity_label(conn, row["entity_type"], row["entity_id"])
    return rows


def list_payments(conn: sqlite3.Connection, invoice_id: int | None = None, status: str | None = None) -> list[dict]:
    where, params = [], []
    if invoice_id is not None:
        where.append("p.invoice_id = ?")
        params.append(invoice_id)
    if status:
        where.append("p.status = ?")
        params.append(status)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    return _rows(conn, f"SELECT p.*, i.invoice_no, v.name AS vendor_name FROM payments p "
                       f"JOIN invoices i ON i.id = p.invoice_id JOIN vendors v ON v.id = i.vendor_id "
                       f"{clause} ORDER BY p.id DESC", tuple(params))


def list_employees(conn: sqlite3.Connection, q: str | None = None) -> list[dict]:
    if q:
        return _rows(conn, "SELECT * FROM employees WHERE name LIKE ? ESCAPE '\\' ORDER BY name",
                     (f"%{_like(q)}%",))
    return _rows(conn, "SELECT * FROM employees ORDER BY name")


def list_it_tickets(conn: sqlite3.Connection, employee_id: int | None = None) -> list[dict]:
    where, params = ("WHERE t.employee_id = ?", (employee_id,)) if employee_id is not None else ("", ())
    return _rows(conn, f"SELECT t.*, e.name AS employee_name FROM it_tickets t "
                       f"JOIN employees e ON e.id = t.employee_id {where} ORDER BY t.id DESC", params)


def approvals_for(conn: sqlite3.Connection, entity_type: str, entity_id: int) -> list[dict]:
    return _rows(conn, "SELECT * FROM approvals WHERE entity_type = ? AND entity_id = ? ORDER BY id",
                 (entity_type, entity_id))


def entity_label(conn: sqlite3.Connection, entity_type: str, entity_id: int) -> str:
    """Human label such as 'invoice INV-1043 (Sharma Logistics Pvt Ltd)' or 'payment 3 for INV-778'."""
    if entity_type == "invoice":
        row = conn.execute("SELECT i.id, i.invoice_no, v.name FROM invoices i JOIN vendors v ON v.id = i.vendor_id "
                           "WHERE i.id = ?", (entity_id,)).fetchone()
        return f"invoice {row['invoice_no']} ({row['name']}) #{row['id']}" if row else f"invoice #{entity_id}"
    row = conn.execute("SELECT p.id, i.invoice_no FROM payments p JOIN invoices i ON i.id = p.invoice_id "
                       "WHERE p.id = ?", (entity_id,)).fetchone()
    return f"payment #{row['id']} for {row['invoice_no']}" if row else f"payment #{entity_id}"


def audit_since(conn: sqlite3.Connection, since: int, limit: int) -> list[dict]:
    """Audit rows with id > since, in id order (never by timestamp: N.20), all actors. Bank fields in
    before/after were masked when the row was written (register 7.6)."""
    rows = _rows(conn, "SELECT * FROM audit_log WHERE id > ? ORDER BY id LIMIT ?", (since, limit))
    for row in rows:
        for column, key in (("before_json", "before"), ("after_json", "after")):
            raw = row.pop(column)
            row[key] = json.loads(raw) if raw is not None else None
    return rows


def _like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
