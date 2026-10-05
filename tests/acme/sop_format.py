"""The SOP file format, as a strict parser. This is the contract the Day 4 planner parser is written against
(register 2.3, risk N.72). The format is documented in acme/knowledge/sops/README.md."""

import re
from dataclasses import dataclass
from pathlib import Path

from agent.policy.loader import PolicyError, strict_yaml

SOP_DIR = Path(__file__).resolve().parents[2] / "acme" / "knowledge" / "sops"
FRONT_MATTER_KEYS = {"id", "title", "triggers"}
STEP_HEADING = re.compile(r"^### ([A-Z]{2}-\d+) (\S.*)$")
FIELDS = ("Target", "Source", "Ask when")


class SopFormatError(ValueError):
    pass


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    target: str
    source: str
    ask_when: str


@dataclass(frozen=True)
class Sop:
    id: str
    title: str
    triggers: list[str]
    steps: list[Step]
    text: str


def parse_sop(text: str, name: str) -> Sop:
    """`name` is the file stem; the front-matter id must equal it."""
    parts = text.split("---\n", 2)
    if len(parts) != 3 or parts[0] != "":
        raise SopFormatError(f"{name}: the file must start with a --- front-matter block")
    try:
        meta = strict_yaml(parts[1])
    except PolicyError as exc:
        raise SopFormatError(f"{name}: front-matter: {exc}") from exc
    if not isinstance(meta, dict) or set(meta) != FRONT_MATTER_KEYS:
        raise SopFormatError(f"{name}: front-matter keys must be exactly {sorted(FRONT_MATTER_KEYS)}")
    if meta["id"] != name:
        raise SopFormatError(f"{name}: front-matter id {meta['id']!r} must equal the file name")
    triggers = meta["triggers"]
    if (not isinstance(meta["title"], str) or not meta["title"].strip() or not isinstance(triggers, list)
            or not triggers or not all(isinstance(t, str) and t and t == t.lower() for t in triggers)):
        raise SopFormatError(f"{name}: title must be text and triggers a non-empty list of lowercase text")

    steps, current = [], None
    for line in parts[2].splitlines():
        if line.startswith("###"):
            m = STEP_HEADING.match(line)
            if not m:
                raise SopFormatError(f"{name}: bad step heading {line!r}; expected '### AB-1 Title'")
            current = [m.group(1), m.group(2), []]
            steps.append(current)
        elif current is not None and (line.startswith("- ") or line.startswith("  ")):
            if line.startswith("- "):
                current[2].append(line[2:])
            elif current[2]:
                current[2][-1] += " " + line.strip()
            else:
                raise SopFormatError(f"{name}: {current[0]}: a continuation line before any field")
        elif current is not None and line.strip():
            raise SopFormatError(f"{name}: {current[0]}: unexpected line {line!r}")
    if not steps:
        raise SopFormatError(f"{name}: no steps")

    out = []
    for step_id, title, lines in steps:
        values = []
        for label, line in zip(FIELDS, lines):
            if not line.startswith(label + ": ") or not line[len(label) + 2:].strip():
                raise SopFormatError(f"{name}: {step_id}: expected '- {label}: <text>', got {line!r}")
            values.append(line[len(label) + 2:].strip())
        if len(lines) != len(FIELDS):
            raise SopFormatError(f"{name}: {step_id}: needs exactly the lines {', '.join(FIELDS)}")
        out.append(Step(step_id, title, *values))
    return Sop(meta["id"], meta["title"], triggers, out, text)


def load_sops(directory: Path = SOP_DIR) -> list[Sop]:
    return [parse_sop(p.read_text(), p.stem) for p in sorted(directory.glob("*.md")) if p.name != "README.md"]
