"""The submission docs stay true to the repo (Day 6): every `make` target they name exists in the Makefile, every
relative link and anchor resolves, every cited test exists, every cited decision and risk id is a real row, and every
cited bench results file is there."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "README.md", *(ROOT / "docs" / name for name in ("DESIGN.md", "EVALUATION.md", "EXTENDING.md", "DEMO.md"))]
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
FENCE = re.compile(r"```.*?```", re.S)


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def anchors(path: Path) -> set[str]:
    """GitHub's heading slugs: lower case, punctuation dropped except - and _, spaces to hyphens."""
    heads = re.findall(r"^#{1,6} (.+)$", FENCE.sub("", text(path)), re.M)
    return {re.sub(r"[^\w\- ]", "", h.strip().lower()).replace(" ", "-") for h in heads}


def make_targets() -> set[str]:
    return set(re.findall(r"^([a-z][a-z0-9-]*):", text(ROOT / "Makefile"), re.M))


def defined_tests() -> set[str]:
    return {m for p in (ROOT / "tests").rglob("*.py") for m in re.findall(r"def (test_\w+)", text(p))}


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_every_make_command_a_doc_names_exists(doc):
    named = set(re.findall(r"\bmake ([a-z][a-z0-9-]*)", text(doc)))
    assert named and named <= make_targets(), sorted(named - make_targets())


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_every_relative_link_and_anchor_resolves(doc):
    broken = []
    for target in LINK.findall(FENCE.sub("", text(doc))):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        path, _, anchor = target.partition("#")
        file = (doc.parent / path).resolve() if path else doc
        if not file.exists():
            broken.append(target)
        elif anchor and file.suffix == ".md" and anchor not in anchors(file):
            broken.append(target)
    assert not broken, broken


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_every_cited_test_exists(doc):
    cited = set(re.findall(r"`(test_\w+)`", text(doc)))
    assert cited <= defined_tests(), sorted(cited - defined_tests())


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_every_cited_decision_and_risk_is_a_real_row(doc):
    decisions, risks = text(ROOT / "docs" / "decisions.md"), text(ROOT / "docs" / "risk-log.md")
    missing = [d for d in set(re.findall(r"\bD-\d{3}\b", text(doc))) if f"| {d} |" not in decisions]
    missing += [n for n in set(re.findall(r"\bN\.\d+\b", text(doc))) if f"| {n} |" not in risks]
    assert not missing, sorted(missing)


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_every_cited_results_file_is_in_bench_results(doc):
    cited = set(re.findall(r"\b(2026\d{4}-\d{6})\b", text(doc)))
    missing = [c for c in cited if not (ROOT / "bench" / "results" / f"{c}.md").is_file()]
    assert not missing, sorted(missing)


def test_the_link_check_can_fail(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text("# Title\n[x](missing.md) [y](#nowhere) [z](#title)\n")
    found = [t for t in LINK.findall(text(bad)) if not (t.startswith("#") and t[1:] in anchors(bad))
             and not (not t.startswith("#") and (tmp_path / t).exists())]
    assert found == ["missing.md", "#nowhere"]


IMAGE = re.compile(r'<img[^>]*\bsrc="([^"]+)"|!\[[^\]]*\]\(([^)\s]+)\)')
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️]")


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_every_image_exists_and_has_alt_text(doc):
    """The README's screenshots and GIF come from `make readme-assets`; a moved or missing file fails here."""
    body = FENCE.sub("", text(doc))
    for html, md in IMAGE.findall(body):
        assert (doc.parent / (html or md)).is_file(), f"{doc.name}: missing image {html or md}"
    assert all(" alt=" in tag for tag in re.findall(r"<img[^>]*>", body, re.S)), f"{doc.name}: an <img> lacks alt"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_no_emoji(doc):
    """The design brief: plain words and numbers, no emoji or pictographs."""
    assert not EMOJI.findall(text(doc)), f"{doc.name}: {sorted(set(EMOJI.findall(text(doc))))}"
