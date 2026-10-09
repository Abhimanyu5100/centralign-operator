"""Record/replay cassettes (X.1, M.6). Key: the role, the request body and the frozen `now`; never the provider or
model, so a replay does not depend on an evaluator's keys (D-165). A file holds the request, the reply and who
answered; never a key or a header."""

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def cassette_key(role: str, body: dict[str, Any], now: str, scope: str = "") -> str:
    """`scope`: a scenario name the harness sets for a run that must not share replies with the plain task (a chaos
    run, D-209); empty keeps the plain key."""
    key = {"role": role, "now": now, "body": body, **({"scope": scope} if scope else {})}
    text = json.dumps(key, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()


def load(folder: Path, key: str) -> dict[str, Any] | None:
    path = folder / key[:2] / f"{key}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def save(folder: Path, key: str, role: str, body: dict[str, Any], reply: dict[str, Any]) -> None:
    path = folder / key[:2] / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")  # written whole, then renamed: a crash never leaves half a cassette
    temp.write_text(json.dumps({"role": role, "request": body, "reply": reply}, indent=1, ensure_ascii=False),
                    encoding="utf-8")
    os.replace(temp, path)
