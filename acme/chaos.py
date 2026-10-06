"""Chaos profiles: named, seeded faults injected into Acme (part 8 stores the profile, part 9 the effects).

One active profile at most, stored in the `chaos` table. Three small tables hold all chaos state, all outside
`ENTITY_TABLES` (so never in the state hash or the diff) and all dropped by reset (risks N.18, N.97):
- `chaos`           the active profile and seed, and `set_at_event`: the last event id when it was set;
- `chaos_attempts`  every distinct write attempt seen since the profile was set, numbered 1, 2, 3 ...;
- `chaos_events`    every injected fault, for the harness (`GET /__admin/chaos/events`, risk N.107).

Where the effects enter (one point per channel, no per-route edits; risks N.55, N.102):
- API writes: `api._write` calls `before_write` and `after_write`.
- UI writes: `ChaosRoute`, the route class of `ui.router`, wraps every UI handler and calls the same two.
- Session expiry: `web.require_login` calls `session_step_limit` (every authenticated request passes there).
- The invoice button label: `ui.invoice_submit_label` calls `submit_label`.
Only the operator under test (`ops-agent`) is ever faulted; meera, admin and `/__admin/*` never are (N.104).

Profiles (D-094):
- `rename_submit_button`  the invoice form's button reads "Submit invoice"; behaviour is unchanged.
- `session_expiry_at_step_N`  the first ops-agent session to make an (N+1)th authenticated request is revoked:
  the API gets 401 `session_expired`, the UI a 303 to /login. Once per activation.
- `flaky_500`  30 % of first write attempts fail with a 500 before anything is written (N.19). Which attempts
  fail is a pure function of (profile, seed, attempt number) (N.103); a retry of the same attempt passes.
- `commit_then_timeout`  the first committed IT-ticket creation or approval request (D-008) is held for
  `ACME_CHAOS_TIMEOUT_DELAY_SECONDS` (default 120 s) after the commit, past any sane client timeout.
- `silent_drop_write`  the first UI write is rolled back whole (row, audit row, idempotency record) while the
  redirect and success toast still say it saved; the redirect goes to the section list (N.105).
Day 2.3 profiles (D-116), same insertion points:
- `slow_server`  every committed ops-agent write is held a seeded 1.5-3 s (`ACME_CHAOS_SLOW_SECONDS` x [1, 2)).
- `toast_2s`  ops-agent pages drop their toast and page-level alert `ACME_CHAOS_TOAST_MS` ms after load (ChaosRoute
  sets `request.state.toast_ms`; base.html carries the script).
- `field_moved`  the invoice form shows its fields in a seeded order with the submit button first.
- `delayed_write`  rows inserted by ops-agent writes stay hidden from ops-agent GETs for `ACME_CHAOS_VISIBILITY_SECONDS`
  (`after_write` records them in `chaos_hidden`; `require_login` hides them behind TEMP views on that request's
  connection, so writes, other users and admin calls still see them).
"""

import asyncio
import hashlib
import os
import random
import re
import sqlite3
from collections.abc import Callable, Coroutine
from contextlib import closing
from dataclasses import dataclass, replace
from typing import Any

from fastapi import Request
from fastapi.responses import Response
from fastapi.routing import APIRoute

from acme import auth, clock
from acme.db import DISCARD_COMMITS, ENTITY_TABLES, connect, transaction
from acme.services import AcmeError, Invalid

PROFILES = ("rename_submit_button", "flaky_500", "commit_then_timeout", "silent_drop_write",
            "slow_server", "toast_2s", "field_moved", "delayed_write")
STEP_PROFILE = re.compile(r"session_expiry_at_step_([1-9][0-9]{0,2})")  # N = 1..999 authenticated requests
NONE = "none"
WIRED_PROFILES: frozenset[str] = frozenset(PROFILES)  # session_expiry_at_step_N is wired too (pattern)

TARGET_ACTOR = "ops-agent"
FLAKY_RATE = 0.3
RENAMED_LABEL = "Submit invoice"
DEFAULT_TIMEOUT_DELAY_SECONDS = 120.0
DEFAULT_SLOW_SECONDS, DEFAULT_TOAST_MS, DEFAULT_VISIBILITY_SECONDS = 1.5, 2000, 5.0
WRITE_PROFILES = ("flaky_500", "commit_then_timeout", "silent_drop_write", "slow_server", "delayed_write")
TIMEOUT_ENDPOINTS = frozenset({  # D-008: no idempotency key and no natural uniqueness (register 3.5)
    "api:POST /api/it-tickets", "api:POST /api/approvals",
    "ui:POST /it-tickets/new", "ui:POST /invoices/{invoice_id}/request-approval",
    "ui:POST /payments/{payment_id}/request-approval",
})
UI_NON_WRITES = frozenset({"/logout"})  # UI POSTs that change no company state


