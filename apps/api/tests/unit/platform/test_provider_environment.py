from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from autoclaw.platform.provider_environment import (
    ANTHROPIC_API_KEY,
    OPENCLAW_GATEWAY_PASSWORD,
    OPENCLAW_GATEWAY_TOKEN,
    ProviderEnvironmentError,
    persist_provider_secret,
    provider_secret_environment,
    provider_service_environment,
    provider_service_identity_environment,
    provider_subprocess_environment,
    provider_subprocess_environment_overrides,
    read_provider_secret_environment,
)


def test_private_provider_environment_round_trips_and_preserves_comments(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "autoclaw.env"
    env_file.write_text("# Managed provider credentials.\n", encoding="utf-8")

    persist_provider_secret(
        env_file,
        key=OPENCLAW_GATEWAY_TOKEN,
        value='token with $ and "quotes"',
        remove=frozenset({OPENCLAW_GATEWAY_PASSWORD}),
    )

    assert read_provider_secret_environment(env_file) == {
        OPENCLAW_GATEWAY_TOKEN: 'token with $ and "quotes"'
    }
    assert "# Managed provider credentials." in env_file.read_text(encoding="utf-8")
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600


def test_private_provider_environment_replaces_mutually_exclusive_gateway_secret(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "autoclaw.env"
    persist_provider_secret(env_file, key=OPENCLAW_GATEWAY_TOKEN, value="token-value")

    persist_provider_secret(
        env_file,
        key=OPENCLAW_GATEWAY_PASSWORD,
        value="password-value",
        remove=frozenset({OPENCLAW_GATEWAY_TOKEN}),
    )

    assert read_provider_secret_environment(env_file) == {
        OPENCLAW_GATEWAY_PASSWORD: "password-value"
    }


def test_private_provider_environment_rejects_unowned_assignments(tmp_path: Path) -> None:
    env_file = tmp_path / "autoclaw.env"
    env_file.write_text("CUSTOM_FLAG=1\n", encoding="utf-8")

    with pytest.raises(ProviderEnvironmentError, match="does not support CUSTOM_FLAG"):
        read_provider_secret_environment(env_file)

    with pytest.raises(ProviderEnvironmentError, match="does not support CUSTOM_FLAG"):
        persist_provider_secret(env_file, key=ANTHROPIC_API_KEY, value="stored-key")


def test_provider_environment_fills_missing_process_value_without_overriding_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / "autoclaw.env"
    persist_provider_secret(env_file, key=ANTHROPIC_API_KEY, value="stored-key")
    monkeypatch.setenv(ANTHROPIC_API_KEY, "shell-key")

    with provider_secret_environment(env_file):
        assert os.environ[ANTHROPIC_API_KEY] == "shell-key"

    assert os.environ[ANTHROPIC_API_KEY] == "shell-key"


def test_service_provider_environment_exactly_mirrors_private_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / "autoclaw.env"
    persist_provider_secret(env_file, key=ANTHROPIC_API_KEY, value="stored-key")
    monkeypatch.setenv(ANTHROPIC_API_KEY, "shell-key")
    monkeypatch.setenv(OPENCLAW_GATEWAY_TOKEN, "shell-token")

    with provider_service_environment(env_file):
        assert os.environ[ANTHROPIC_API_KEY] == "stored-key"
        assert OPENCLAW_GATEWAY_TOKEN not in os.environ

    assert os.environ[ANTHROPIC_API_KEY] == "shell-key"
    assert os.environ[OPENCLAW_GATEWAY_TOKEN] == "shell-token"


def test_service_provider_identity_uses_default_native_homes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_HOME", "/tmp/shell-codex")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/tmp/shell-claude")
    monkeypatch.setenv("OPENCLAW_STATE_DIR", "/tmp/shell-openclaw")

    with provider_service_identity_environment():
        assert "CODEX_HOME" not in os.environ
        assert "CLAUDE_CONFIG_DIR" not in os.environ
        assert "OPENCLAW_STATE_DIR" not in os.environ

    assert os.environ["CODEX_HOME"] == "/tmp/shell-codex"
    assert os.environ["CLAUDE_CONFIG_DIR"] == "/tmp/shell-claude"
    assert os.environ["OPENCLAW_STATE_DIR"] == "/tmp/shell-openclaw"


def test_provider_subprocess_overrides_blank_other_managed_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ANTHROPIC_API_KEY, "anthropic-secret")
    monkeypatch.setenv(OPENCLAW_GATEWAY_TOKEN, "gateway-secret")

    overrides = provider_subprocess_environment_overrides(
        allowed_keys=frozenset({ANTHROPIC_API_KEY})
    )

    assert ANTHROPIC_API_KEY not in overrides
    assert overrides[OPENCLAW_GATEWAY_TOKEN] == ""


def test_provider_subprocess_environment_removes_other_managed_credentials() -> None:
    environment = {
        "PATH": "/usr/bin",
        ANTHROPIC_API_KEY: "anthropic-secret",
        OPENCLAW_GATEWAY_TOKEN: "gateway-secret",
    }

    child_environment = provider_subprocess_environment(
        allowed_keys=frozenset({ANTHROPIC_API_KEY}),
        environment=environment,
    )

    assert child_environment == {
        "PATH": "/usr/bin",
        ANTHROPIC_API_KEY: "anthropic-secret",
    }
