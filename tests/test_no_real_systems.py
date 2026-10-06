"""Register 0.6 (real systems or credentials used): Acme stays on this machine.

(a) Every Acme base-URL-like value in `.env.example` points at localhost or 127.0.0.1.
(b) Nothing under `acme/` imports an outbound network client.

Only `.env.example` is read; `.env` is never opened. Only `acme/` is scanned, so tests that use
`TestClient` (which pulls in httpx) cannot false-positive.
"""

from __future__ import annotations

import ast
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
LOCAL_HOSTS = {"localhost", "127.0.0.1"}

# Modules that can open a connection to another machine. `urllib.parse` is pure string work and allowed.
FORBIDDEN_MODULES = {
    "smtplib",
    "requests",
    "httpx",
    "urllib.request",
    "http.client",
    "socket",
    "aiohttp",
    "ftplib",
    "imaplib",
    "poplib",
    "telnetlib",
    "websocket",
    "websockets",
}


def _env_example_acme_urls() -> dict[str, str]:
    urls: dict[str, str] = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key.startswith("ACME_") and "://" in value:
            urls[key] = value
    return urls


def test_env_example_acme_urls_are_local() -> None:
    urls = _env_example_acme_urls()
    assert "ACME_URL" in urls, "expected ACME_URL in .env.example"
    for key, value in urls.items():
        assert urlsplit(value).hostname in LOCAL_HOSTS, f"{key}={value} is not localhost"


def _forbidden_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            # `from urllib import request` imports urllib.request.
            names = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
        for name in names:
            parts = name.split(".")
            prefixes = {".".join(parts[: i + 1]) for i in range(len(parts))}
            if prefixes & FORBIDDEN_MODULES:
                found.append(f"{path.relative_to(ROOT)}:{node.lineno}: {name}")
    return found


def test_acme_imports_no_outbound_network_client() -> None:
    sources = sorted((ROOT / "acme").rglob("*.py"))
    assert sources, "no acme sources found"
    found = [hit for path in sources for hit in _forbidden_imports(path)]
    assert not found, "outbound network client imported in acme/:\n" + "\n".join(found)