class InjectedFault(AcmeError):
    """The `flaky_500` failure. Same status, type and text as a real 500, so a client cannot tell them apart;
    an AcmeError, so the normal handler maps it and Starlette does not re-raise it (N.107)."""
    status_code = 500
    error_type = "server_error"


# --- profile state -------------------------------------------------------------------------------


def validate(profile: str) -> None:
    if profile not in WIRED_PROFILES and not STEP_PROFILE.fullmatch(profile):
        known = ", ".join([*PROFILES, "session_expiry_at_step_<N> (N = 1 to 999)", NONE])
        raise Invalid(f"unknown chaos profile {profile!r}; known: {known}", "profile")


@dataclass(frozen=True)
class Active:
    profile: str
    seed: int
    set_at_event: int  # events with a larger id belong to this activation


def active(conn: sqlite3.Connection) -> Active | None:
    row = conn.execute("SELECT profile, seed, set_at_event FROM chaos WHERE id = 1").fetchone()
    return Active(row["profile"], row["seed"], row["set_at_event"]) if row else None


def state(conn: sqlite3.Connection) -> dict:
    current = active(conn)
    profile, seed = (current.profile, current.seed) if current else (NONE, 0)
    step = STEP_PROFILE.fullmatch(profile)
    return {"profile": profile, "seed": seed, "active": current is not None,
            "params": {"step": int(step.group(1))} if step else {},
            "wired": profile in WIRED_PROFILES or step is not None}


def set_profile(conn: sqlite3.Connection, profile: str, seed: int) -> dict:
    """Setting any profile (or none) restarts the attempt numbering; the event log is kept until reset."""
    if profile != NONE:
        validate(profile)
    with transaction(conn):
        conn.execute("DELETE FROM chaos")
        conn.execute("DELETE FROM chaos_attempts")
        conn.execute("DELETE FROM chaos_hidden")
        if profile != NONE:
            last = conn.execute("SELECT COALESCE(MAX(id), 0) FROM chaos_events").fetchone()[0]
            conn.execute("INSERT INTO chaos (id, profile, seed, set_at_event) VALUES (1, ?, ?, ?)",
                         (profile, seed, last))
    return state(conn)


def fires(profile: str, seed: int, attempt: int, rate: float) -> bool:
    """Deterministic: the same (profile, seed, attempt) always gives the same answer (N.103)."""
    digest = hashlib.sha256(f"{profile}:{seed}:{attempt}".encode()).hexdigest()
    return int(digest[:8], 16) < rate * 16**8


def timeout_delay() -> float:
    return float(os.environ.get("ACME_CHAOS_TIMEOUT_DELAY_SECONDS", DEFAULT_TIMEOUT_DELAY_SECONDS))


def slow_delay(seed: int, attempt: int) -> float:
    """`slow_server`: b + b*u with u in [0, 1) from the same SHA-256 schedule as `fires` (N.103)."""
    base = float(os.environ.get("ACME_CHAOS_SLOW_SECONDS", DEFAULT_SLOW_SECONDS))
    digest = hashlib.sha256(f"slow_server:{seed}:{attempt}".encode()).hexdigest()
    return base + base * int(digest[:8], 16) / 16**8


def visibility_delay() -> float:
    return float(os.environ.get("ACME_CHAOS_VISIBILITY_SECONDS", DEFAULT_VISIBILITY_SECONDS))


# --- event log -----------------------------------------------------------------------------------


def record(conn: sqlite3.Connection, current: Active, effect: str, actor: str, channel: str, method: str,
           path: str, attempt: int | None = None) -> None:
    conn.execute(
        "INSERT INTO chaos_events (profile, seed, effect, actor, channel, method, path, attempt, logical_now)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (current.profile, current.seed, effect, actor, channel, method, path, attempt, clock.now(conn)),
    )


def _fired(conn: sqlite3.Connection, current: Active) -> bool:
    return conn.execute("SELECT 1 FROM chaos_events WHERE id > ? LIMIT 1", (current.set_at_event,)).fetchone() is not None


def events(conn: sqlite3.Connection) -> dict:
    """Every event since reset, plus whether the ACTIVE profile has fired since it was set. AcmeBench uses
    `fired` to mark a chaos run "fault fired: yes/no" (D-095)."""
    current = active(conn)
    items = [dict(r) for r in conn.execute("SELECT * FROM chaos_events ORDER BY id")]
    mine = [e for e in items if current and e["id"] > current.set_at_event]
    return {**state(conn), "fired": bool(mine), "fired_count": len(mine),
            "first_fired_at": mine[0]["logical_now"] if mine else None, "items": items}


