from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from oh_my_subagents.interfaces.cli.main import build_parser
from oh_my_subagents.interfaces.cli.providers.configuration import (
    ProviderConfigurationRequest,
    configure_provider,
)
from oh_my_subagents.interfaces.cli.providers.contracts import ProviderIdentityOutcome
from oh_my_subagents.interfaces.cli.providers.identity import invoke_provider_identity_action
from oh_my_subagents.platform.provider_environment import (
    ANTHROPIC_API_KEY,
    read_provider_secret_environment,
)
from oh_my_subagents.providers import ProviderKind
from oh_my_subagents.runtime.providers import ProviderAuthenticationMethod


def test_codex_subscription_identity_delegates_without_storing_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native_calls: list[tuple[list[str], dict[str, object]]] = []

    def native_runner(
        command: list[str],
        **options: object,
    ) -> subprocess.CompletedProcess[str]:
        native_calls.append((command, options))
        return subprocess.CompletedProcess(command, 0)

    bundled_binary = tmp_path / "codex"
    monkeypatch.setattr(
        "oh_my_subagents.interfaces.cli.providers.identity.bundled_codex_path",
        lambda: bundled_binary,
    )

    snapshot = invoke_provider_identity_action(
        ProviderKind.CODEX,
        "login",
        is_json_output=True,
        command_runner=native_runner,
    )

    assert snapshot.outcome == ProviderIdentityOutcome.SUCCEEDED
    assert snapshot.authentication_method is ProviderAuthenticationMethod.SUBSCRIPTION
    assert native_calls[0][0] == [str(bundled_binary), "login"]
    assert native_calls[0][1]["stdout"] == subprocess.DEVNULL
    assert native_calls[0][1]["stderr"] == subprocess.DEVNULL


def test_claude_api_key_identity_uses_private_service_environment(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    snapshot = invoke_provider_identity_action(
        ProviderKind.CLAUDE,
        "login",
        is_json_output=True,
        config_path=config_path,
        authentication_method=ProviderAuthenticationMethod.API_KEY,
        secret="anthropic-secret",
    )

    assert snapshot.outcome == ProviderIdentityOutcome.SUCCEEDED
    assert read_provider_secret_environment(tmp_path / "oms.env") == {
        ANTHROPIC_API_KEY: "anthropic-secret"
    }
    assert "anthropic-secret" not in snapshot.model_dump_json()


def test_claude_subscription_identity_uses_sdk_bundled_native_login(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    config_path = tmp_path / "config.toml"
    invoke_provider_identity_action(
        ProviderKind.CLAUDE,
        "login",
        is_json_output=True,
        config_path=config_path,
        authentication_method=ProviderAuthenticationMethod.API_KEY,
        secret="old-api-key",
    )
    monkeypatch.setattr(
        "oh_my_subagents.interfaces.cli.providers.identity.bundled_claude_path",
        lambda: tmp_path / "claude",
    )

    def run(command: list[str], **_options: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    snapshot = invoke_provider_identity_action(
        ProviderKind.CLAUDE,
        "login",
        is_json_output=False,
        config_path=config_path,
        authentication_method=ProviderAuthenticationMethod.SUBSCRIPTION,
        command_runner=run,
    )

    assert snapshot.outcome == ProviderIdentityOutcome.SUCCEEDED
    assert calls == [[str(tmp_path / "claude"), "auth", "login", "--claudeai"]]
    assert read_provider_secret_environment(tmp_path / "oms.env") == {}


def test_provider_login_cli_reads_claude_api_key_from_stdin_without_echo(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CLAUDE),
    )

    result = CliRunner().invoke(
        build_parser(),
        [
            "providers",
            "login",
            "claude",
            "--config",
            str(config_path),
            "--method",
            "api-key",
            "--secret-stdin",
        ],
        input="anthropic-secret\n",
    )

    assert result.exit_code == 0, result.output
    assert "anthropic-secret" not in result.output
    assert "Authentication: API key" in result.output
    assert read_provider_secret_environment(tmp_path / "oms.env") == {
        ANTHROPIC_API_KEY: "anthropic-secret"
    }


def test_provider_login_rejects_method_owned_by_another_provider(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CLAUDE),
    )

    result = CliRunner().invoke(
        build_parser(),
        [
            "providers",
            "login",
            "claude",
            "--config",
            str(config_path),
            "--method",
            "token",
            "--secret-stdin",
        ],
        input="must-not-be-used\n",
    )

    assert result.exit_code != 0
    assert "'token' is not one of 'subscription', 'api-key'" in result.output
    assert not (tmp_path / "oms.env").exists()


def test_noninteractive_provider_login_requires_an_explicit_method(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CODEX),
    )

    result = CliRunner().invoke(
        build_parser(),
        ["providers", "login", "codex", "--config", str(config_path), "--json"],
    )

    assert result.exit_code != 0
    assert "--method is required" in result.output


def test_noninteractive_subscription_login_requires_a_terminal(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CODEX),
    )

    result = CliRunner().invoke(
        build_parser(),
        [
            "providers",
            "login",
            "codex",
            "--config",
            str(config_path),
            "--method",
            "subscription",
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert "subscription login requires an interactive terminal" in result.output


def test_claude_logout_reports_partial_when_only_stored_api_key_is_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    invoke_provider_identity_action(
        ProviderKind.CLAUDE,
        "login",
        is_json_output=True,
        config_path=config_path,
        authentication_method=ProviderAuthenticationMethod.API_KEY,
        secret="stored-key",
    )
    monkeypatch.setattr(
        "oh_my_subagents.interfaces.cli.providers.identity.bundled_claude_path",
        lambda: tmp_path / "claude",
    )

    def fail_logout(
        command: list[str],
        **_options: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1)

    snapshot = invoke_provider_identity_action(
        ProviderKind.CLAUDE,
        "logout",
        is_json_output=True,
        config_path=config_path,
        command_runner=fail_logout,
    )

    assert snapshot.outcome is ProviderIdentityOutcome.PARTIAL
    assert "API key removed" in snapshot.detail
    assert read_provider_secret_environment(tmp_path / "oms.env") == {}
