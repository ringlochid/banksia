from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

from banksia.interfaces.cli.commands import providers as provider_commands
from banksia.interfaces.cli.main import build_parser
from banksia.interfaces.cli.providers.configuration import ProviderConfigurationRequest
from banksia.interfaces.cli.providers.contracts import (
    ProviderCheckOutcome,
    ProviderCheckSnapshot,
    ProviderConfigurationSnapshot,
)
from banksia.providers import ProviderKind
from banksia.runtime.providers import (
    ProviderAuthenticationMethod,
    ProviderCheckAxisStatus,
)


def test_setup_uses_the_shared_configuration_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    calls: list[ProviderConfigurationRequest] = []
    original = provider_commands.configure_provider

    def recording_configure(
        path: Path,
        request: ProviderConfigurationRequest,
    ) -> ProviderConfigurationSnapshot:
        calls.append(request)
        return original(path, request)

    monkeypatch.setattr(provider_commands, "configure_provider", recording_configure)
    monkeypatch.setattr(
        provider_commands,
        "collect_provider_check",
        lambda _settings, provider: ProviderCheckSnapshot(
            kind=provider,
            outcome=ProviderCheckOutcome.READY,
            is_ready=True,
            service_identity="tester",
            native_home="/tmp/claude",
            authentication=ProviderCheckAxisStatus.PASSED,
            authentication_method=ProviderAuthenticationMethod.SUBSCRIPTION,
            detail="claude_available",
        ),
    )

    result = provider_commands.cmd_setup(
        argparse.Namespace(
            config=str(config_path),
            provider="claude",
            model="sonnet",
            effort=None,
            gateway_url=None,
            gateway_profile=None,
            gateway_auth_mode=None,
            json=True,
        )
    )

    assert result == 0
    assert calls == [ProviderConfigurationRequest(provider=ProviderKind.CLAUDE, model="sonnet")]
    assert tomllib.loads(config_path.read_text())["runtime"]["default_provider"] == "claude"


def test_json_setup_without_provider_is_a_zero_write_guide(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"

    result = CliRunner().invoke(
        build_parser(),
        ["setup", "--config", str(config_path), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload == {
        "ok": True,
        "configured_provider": None,
        "configured_providers": [],
        "default_provider": None,
        "default_provider_configured": False,
        "next_actions": [
            "banksia init",
            "banksia providers configure <provider>",
        ],
    }
    assert not config_path.exists()


@pytest.mark.parametrize(
    ("config_text", "configured", "default_provider", "next_actions"),
    (
        (
            "[codex]\nenabled = true\n",
            ["codex"],
            None,
            ["banksia providers set-default codex"],
        ),
        (
            '[codex]\nenabled = true\n[runtime]\ndefault_provider = "codex"\n',
            ["codex"],
            "codex",
            ["banksia providers check codex", "banksia serve"],
        ),
        (
            "[codex]\nenabled = true\n[claude]\nenabled = true\n",
            ["codex", "claude"],
            None,
            ["banksia providers set-default <provider>"],
        ),
    ),
)
def test_json_setup_guide_uses_selected_provider_state_without_writes(
    tmp_path: Path,
    config_text: str,
    configured: list[str],
    default_provider: str | None,
    next_actions: list[str],
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(config_text, encoding="utf-8")
    previous_bytes = config_path.read_bytes()

    result = CliRunner().invoke(
        build_parser(),
        ["setup", "--config", str(config_path), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["configured_providers"] == configured
    assert payload["configured_provider"] == (configured[0] if len(configured) == 1 else None)
    assert payload["default_provider"] == default_provider
    assert payload["default_provider_configured"] is (default_provider is not None)
    assert payload["next_actions"] == next_actions
    assert config_path.read_bytes() == previous_bytes


def test_json_setup_guide_configures_environment_only_provider_before_default(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"

    result = CliRunner().invoke(
        build_parser(),
        ["setup", "--config", str(config_path), "--json"],
        env={"BANKSIA_CODEX__ENABLED": "true"},
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["configured_providers"] == ["codex"]
    assert payload["default_provider"] is None
    assert payload["next_actions"] == ["banksia providers configure codex"]
    assert not config_path.exists()