# --- hooks ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Attempt:
    """A write the active profile will act on after it runs: `delay` (commit_then_timeout) or `drop`."""
    current: Active
    actor: str
    channel: str
    method: str
    path: str
    number: int
    delay: float = 0.0
    delay_effect: str = "response_delayed"
    drop: bool = False
    audit_mark: int | None = None  # delayed_write: the last audit id before the write; rows inserted after it hide


def _number(conn: sqlite3.Connection, fingerprint: str) -> int | None:
    """The attempt's number if this is its first sight, else None (a retry of the same write)."""
    with transaction(conn):
        if conn.execute("SELECT 1 FROM chaos_attempts WHERE fingerprint = ?", (fingerprint,)).fetchone():
            return None
        number = conn.execute("SELECT COUNT(*) FROM chaos_attempts").fetchone()[0] + 1
        conn.execute("INSERT INTO chaos_attempts (fingerprint, number) VALUES (?, ?)", (fingerprint, number))
        return number


def before_write(conn: sqlite3.Connection, actor: str | None, channel: str, method: str, route: str, path: str,
                 attempt_key: str) -> Attempt | None:
    """Called before a write runs. Raises `InjectedFault` (nothing written yet), or returns an Attempt whose
    effect `after_write` applies once the write has run, or None. `attempt_key` is the Idempotency-Key or a
    hash of the body, so a retry of the same write is recognised (N.19)."""
    current = active(conn)
    if actor != TARGET_ACTOR or current is None or current.profile not in WRITE_PROFILES:
        return None
    fingerprint = hashlib.sha256(f"{actor}|{channel}|{method} {path}|{attempt_key}".encode()).hexdigest()
    number = _number(conn, fingerprint)
    if number is None:
        return None
    if current.profile == "flaky_500":
        if fires(current.profile, current.seed, number, FLAKY_RATE):
            record(conn, current, "server_error", actor, channel, method, path, number)
            raise InjectedFault("Internal server error; nothing was saved. Read back before retrying.")
        return None
    attempt = Attempt(current, actor, channel, method, path, number)
    if current.profile == "slow_server":  # every write, not once
        return replace(attempt, delay=slow_delay(current.seed, number), delay_effect="response_slowed")
    if current.profile == "delayed_write":
        mark = conn.execute("SELECT COALESCE(MAX(id), 0) FROM audit_log").fetchone()[0]
        return replace(attempt, audit_mark=mark)
    if _fired(conn, current):  # commit_then_timeout and silent_drop_write fire once per activation
        return None
    if current.profile == "commit_then_timeout" and f"{channel}:{method} {route}" in TIMEOUT_ENDPOINTS:
        return replace(attempt, delay=timeout_delay())
    if current.profile == "silent_drop_write" and channel == "ui":
        return replace(attempt, drop=True)
    return None


async def after_write(conn: sqlite3.Connection, attempt: Attempt | None, *, committed: bool,
                      dropped: bool = False, wall: float = 0.0) -> None:
    """Record and apply the effect of a write that ran. Only a write that really committed (or really was
    dropped) counts as the fault firing, so a rejected write leaves the fault for the next eligible one."""
    if attempt is None:
        return
    a = attempt
    if a.drop and dropped:
        record(conn, a.current, "write_dropped", a.actor, a.channel, a.method, a.path, a.number)
    elif a.audit_mark is not None and committed:
        hidden = conn.execute("SELECT entity_type, entity_id FROM audit_log WHERE id > ? AND before_json IS NULL",
                              (a.audit_mark,)).fetchall()
        with transaction(conn):
            conn.executemany("INSERT OR REPLACE INTO chaos_hidden (table_name, row_id, visible_at) VALUES (?, ?, ?)",
                             [(_table(r[0]), r[1], wall + visibility_delay()) for r in hidden])
            record(conn, a.current, "write_delayed", a.actor, a.channel, a.method, a.path, a.number)
    elif a.delay and committed:
        record(conn, a.current, a.delay_effect, a.actor, a.channel, a.method, a.path, a.number)
        await asyncio.sleep(a.delay)  # the event loop keeps serving other clients meanwhile (N.106)


def _table(entity_type: str) -> str:
    from acme.services import TABLES  # chaos imports services already; the mapping lives there
    return TABLES[entity_type]


