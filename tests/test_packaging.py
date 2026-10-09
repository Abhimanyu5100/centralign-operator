"""Packaging checks that need no Docker (Day 3.4; register 0.7, R.4; N.30, N.31, N.92, N.158; D-163).

The image must match the locked Playwright, the admin token may appear only in the acme service, the runner runs
the bench with its own child Acme, and secrets never enter the image."""

import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
DOCKERFILE = (ROOT / "Dockerfile").read_text()


def locked(package: str) -> str:
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    return next(p["version"] for p in lock["package"] if p["name"] == package)


def test_the_image_is_the_playwright_image_of_the_locked_version():
    base = re.search(r"^FROM (\S+)", DOCKERFILE, re.M)[1]
    assert base == f"mcr.microsoft.com/playwright/python:v{locked('playwright')}-noble"
    assert "uv sync --frozen" in DOCKERFILE and "UV_FROZEN=1" in DOCKERFILE


def test_the_admin_token_is_only_in_the_acme_service():
    services = COMPOSE["services"]
    assert set(services) == {"acme", "runner"}
    holders = [name for name, svc in services.items() if "ACME_ADMIN_TOKEN" in str(svc)]
    assert holders == ["acme"]
    assert "ACME_ADMIN_TOKEN" not in DOCKERFILE  # never baked into the image


def test_up_serves_acme_on_8000_and_the_runner_runs_the_bench_on_demand():
    acme, runner = COMPOSE["services"]["acme"], COMPOSE["services"]["runner"]
    assert acme["ports"] == ["8000:8000"] and acme["command"] == ["make", "acme", "HOST=0.0.0.0"]
    assert "healthz" in " ".join(acme["healthcheck"]["test"])
    assert runner["profiles"] == ["tools"] and runner["command"] == ["make", "bench"]
    assert runner["volumes"] == ["./bench/results:/app/bench/results"]
    assert "environment" not in runner  # the bench starts its own Acme with a random token (D-119)


def test_secrets_and_local_state_never_enter_the_image():
    ignored = (ROOT / ".dockerignore").read_text().split()
    for entry in (".env", ".venv/", ".git/", "runs/", "acme/data/acme.db*", ".claude/"):
        assert entry in ignored


def test_make_acme_stays_on_localhost_unless_told_otherwise():
    makefile = (ROOT / "Makefile").read_text()
    assert "HOST ?= 127.0.0.1" in makefile and "--host $(HOST)" in makefile


def test_the_image_keeps_ist_and_names_its_commit():
    """Day 6: container timestamps in IST (tzdata + TZ) and the bench's commit from a build arg (no .git inside)."""
    assert "tzdata" in DOCKERFILE and "TZ=Asia/Kolkata" in DOCKERFILE
    assert "ARG GIT_COMMIT" in DOCKERFILE and "GIT_COMMIT=${GIT_COMMIT}" in DOCKERFILE
    assert all(svc["build"]["args"]["GIT_COMMIT"] == "${GIT_COMMIT:-}" for svc in COMPOSE["services"].values())
