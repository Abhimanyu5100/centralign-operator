"""Building the committed cassettes from a live bench (bench/keep_cassettes.py, D-216): the first passing attempt
per row, from that attempt's folder, nothing else; rows that never passed are named; a prune keeps what replayed."""

import json

from bench import keep_cassettes as kc


def row(run_id, attempt, passed, cassettes, chaos="off"):
    return {"run_id": run_id, "chaos": chaos, "attempt": attempt, "passed": passed, "cassettes": cassettes}


def put(folder, key):
    (folder / key[:2]).mkdir(parents=True, exist_ok=True)
    (folder / key[:2] / f"{key}{'0' * 48}.json").write_text(json.dumps({"key": key}))


def test_the_first_passing_attempt_per_row_is_kept_and_a_row_that_never_passed_keeps_its_first(tmp_path, monkeypatch):
    monkeypatch.setattr(kc, "ROOT", tmp_path)
    live, target = tmp_path / "live", tmp_path / "cassettes"
    for attempt, key in ((1, "aa" + "1" * 14), (2, "bb" + "2" * 14), (3, "cc" + "3" * 14), (1, "dd" + "4" * 14)):
        put(live / f"a{attempt}", key)
    put(target, "ee" + "9" * 14)  # an old recording: the folder is emptied first
    rows = [row("T1", 1, False, ["aa" + "1" * 14]), row("T1", 2, True, ["bb" + "2" * 14]),
            row("T1", 3, True, ["cc" + "3" * 14]), row("T1", 1, True, ["dd" + "4" * 14], chaos="flaky_500:0"),
            row("T2", 1, False, []), row("T2", 2, False, [])]
    missing = kc.keep([{"meta": {"cassettes": "live", "k": 3}, "rows": rows}], target)
    assert missing == ["T2 off"]
    assert sorted(p.name[:16] for p in target.glob("*/*.json")) == ["bb" + "2" * 14, "dd" + "4" * 14]  # T2: no files
    assert kc.prune({"rows": [row("T1", 1, True, ["bb" + "2" * 14])]}, target) == 1
    assert [p.name[:16] for p in target.glob("*/*.json")] == ["bb" + "2" * 14]


def test_a_later_results_file_replaces_the_rows_of_a_re_measured_task(tmp_path, monkeypatch):
    monkeypatch.setattr(kc, "ROOT", tmp_path)
    put(tmp_path / "old" / "a1", "aa" + "1" * 14)
    put(tmp_path / "old" / "a1", "bb" + "2" * 14)
    put(tmp_path / "new" / "a2", "cc" + "3" * 14)
    old = {"meta": {"cassettes": "old", "k": 3}, "rows": [row("T1", 1, True, ["aa" + "1" * 14]),
                                                          row("T3", 1, True, ["bb" + "2" * 14])]}
    new = {"meta": {"cassettes": "new", "k": 3}, "rows": [row("T3", 1, False, []), row("T3", 2, True, ["cc" + "3" * 14])]}
    target = tmp_path / "cassettes"
    assert kc.keep([old, new], target) == []
    assert sorted(p.name[:16] for p in target.glob("*/*.json")) == ["aa" + "1" * 14, "cc" + "3" * 14]