def hide_recent_rows(conn: sqlite3.Connection, actor: str, method: str, wall: float) -> None:
    """`delayed_write`, read side: on an ops-agent GET, shadow each entity table with a TEMP view that leaves out
    rows still inside their visibility delay. TEMP objects live on this connection only (one per request)."""
    current = active(conn)
    if method != "GET" or actor != TARGET_ACTOR or current is None or current.profile != "delayed_write":
        return
    hidden: dict[str, list[int]] = {}
    for table, row_id in conn.execute("SELECT table_name, row_id FROM chaos_hidden WHERE visible_at > ?", (wall,)):
        if table in ENTITY_TABLES:
            hidden.setdefault(table, []).append(int(row_id))
    for table, ids in hidden.items():
        conn.execute(f"CREATE TEMP VIEW {table} AS SELECT * FROM main.{table} "
                     f"WHERE id NOT IN ({','.join(map(str, ids))})")


def toast_ms(conn: sqlite3.Connection, actor: str | None) -> int | None:
    """`toast_2s`: how long an ops-agent page keeps its toast and page-level alert, or None."""
    current = active(conn)
    if actor != TARGET_ACTOR or current is None or current.profile != "toast_2s":
        return None
    return int(os.environ.get("ACME_CHAOS_TOAST_MS", DEFAULT_TOAST_MS))


def invoice_layout(conn: sqlite3.Connection, actor: str | None, fields: list[str]) -> tuple[list[str], bool]:
    """`field_moved`: (field order, submit button first). A seeded permutation, never the default order."""
    current = active(conn)
    if actor != TARGET_ACTOR or current is None or current.profile != "field_moved":
        return fields, False
    order = list(fields)
    random.Random(f"field_moved:{current.seed}").shuffle(order)
    if order == fields:
        order = order[1:] + order[:1]
    record(conn, current, "layout_moved", actor, "ui", "GET", "/invoices/new")
    return order, True


def session_step_limit(conn: sqlite3.Connection, actor: str) -> int | None:
    """N while `session_expiry_at_step_N` is active and has not fired yet, for ops-agent only."""
    current = active(conn)
    step = STEP_PROFILE.fullmatch(current.profile) if current else None
    if actor != TARGET_ACTOR or step is None or _fired(conn, current):
        return None
    return int(step.group(1))


def record_session_expiry(conn: sqlite3.Connection, actor: str, method: str, path: str, count: int) -> None:
    current = active(conn)
    if current is not None:
        record(conn, current, "session_expired", actor, "api" if path.startswith("/api/") else "ui", method, path, count)


def submit_label(conn: sqlite3.Connection, actor: str | None, default: str) -> str:
    current = active(conn)
    if actor != TARGET_ACTOR or current is None or current.profile != "rename_submit_button":
        return default
    record(conn, current, "label_renamed", actor, "ui", "GET", "/invoices/new")
    return RENAMED_LABEL


# --- the one UI insertion point ------------------------------------------------------------------


def _section(location: str) -> str:
    """`/invoices/42` -> `/invoices`: where a dropped write's redirect goes, so no 404 gives it away."""
    return "/" + location.lstrip("/").split("/", 1)[0].split("?", 1)[0]


class ChaosRoute(APIRoute):
    """Route class for `ui.router`: wraps every UI handler (FastAPI's documented per-router hook), so a UI
    route added later gets chaos too. Mirrors what `api._write` does for the API (N.102)."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()
        route = self.path

        async def chaotic(request: Request) -> Response:
            with closing(connect(request.app.state.db_path)) as conn:
                actor = auth.peek_actor(conn, request.cookies.get(auth.COOKIE_NAME), request.app.state.time_fn())
                request.state.toast_ms = toast_ms(conn, actor)  # base.html removes transient messages after it
                if request.method != "POST" or route in UI_NON_WRITES:
                    response = await handler(request)
                    _record_toast(conn, request, actor, response)
                    return response
                request.state.actor = actor  # so an injected 500 page still shows the nav
                body_hash = hashlib.sha256(await request.body()).hexdigest()  # Starlette caches the body
                attempt = before_write(conn, actor, "ui", "POST", route, request.url.path, body_hash)
                discarded: list[bool] = []
                token = DISCARD_COMMITS.set(discarded if attempt and attempt.drop else None)
                try:
                    response = await handler(request)
                finally:
                    DISCARD_COMMITS.reset(token)
                committed = response.status_code == 303  # forms answer a saved write with Post/Redirect/Get
                if discarded:
                    response.headers["location"] = _section(response.headers.get("location", "/"))
                await after_write(conn, attempt, committed=committed and not discarded, dropped=bool(discarded),
                                  wall=request.app.state.time_fn())
                _record_toast(conn, request, actor, response)
            return response

        return chaotic


def _record_toast(conn: sqlite3.Connection, request: Request, actor: str | None, response: Response) -> None:
    """`toast_2s` fired when the served page carries a transient message (toast or page-level alert)."""
    if getattr(request.state, "toast_ms", None) and b"data-transient" in (getattr(response, "body", b"") or b""):
        record(conn, active(conn), "toast_shortened", actor, "ui", request.method, request.url.path)
