"""Run store (agent/store.py): its own SQLite file, append-only by triggers. Risks P.10, N.120, 3.9 (D-085)."""

import sqlite3
from pathlib import Path

import pytest

from agent.store import DEFAULT_PATH, ROOT, RunStore
from tests.agent.agent_fixtures import NOW


@pytest.fixture
def store(tmp_path):
    s = RunStore(tmp_path / "runs.db")
    yield s
    s.close()


def _raw(store: RunStore) -> sqlite3.Connection:
    return sqlite3.connect(store.path, isolation_level=None)


def _rows(store: RunStore):
    return _raw(store).execute("SELECT * FROM events ORDER BY run_id, seq").fetchall()


def test_seq_counts_from_one_per_run_and_events_come_back_in_order(store):
    a, b = store.start_run("first", NOW), store.start_run("second", NOW)
    assert [store.append(a, "tool_call", NOW.isoformat(), {"n": i}) for i in range(3)] == [1, 2, 3]
    assert store.append(b, "tool_result", NOW.isoformat(), {}) == 1
    assert [(e["seq"], e["payload"]) for e in store.events(a)] == [(1, {"n": 0}), (2, {"n": 1}), (3, {"n": 2})]


def test_run_ids_are_random_and_now_must_be_aware(store):
    assert store.start_run("x", NOW) != store.start_run("x", NOW)
    with pytest.raises(ValueError):
        store.start_run("x", NOW.replace(tzinfo=None))


def test_unknown_event_types_and_unknown_runs_are_refused(store):
    run = store.start_run("x", NOW)
    with pytest.raises(ValueError):
        store.append(run, "note", NOW.isoformat(), {})
    with pytest.raises(sqlite3.IntegrityError):
        store.append("no-such-run", "tool_call", NOW.isoformat(), {})


TAMPERING = {
    "update": "UPDATE events SET payload = '{{}}' WHERE seq = 1",
    "delete": "DELETE FROM events WHERE seq = 1",
    "insert or replace": "INSERT OR REPLACE INTO events VALUES ('{run}', 1, 'tool_result', 't', '{{}}')",
    "replace": "REPLACE INTO events VALUES ('{run}', 2, 'tool_result', 't', '{{}}')",
    "gap in seq": "INSERT INTO events VALUES ('{run}', 5, 'tool_result', 't', '{{}}')",
    "reused seq": "INSERT INTO events VALUES ('{run}', 1, 'tool_result', 't', '{{}}')",
    "update a run": "UPDATE runs SET request = 'other'",
    "delete a run": "DELETE FROM runs",
    "replace a run": "INSERT OR REPLACE INTO runs VALUES ('{run}', 'other', 'now')",
}


@pytest.mark.parametrize("case", TAMPERING)
def test_the_log_refuses_every_change_and_stays_as_it_was(store, case):
    run = store.start_run("x", NOW)
    store.append(run, "tool_call", NOW.isoformat(), {"a": 1})
    store.append(run, "tool_result", NOW.isoformat(), {"b": 2})
    before = (_rows(store), _raw(store).execute("SELECT * FROM runs").fetchall())
    with pytest.raises(sqlite3.IntegrityError):
        _raw(store).execute(TAMPERING[case].format(run=run))
    assert (_rows(store), _raw(store).execute("SELECT * FROM runs").fetchall()) == before


def test_insert_or_ignore_with_a_used_seq_is_refused_too(store):
    # RAISE(ABORT) in a trigger ignores the statement's OR clause, so a reused seq fails loudly, not silently
    run = store.start_run("x", NOW)
    store.append(run, "tool_call", NOW.isoformat(), {"a": 1})
    before = _rows(store)
    with pytest.raises(sqlite3.IntegrityError, match="next number"):
        _raw(store).execute(f"INSERT OR IGNORE INTO events VALUES ('{run}', 1, 'tool_result', 't', '{{}}')")
    assert _rows(store) == before


def test_a_fresh_connection_still_has_the_triggers(tmp_path):
    first = RunStore(tmp_path / "runs.db")
    run = first.start_run("x", NOW)
    first.append(run, "tool_call", NOW.isoformat(), {})
    first.close()
    with pytest.raises(sqlite3.IntegrityError):
        sqlite3.connect(tmp_path / "runs.db").execute("DELETE FROM events")


@pytest.mark.parametrize("inside", ["acme/data/runs.db", "acme/acme.db", "acme/data/../data/x.db"])
def test_the_store_refuses_to_live_under_acme(inside):
    with pytest.raises(ValueError, match="never Acme's database"):
        RunStore(ROOT / inside)


def test_the_default_store_is_under_runs_which_git_ignores():
    assert DEFAULT_PATH == ROOT / "runs" / "runs.db"
    assert "runs/" in (ROOT / ".gitignore").read_text().splitlines()


def test_payloads_are_stored_as_sorted_json(store):
    run = store.start_run("x", NOW)
    store.append(run, "tool_call", NOW.isoformat(), {"b": 1, "a": Path("p")})
    (payload,) = _raw(store).execute("SELECT payload FROM events").fetchone()
    assert payload == '{"a": "PosixPath(\'p\')", "b": 1}'
