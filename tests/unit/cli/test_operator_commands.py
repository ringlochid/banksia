from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

import banksia.interfaces.cli as cli
from banksia.interfaces.cli import root as cli_root
from banksia.interfaces.cli.commands import operator as operator_commands
from banksia.interfaces.cli.main import build_parser
from banksia.interfaces.cli.providers.configuration import (
    ProviderConfigurationRequest,
    configure_provider,
)
from banksia.interfaces.cli.providers.contracts import (
    ProviderCheckOutcome,
)
from banksia.providers import ProviderKind
from tests.unit.cli.cli_test_support import (
    build_provider_check_snapshot,
    write_local_cli_config,
)


def test_operator_setup_requires_saved_managed_route_before_mutation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = write_local_cli_config(tmp_path)
    previous_bytes = config_path.read_bytes()

    json_result = cli.main(
        [
            "operator",
            "setup",
            "--config",
            str(config_path),
            "--provider",
            "codex",
            "--non-interactive",
            "--json",
        ],
    )
    json_payload = json.loads(capsys.readouterr().out)
    human_result = cli.main(
        [
            "operator",
            "setup",
            "--config",
            str(config_path),
            "--provider",
            "codex",
            "--non-interactive",
        ]
    )
    human_output = capsys.readouterr().out

    assert json_result == 1
    assert json_payload["error"]["kind"] == "operator_provider_not_configured"
    assert "oms providers configure codex" in json_payload["error"]["hint"]
    assert human_result == 1
    assert "Operator setup needs a provider route" in human_output
    assert "Command parse failed" not in human_output
    assert "oms providers configure codex" in human_output
    assert "oms operator setup --provider codex" in human_output
    assert config_path.read_bytes() == previous_bytes


def test_operator_setup_atomically_replaces_optional_overrides(
    tmp_path: Path,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CODEX),
    )
    runner = CliRunner()
    parser = build_parser()

    first = runner.invoke(
        parser,
        [
            "operator",
            "setup",
            "--config",
            str(config_path),
            "--provider",
            "codex",
            "--model",
            "gpt-operator",
            "--effort",
            "high",
            "--non-interactive",
            "--json",
        ],
    )
    replaced = runner.invoke(
        parser,
        [
            "operator",
            "setup",
            "--config",
            str(config_path),
            "--provider",
            "codex",
            "--non-interactive",
            "--json",
        ],
    )

    assert first.exit_code == 0, first.output
    assert replaced.exit_code == 0, replaced.output
    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert payload["operator"] == {"provider": "codex"}
    assert payload["codex"]["enabled"] is True
    assert json.loads(replaced.output)["changed"] is True


def test_operator_status_is_passive_and_discloses_environment_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CODEX),
    )
    config_path.write_text(
        config_path.read_text(encoding="utf-8") + '\n[operator]\nprovider = "codex"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        operator_commands,
        "collect_configured_provider_check",
        lambda *_args: pytest.fail("passive status contacted a provider"),
    )

    result = CliRunner().invoke(
        build_parser(),
        [
            "operator",
            "status",
            "--config",
            str(config_path),
            "--json",
        ],
        env={
            "OMS_OPERATOR__PROVIDER": "claude",
            "OMS_CLAUDE__ENABLED": "true",
        },
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["operator"]["persisted"]["provider"] == "codex"
    assert payload["operator"]["effective"]["provider"] == "claude"
    assert payload["operator"]["environment_override"] is True
    assert payload["operator"]["provider_route_configured"] is True
    assert payload["next_action"] == "oms providers check claude"


def test_operator_disable_is_idempotent_and_keeps_provider_route(
    tmp_path: Path,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CODEX),
    )
    config_path.write_text(
        config_path.read_text(encoding="utf-8") + '\n[operator]\nprovider = "codex"\n',
        encoding="utf-8",
    )
    runner = CliRunner()
    parser = build_parser()

    first = runner.invoke(
        parser,
        [
            "operator",
            "disable",
            "--config",
            str(config_path),
            "--json",
        ],
        env={"OMS_OPERATOR__PROVIDER": "codex"},
    )
    second = runner.invoke(
        parser,
        [
            "operator",
            "disable",
            "--config",
            str(config_path),
            "--json",
        ],
    )

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert json.loads(first.output)["changed"] is True
    assert json.loads(first.output)["operator"]["environment_override"] is True
    assert json.loads(first.output)["operator"]["effective"]["provider"] == "codex"
    assert json.loads(second.output)["changed"] is False
    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert "operator" not in payload
    assert payload["codex"]["enabled"] is True


