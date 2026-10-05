"""Chaos profile registry and state (part 8; the effects are wired into `_write` in part 9).

One active profile at most, stored in the `chaos` table: outside `ENTITY_TABLES`, so setting it never changes
the state hash or the diff, and dropped by reset so a profile cannot outlive its run (risk N.97).
`WIRED_PROFILES` lists the profiles whose effect exists; part 9 adds the names as it builds them, so a harness
can see that a profile it set does nothing yet (risk N.98).
"""

import re
import sqlite3

from acme.db import transaction
from acme.services import Invalid

PROFILES = ("rename_submit_button", "flaky_500", "commit_then_timeout", "silent_drop_write")
STEP_PROFILE = re.compile(r"session_expiry_at_step_([1-9][0-9]{0,2})")  # N = 1..999 authenticated requests
NONE = "none"
WIRED_PROFILES: frozenset[str] = frozenset()


def validate(profile: str) -> None:
    if profile not in PROFILES and not STEP_PROFILE.fullmatch(profile):
        known = ", ".join([*PROFILES, "session_expiry_at_step_<N> (N = 1 to 999)", NONE])
        raise Invalid(f"unknown chaos profile {profile!r}; known: {known}", "profile")


def state(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT profile, seed FROM chaos WHERE id = 1").fetchone()
    profile, seed = (row["profile"], row["seed"]) if row else (NONE, 0)
    step = STEP_PROFILE.fullmatch(profile)
    return {"profile": profile, "seed": seed, "active": row is not None,
            "params": {"step": int(step.group(1))} if step else {},
            "wired": profile in WIRED_PROFILES}


def set_profile(conn: sqlite3.Connection, profile: str, seed: int) -> dict:
    if profile != NONE:
        validate(profile)
    with transaction(conn):
        conn.execute("DELETE FROM chaos")
        if profile != NONE:
            conn.execute("INSERT INTO chaos (id, profile, seed) VALUES (1, ?, ?)", (profile, seed))
    return state(conn)
