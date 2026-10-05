"""Admin endpoints for the harness (part 8): reset, snapshot, state hash, diff, chaos.

Every route here is guarded by the token rule in `acme/web.py` (`X-Admin-Token`, never a session) and denied
to the agent by ORG-004. The diff is the harness's independent ground truth for side effects (6.4): row-level
before/after for every entity table since a snapshot, rows in primary-key order, nothing for sessions,
idempotency keys, chaos or snapshots. Bank numbers are masked in the rows themselves (7.6, N.100).
"""

import json
import secrets
import sqlite3

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from acme import chaos, clock, seed as seeding
from acme.api import ok
from acme.db import ENTITY_TABLES, transaction
from acme.services import Invalid, NotFound
from acme.web import get_conn

router = APIRouter(prefix="/__admin")


def _dump(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    return {table: [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY id")] for table in ENTITY_TABLES}


def diff_states(before: dict[str, list[dict]], after: dict[str, list[dict]]) -> dict:
    """Per table: rows added, rows removed, and rows changed (id, before, after), all in id order."""
    tables = {}
    for table in ENTITY_TABLES:
        old = {r["id"]: r for r in before[table]}
        new = {r["id"]: r for r in after[table]}
        added = [new[i] for i in sorted(new.keys() - old.keys())]
        removed = [old[i] for i in sorted(old.keys() - new.keys())]
        changed = [{"id": i, "before": old[i], "after": new[i]} for i in sorted(old.keys() & new.keys())
                   if old[i] != new[i]]
        if added or removed or changed:
            tables[table] = {"added": added, "removed": removed, "changed": changed}
    return tables


@router.post("/reset")
def reset(seed: str = Query("base"), now: str = Query(clock.DEFAULT_NOW),
          conn: sqlite3.Connection = Depends(get_conn)) -> JSONResponse:
    """Rebuild the database for `seed` at the frozen `now`. Drops sessions, snapshots and chaos too."""
    if seed not in seeding.SEEDS:
        raise Invalid(f"unknown seed {seed!r}; known: {', '.join(sorted(seeding.SEEDS))}", "seed")
    try:
        clock.parse_now(now)
    except ValueError as exc:
        raise Invalid(f"now must be an ISO datetime with offset +05:30 (in a URL write the + as %2B): {exc}",
                      "now") from exc
    state_hash = seeding.reset(conn, seed, now)
    return ok({"seed": seed, "now": now, "state_hash": state_hash}, detail="reset")


@router.get("/state_hash")
def state_hash(conn: sqlite3.Connection = Depends(get_conn)) -> JSONResponse:
    return ok({"state_hash": seeding.state_hash(conn), "now": clock.now(conn)})


@router.post("/snapshot")
def snapshot(conn: sqlite3.Connection = Depends(get_conn)) -> JSONResponse:
    with transaction(conn):  # one consistent read of every table
        state, digest, taken_at = _dump(conn), seeding.state_hash(conn), clock.now(conn)
        snapshot_id = secrets.token_hex(8)
        conn.execute("INSERT INTO snapshots (id, taken_at, state_hash, state_json) VALUES (?, ?, ?, ?)",
                     (snapshot_id, taken_at, digest, json.dumps(state, sort_keys=True)))
    return ok({"snapshot": snapshot_id, "state_hash": digest, "now": taken_at}, 201, "snapshot taken")


@router.get("/diff")
def diff(since: str = Query(...), conn: sqlite3.Connection = Depends(get_conn)) -> JSONResponse:
    conn.execute("BEGIN")  # one consistent read: the snapshot row and every table
    try:
        row = conn.execute("SELECT taken_at, state_hash, state_json FROM snapshots WHERE id = ?", (since,)).fetchone()
        if row is None:
            raise NotFound(f"Snapshot {since!r} not found (reset deletes every snapshot)")
        current, digest, now = _dump(conn), seeding.state_hash(conn), clock.now(conn)
    finally:
        conn.execute("COMMIT")
    tables = diff_states(json.loads(row["state_json"]), current)
    return ok({"since": since, "snapshot_now": row["taken_at"], "now": now, "snapshot_state_hash": row["state_hash"],
              "state_hash": digest, "unchanged": not tables, "tables": tables})


@router.get("/chaos")
def get_chaos(conn: sqlite3.Connection = Depends(get_conn)) -> JSONResponse:
    return ok(chaos.state(conn))


@router.post("/chaos")
def set_chaos(profile: str = Query(...), seed: int = Query(0, ge=0, le=2**31 - 1),
              conn: sqlite3.Connection = Depends(get_conn)) -> JSONResponse:
    return ok(chaos.set_profile(conn, profile, seed), detail="chaos set")
