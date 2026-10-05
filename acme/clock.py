"""Acme's logical clock (decision D-035).

Reset sets the clock to the task's frozen `now`. Every successful write is stamped with the current
clock value and then advances it by exactly one second. Nothing in Acme reads the wall clock, so the
same sequence of writes always produces the same timestamps (risks N.12, N.17, N.20).
"""

import sqlite3
from datetime import date, datetime, timedelta

IST_OFFSET = "+05:30"
DEFAULT_NOW = "2026-10-07T10:30:00+05:30"


def parse_now(value: str) -> datetime:
    """Accept only an ISO datetime in IST, e.g. 2026-10-07T10:30:00+05:30."""
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() != timedelta(hours=5, minutes=30):
        raise ValueError(f"now must be an ISO datetime with offset {IST_OFFSET}: {value!r}")
    return parsed


def set_now(conn: sqlite3.Connection, value: str) -> None:
    parse_now(value)
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('now', ?)", (value,))


def now(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = 'now'").fetchone()
    if row is None:
        raise RuntimeError("Acme clock is not set; run a reset first")
    return row["value"]


def today(conn: sqlite3.Connection) -> date:
    return parse_now(now(conn)).date()


def tick(conn: sqlite3.Connection) -> str:
    """Return the timestamp for this write and advance the clock by one second.

    Call inside the write's transaction, so a rolled-back write does not advance the clock.
    """
    current = now(conn)
    set_now(conn, (parse_now(current) + timedelta(seconds=1)).isoformat())
    return current
