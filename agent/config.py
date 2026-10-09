"""Agent configuration: the only module in agent/ that reads the environment (a test enforces this).

Values come from `.env` (read with `dotenv_values`, which does not touch `os.environ`) and then from the
process environment, but only for the keys in `ALLOWED_KEYS`. `ACME_ADMIN_TOKEN` and the other users'
passwords are never loaded, even when the author has exported them in the shell for `make acme` (N.30, N.92).
Subprocesses (browser, code tool) get an explicit env built from this config, never the inherited one (D-105).
"""

import os
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_KEYS = frozenset({
    "ACME_URL", "ACME_PASSWORD_OPS_AGENT", "ACME_HTTP_TIMEOUT_SECONDS", "READ_LAG_SECONDS", "TZ_NAME", "HEADED",
    "REPLAY", "CASSETTE_DIR", "CASSETTE_SCOPE", "LLM_TOKEN_BUDGET",
    "LLM_DAILY_LIMITS", "LLM_RPM", "GEMINI_API_KEY", "GEMINI_BASE_URL", "GEMINI_MODEL", "GEMINI_FLASH2_MODEL",
    "GEMINI_LITE_MODEL", "GEMINI_LITE2_MODEL", "GROQ_API_KEY", "GROQ_BASE_URL", "GROQ_PLAN_MODEL", "GROQ_JUDGE_MODEL",
    "GROQ_COMPACTION_MODEL",
    "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "OPENROUTER_FALLBACK_MODEL",
})


def load_config(env_file: Path | None = ROOT / ".env",
                environ: Mapping[str, str] | None = None) -> Mapping[str, str]:
    """Allowlisted settings, read-only. The process environment wins over `.env`; empty values are dropped."""
    environ = os.environ if environ is None else environ
    from_file = dotenv_values(env_file) if env_file is not None and env_file.is_file() else {}
    values = {}
    for key in sorted(ALLOWED_KEYS):
        value = environ.get(key) or from_file.get(key)
        if value:
            values[key] = value
    return MappingProxyType(values)


# What a launched browser may see of the environment (D-105): enough for Chromium to start and nothing else.
BROWSER_ENV_KEYS = ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL", "XDG_RUNTIME_DIR")


def browser_env(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The explicit env for the browser process, never the inherited one: no Acme token, no API keys."""
    environ = os.environ if environ is None else environ
    return {key: environ[key] for key in BROWSER_ENV_KEYS if environ.get(key)}
