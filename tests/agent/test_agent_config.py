"""Agent config (agent/config.py): an allowlist of env keys, never ACME_ADMIN_TOKEN. Risks N.30, N.92 (D-039, D-105)."""

import pytest

from agent.config import ALLOWED_KEYS, ROOT, load_config

FORBIDDEN = ("ACME_ADMIN_TOKEN", "ACME_PASSWORD_MEERA", "ACME_PASSWORD_ADMIN")


def test_the_allowlist_holds_no_admin_token_and_no_other_users_password():
    assert not set(FORBIDDEN) & ALLOWED_KEYS
    assert not [k for k in ALLOWED_KEYS if "ADMIN" in k]


def test_admin_token_already_exported_in_the_shell_is_not_exposed(monkeypatch):
    # the author exports ACME_ADMIN_TOKEN for `make acme`, so the agent's process may inherit it
    for key in FORBIDDEN:
        monkeypatch.setenv(key, "do-not-load")
    monkeypatch.setenv("ACME_URL", "http://localhost:8000")
    config = load_config(env_file=None)
    assert config["ACME_URL"] == "http://localhost:8000"
    assert not set(FORBIDDEN) & set(config) and "do-not-load" not in config.values()


def test_admin_token_in_the_env_file_is_not_loaded(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ACME_ADMIN_TOKEN=tok\nACME_PASSWORD_MEERA=m\nACME_PASSWORD_OPS_AGENT=ops\nGEMINI_MODEL=\n")
    config = load_config(env_file=env, environ={})
    assert dict(config) == {"ACME_PASSWORD_OPS_AGENT": "ops"}  # empty values are dropped too


def test_the_process_environment_wins_over_the_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ACME_URL=http://localhost:1\n")
    assert load_config(env_file=env, environ={"ACME_URL": "http://localhost:2"})["ACME_URL"] == "http://localhost:2"


def test_config_is_read_only():
    with pytest.raises(TypeError):
        load_config(env_file=None, environ={})["ACME_URL"] = "x"  # type: ignore[index]


def test_every_allowed_key_is_documented_in_env_example():
    documented = {line.split("=", 1)[0].strip() for line in (ROOT / ".env.example").read_text().splitlines()
                  if "=" in line and not line.lstrip().startswith("#")}
    assert ALLOWED_KEYS <= documented, sorted(ALLOWED_KEYS - documented)
