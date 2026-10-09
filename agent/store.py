"""Run store: the operator's own SQLite file (default runs/runs.db, gitignored), never Acme's database.

`runs` holds one immutable row per run; `events` is the append-only log of everything a run did. SQLite
triggers refuse UPDATE and DELETE on both tables, and refuse an event whose `seq` is not the next number for
its run, which also blocks `INSERT OR REPLACE` and gaps (N.120). The triggers guard against code bugs, not
against someone who can edit the file. Writes are short and synchronous; a run writes a few events per call.
"""

import json
import secrets
import sqlite3
from pathlib import Path
from typing import Any

from pydantic import AwareDatetime, TypeAdapter

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "runs" / "runs.db"
EVENT_TYPES = ("tool_call", "precondition", "policy_decision", "tool_result",
               "approval", "security_finding", "run_start", "verifier_result",  # Day 3 (D-131)
               "llm_call", "goal", "plan", "agent_message", "executor_stop",      # Day 4
               "prediction", "rollback", "escalation")                            # Day 5

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, request TEXT NOT NULL, now TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
    run_id TEXT NOT NULL REFERENCES runs(run_id), seq INTEGER NOT NULL, type TEXT NOT NULL,
    logical_time TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (run_id, seq));
CREATE TRIGGER IF NOT EXISTS runs_no_update BEFORE UPDATE ON runs
    BEGIN SELECT RAISE(ABORT, 'runs are append-only'); END;
CREATE TRIGGER IF NOT EXISTS runs_no_delete BEFORE DELETE ON runs
    BEGIN SELECT RAISE(ABORT, 'runs are append-only'); END;
CREATE TRIGGER IF NOT EXISTS runs_no_replace BEFORE INSERT ON runs
    WHEN EXISTS (SELECT 1 FROM runs WHERE run_id = NEW.run_id)
    BEGIN SELECT RAISE(ABORT, 'run id already exists'); END;
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
    BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
    BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_next_seq BEFORE INSERT ON events
    WHEN NEW.seq IS NOT (SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE run_id = NEW.run_id)
    BEGIN SELECT RAISE(ABORT, 'seq must be the next number for this run'); END;
"""


class RunStore:
    def __init__(self, path: Path | str = DEFAULT_PATH):
        path = Path(path).resolve()
        if (ROOT / "acme").resolve() in path.parents:
            raise ValueError(f"the run store must not live under acme/ ({path}); it is never Acme's database")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._db = sqlite3.connect(path, isolation_level=None)  # autocommit; we open transactions ourselves
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._db.execute("PRAGMA foreign_keys=ON")  # an event for an unknown run is refused
        self._db.executescript(_SCHEMA)

    def start_run(self, request: str, now: AwareDatetime) -> str:
        """New run with a random id (never derived from the wall clock); `now` is the run's frozen time."""
        now = TypeAdapter(AwareDatetime).validate_python(now)
        run_id = secrets.token_hex(8)
        self._db.execute("INSERT INTO runs (run_id, request, now) VALUES (?, ?, ?)", (run_id, request, now.isoformat()))
        return run_id

    def append(self, run_id: str, type: str, logical_time: str, payload: dict[str, Any]) -> int:
        if type not in EVENT_TYPES:
            raise ValueError(f"unknown event type {type!r}")
        body = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=repr)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            (seq,) = self._db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE run_id = ?",
                                      (run_id,)).fetchone()
            self._db.execute("INSERT INTO events (run_id, seq, type, logical_time, payload) VALUES (?, ?, ?, ?, ?)",
                             (run_id, seq, type, logical_time, body))
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        return seq

    def run(self, run_id: str) -> dict[str, str]:
        row = self._db.execute("SELECT request, now FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"no run {run_id!r}")
        return {"run_id": run_id, "request": row[0], "now": row[1]}

    def events_of_type(self, type: str) -> list[dict[str, Any]]:
        """Every event of one type across all runs, in run and seq order (the approval inbox lists them)."""
        rows = self._db.execute("SELECT run_id, seq, payload FROM events WHERE type = ? ORDER BY run_id, seq",
                                (type,)).fetchall()
        return [{"run_id": r, "seq": s, "payload": json.loads(p)} for r, s, p in rows]

    def events(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._db.execute("SELECT seq, type, logical_time, payload FROM events WHERE run_id = ? ORDER BY seq",
                                (run_id,)).fetchall()
        return [{"seq": s, "type": t, "logical_time": lt, "payload": json.loads(p)} for s, t, lt, p in rows]

    def close(self) -> None:
        self._db.close()
