from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from oh_my_subagents.platform.provider_environment import (
    ANTHROPIC_API_KEY,
    ProviderEnvironmentError,
    persist_provider_secret,
    provider_environment_file_path,
    provider_secret_environment,
    provider_service_environment,
    provider_service_identity_environment,
    provider_subprocess_environment,
    provider_subprocess_environment_overrides,
    read_provider_secret_environment,
)


def test_provider_environment_uses_only_banksia_private_file_name(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    assert provider_environment_file_path(config_path) == tmp_path / "oms.env"


def test_private_provider_environment_round_trips_and_preserves_comments(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "oms.env"
    env_file.write_text("# Managed provider credentials.\n", encoding="utf-8")

    persist_provider_secret(
        env_file,
        key=ANTHROPIC_API_KEY,
        value='key with $ and "quotes"',
    )

    assert read_provider_secret_environment(env_file) == {
        ANTHROPIC_API_KEY: 'key with $ and "quotes"'
    }
    assert "# Managed provider credentials." in env_file.read_text(encoding="utf-8")
    if os.name == "posix":
        assert stat.S_IMODE(env_file.stat().st_mode) == 0o600


def test_retired_provider_assignments_are_ignored_without_reexposing_them(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "oms.env"
    env_file.write_text(
        'OPENCLAW_GATEWAY_TOKEN="retired-token"\n'
        'OPENCLAW_GATEWAY_PASSWORD="retired-password"\n'
        f'{ANTHROPIC_API_KEY}="anthropic-value"\n',
        encoding="utf-8",
    )

    assert read_provider_secret_environment(env_file) == {ANTHROPIC_API_KEY: "anthropic-value"}


@pytest.mark.skipif(os.name != "posix", reason="POSIX no-follow proof")
def test_provider_environment_rejects_a_final_symlink(tmp_path: Path) -> None:
    target = tmp_path / "outside.env"
    target.write_text(f'{ANTHROPIC_API_KEY}="outside"\n', encoding="utf-8")
    env_file = tmp_path / "oms.env"
    env_file.symlink_to(target)

    with pytest.raises(OSError):
        read_provider_secret_environment(env_file)
    with pytest.raises(OSError):
        persist_provider_secret(
            env_file,
            key=ANTHROPIC_API_KEY,
            value="replacement",
        )

    assert target.read_text(encoding="utf-8") == f'{ANTHROPIC_API_KEY}="outside"\n'


def test_private_provider_environment_rejects_unowned_assignments(tmp_path: Path) -> None:
    env_file = tmp_path / "oms.env"
    env_file.write_text("CUSTOM_FLAG=1\n", encoding="utf-8")

    with pytest.raises(ProviderEnvironmentError, match="does not support CUSTOM_FLAG"):
        read_provider_secret_environment(env_file)

    with pytest.raises(ProviderEnvironmentError, match="does not support CUSTOM_FLAG"):
        persist_provider_secret(env_file, key=ANTHROPIC_API_KEY, value="stored-key")


def test_provider_environment_fills_missing_process_value_without_overriding_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / "oms.env"
    persist_provider_secret(env_file, key=ANTHROPIC_API_KEY, value="stored-key")
    monkeypatch.setenv(ANTHROPIC_API_KEY, "shell-key")

    with provider_secret_environment(env_file):
        assert os.environ[ANTHROPIC_API_KEY] == "shell-key"

    assert os.environ[ANTHROPIC_API_KEY] == "shell-key"


def test_service_provider_environment_exactly_mirrors_private_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / "oms.env"
    persist_provider_secret(env_file, key=ANTHROPIC_API_KEY, value="stored-key")
    monkeypatch.setenv(ANTHROPIC_API_KEY, "shell-key")

    with provider_service_environment(env_file):
        assert os.environ[ANTHROPIC_API_KEY] == "stored-key"

    assert os.environ[ANTHROPIC_API_KEY] == "shell-key"


def test_service_provider_identity_uses_default_native_homes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_HOME", "/tmp/shell-codex")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/tmp/shell-claude")

    with provider_service_identity_environment():
        assert "CODEX_HOME" not in os.environ
        assert "CLAUDE_CONFIG_DIR" not in os.environ

    assert os.environ["CODEX_HOME"] == "/tmp/shell-codex"
    assert os.environ["CLAUDE_CONFIG_DIR"] == "/tmp/shell-claude"


def test_provider_subprocess_overrides_blank_other_managed_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ANTHROPIC_API_KEY, "anthropic-secret")

    overrides = provider_subprocess_environment_overrides()

    assert overrides == {ANTHROPIC_API_KEY: ""}


def test_provider_subprocess_environment_removes_other_managed_credentials() -> None:
    environment = {
        "PATH": "/usr/bin",
        ANTHROPIC_API_KEY: "anthropic-secret",
    }

    child_environment = provider_subprocess_environment(
        environment=environment,
    )

    assert child_environment == {"PATH": "/usr/bin"}
