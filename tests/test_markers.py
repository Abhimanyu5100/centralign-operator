"""Browser tests must carry the `e2e` marker so `make test` stays fast (risk N.38)."""

import re
from pathlib import Path

TESTS = Path(__file__).parent
IMPORTS_PLAYWRIGHT = re.compile(r"^\s*(?:import|from)\s+playwright\b", re.MULTILINE)
HAS_MARKER = re.compile(r"^pytestmark\s*=.*\be2e\b", re.MULTILINE)


def unmarked(root: Path) -> list[str]:
    bad = []
    for path in sorted(root.rglob("*.py")):
        text = path.read_text()
        if IMPORTS_PLAYWRIGHT.search(text) and not HAS_MARKER.search(text):
            bad.append(str(path.relative_to(root)))
    return bad


def test_every_playwright_test_file_is_marked_e2e():
    assert unmarked(TESTS) == []


def test_the_check_catches_an_unmarked_file(tmp_path):
    (tmp_path / "test_good.py").write_text("import pytest\nfrom playwright.async_api import async_playwright\n"
                                           "pytestmark = pytest.mark.e2e\n")
    (tmp_path / "test_bad.py").write_text("from playwright.async_api import async_playwright\n")
    (tmp_path / "test_unrelated.py").write_text("import json\n")
    assert unmarked(tmp_path) == ["test_bad.py"]