def test_guided_operator_can_configure_missing_route_before_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    monkeypatch.setattr(
        cli_root,
        "should_run_guided_flow",
        lambda **_kwargs: True,
    )

    def configure_selected_provider(
        _args: object,
        *,
        config_path: Path,
        provider: ProviderKind,
    ) -> object:
        configure_provider(
            config_path,
            ProviderConfigurationRequest(provider=provider),
        )
        return build_provider_check_snapshot(
            provider,
            outcome=ProviderCheckOutcome.READY,
            is_ready=True,
            detail=f"{provider.value}_available",
        )

    monkeypatch.setattr(
        operator_commands,
        "guide_specific_provider",
        configure_selected_provider,
    )

    result = CliRunner().invoke(
        build_parser(),
        ["operator", "setup", "--config", str(config_path)],
        input="claude\ny\nn\n",
    )

    assert result.exit_code == 0, result.output
    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert payload["claude"]["enabled"] is True
    assert payload["operator"] == {"provider": "claude"}


def test_guided_operator_defaults_to_saved_provider_and_preserves_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CODEX),
    )
    configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CLAUDE),
    )
    with config_path.open("a", encoding="utf-8") as stream:
        stream.write(
            '\n[operator]\nprovider = "claude"\nmodel = "claude-operator"\neffort = "high"\n'
        )
    previous_bytes = config_path.read_bytes()
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)
    monkeypatch.setattr(
        operator_commands,
        "collect_configured_provider_check",
        lambda *_args: pytest.fail("declined readiness check contacted a provider"),
    )

    result = CliRunner().invoke(
        build_parser(),
        ["operator", "setup", "--config", str(config_path)],
        input="\n\nn\n",
    )

    assert result.exit_code == 0, result.output
    assert config_path.read_bytes() == previous_bytes
    assert "Operator provider (Codex, Claude) [Claude]" in result.output
    assert "Change the saved Operator model or reasoning effort?" in result.output
    assert "Operator already configured" in result.output
    assert "Operator setup complete" not in result.output
    assert "Changed" not in result.output
    assert result.output.count("oms providers check claude") == 1


def test_guided_operator_can_explicitly_clear_saved_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CODEX),
    )
    with config_path.open("a", encoding="utf-8") as stream:
        stream.write('\n[operator]\nprovider = "codex"\nmodel = "gpt-operator"\neffort = "high"\n')
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)
    monkeypatch.setattr(
        operator_commands,
        "collect_configured_provider_check",
        lambda *_args: build_provider_check_snapshot(
            ProviderKind.CODEX,
            outcome=ProviderCheckOutcome.READY,
            is_ready=True,
            detail="codex_available",
        ),
    )

    result = CliRunner().invoke(
        build_parser(),
        ["operator", "setup", "--config", str(config_path)],
        input="\ny\n-\n-\n",
    )

    assert result.exit_code == 0, result.output
    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert payload["operator"] == {"provider": "codex"}
    assert "Operator setup complete" in result.output
    assert "Operator already configured" not in result.output
    assert "provider default" in result.output
    assert "Next: oms serve" in result.output


def test_guided_operator_does_not_carry_overrides_to_a_different_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    for provider in (ProviderKind.CODEX, ProviderKind.CLAUDE):
        configure_provider(
            config_path,
            ProviderConfigurationRequest(provider=provider),
        )
    with config_path.open("a", encoding="utf-8") as stream:
        stream.write('\n[operator]\nprovider = "codex"\nmodel = "gpt-operator"\neffort = "high"\n')
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)
    monkeypatch.setattr(
        operator_commands,
        "collect_configured_provider_check",
        lambda *_args: build_provider_check_snapshot(
            ProviderKind.CLAUDE,
            outcome=ProviderCheckOutcome.READY,
            is_ready=True,
            detail="claude_available",
        ),
    )

    result = CliRunner().invoke(
        build_parser(),
        ["operator", "setup", "--config", str(config_path)],
        input="Claude\nn\n",
    )

    assert result.exit_code == 0, result.output
    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert payload["operator"] == {"provider": "claude"}
    assert "Operator setup complete" in result.output
