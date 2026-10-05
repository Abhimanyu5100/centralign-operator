"""Idempotency store shared by the API (`Idempotency-Key` header) and the UI forms (hidden token).

Risks N.27, N.45, 3.5. A record is keyed by (actor, endpoint, key): the endpoint string carries the
channel ("ui:POST /invoices/new" vs "api:POST /api/invoices"), so a UI token and an API key can never
collide, and one user's key never replays another user's response.

`run` does the lookup, the write and the record in ONE transaction (BEGIN IMMEDIATE), so two concurrent
posts with the same key serialise: the second sees the record and replays. A write that raises is
rolled back with its key, so the caller can fix the input and retry with the same key.

The table is outside `ENTITY_TABLES` (not in the state hash or diff, like sessions) and is dropped by
reset, so a replayed key can never return a response from a previous run.
"""

import hashlib
import json
import sqlite3
from collections.abc import Callable

from pydantic import BaseModel

from acme import clock
from acme.db import transaction
from acme.services import Conflict, Invalid

MAX_KEY_LENGTH = 200


class KeyReused(Conflict):
    """The same key arrived with different data (a client bug, not a retry)."""


def fingerprint(request: BaseModel | dict) -> str:
    data = request.model_dump(mode="json") if isinstance(request, BaseModel) else request
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def run(conn: sqlite3.Connection, actor: str, endpoint: str, key: str, request: BaseModel | dict,
        write: Callable[[], dict]) -> tuple[dict, bool]:
    """Returns (response, replayed). `write` performs the service call and returns its result row."""
    if not 1 <= len(key) <= MAX_KEY_LENGTH:
        raise Invalid(f"Idempotency key must be 1 to {MAX_KEY_LENGTH} characters", "idempotency_key")
    request_hash = fingerprint(request)
    with transaction(conn):
        stored = conn.execute(
            "SELECT request_hash, response_json FROM idempotency_keys WHERE actor = ? AND endpoint = ? AND key = ?",
            (actor, endpoint, key),
        ).fetchone()
        if stored is not None:
            if stored["request_hash"] != request_hash:
                raise KeyReused("This idempotency key was already used with different data; use a new key", "idempotency_key")
            return json.loads(stored["response_json"]), True
        response = write()
        conn.execute(
            "INSERT INTO idempotency_keys (actor, endpoint, key, request_hash, response_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (actor, endpoint, key, request_hash, json.dumps(response, sort_keys=True), clock.now(conn)),
        )
        return response, False
