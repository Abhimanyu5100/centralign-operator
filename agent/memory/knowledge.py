"""The SOPs (acme/knowledge/sops/*.md): id, title, triggers, step ids and text. tests/acme/sop_format.py stays the
strict format contract; a test keeps this loader in step with it."""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

SOP_DIR = Path(__file__).resolve().parents[2] / "acme" / "knowledge" / "sops"
STEP = re.compile(r"^### ([A-Z]{2}-\d+) ", re.M)


@dataclass(frozen=True)
class Sop:
    id: str
    title: str
    triggers: list[str]
    steps: list[str]
    text: str

    def sections(self) -> dict[str, str]:
        parts = STEP.split(self.text)[1:]
        return {step: f"### {step} {body.strip()}" for step, body in zip(parts[::2], parts[1::2])}

    def write_steps(self, optional: bool = False) -> list[str]:
        """Steps whose Source names a POST (an endpoint or a page action): each needs a milestone (N.177), unless its
        title makes it conditional ("... when required"); `optional=True` lists only those (D-195)."""
        return [step for step, text in self.sections().items()
                if "POST " in text and (not optional or " when " in text.split("\n", 1)[0])]


def load_sops(folder: Path = SOP_DIR) -> dict[str, Sop]:
    sops = {}
    for path in sorted(p for p in folder.glob("*.md") if p.name != "README.md"):
        text = path.read_text(encoding="utf-8")
        meta = yaml.safe_load(text.split("---\n")[1])
        sops[meta["id"]] = Sop(meta["id"], meta["title"], meta["triggers"], STEP.findall(text), text)
    return sops


def match_sops(request: str, sops: dict[str, Sop]) -> list[str]:
    """SOPs whose trigger words or phrases occur in the request: the only SOPs a run may follow (decision 5)."""
    words = " ".join(re.findall(r"[a-z]+", request.lower()))
    return [s.id for s in sops.values() if any(re.search(rf"\b{re.escape(t)}\b", words) for t in s.triggers)]
