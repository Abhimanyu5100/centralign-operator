"""No API key value is ever written to disk by the agent (register P.7, R.7; Day 4 change 5): every file under
`cassettes/` and `runs/` is read as bytes and searched for the configured key values. Skipped when no key is
configured (an evaluator's clone), so it runs for real on the author's machine after live runs."""

from pathlib import Path

import pytest

from agent.config import ROOT, load_config

KEY_NAMES = ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY")


def key_leaks(keys: list[str], folders: list[Path]) -> list[str]:
    found = []
    for folder in folders:
        for path in (p for p in folder.rglob("*") if p.is_file()) if folder.is_dir() else []:
            data = path.read_bytes()
            found += [f"{path.relative_to(folder.parent)}: {name}" for name, key in keys if key.encode() in data]
    return found


def test_no_configured_key_is_in_cassettes_or_runs():
    config = load_config()
    keys = [(name, config[name]) for name in KEY_NAMES if len(config.get(name, "")) >= 8]
    if not keys:
        pytest.skip("no API key configured")
    assert key_leaks(keys, [ROOT / "cassettes", ROOT / "runs"]) == []


def test_a_planted_key_is_found(tmp_path):
    (tmp_path / "runs" / "r1").mkdir(parents=True)
    (tmp_path / "runs" / "r1" / "events.bin").write_bytes(b"\x00header Bearer sk-planted-123456\x00")
    assert key_leaks([("GROQ_API_KEY", "sk-planted-123456")], [tmp_path / "cassettes", tmp_path / "runs"]) == [
        "runs/r1/events.bin: GROQ_API_KEY"]
