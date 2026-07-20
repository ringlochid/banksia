from __future__ import annotations

import asyncio
import tomllib
from pathlib import Path

import pytest
from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.interfaces.cli import root as cli_root
from autoclaw.interfaces.cli.bootstrap.config import settings_to_config_text
from autoclaw.interfaces.cli.commands import guided_setup
from autoclaw.interfaces.cli.main import build_parser
from autoclaw.interfaces.cli.providers.contracts import (
    ProviderCheckOutcome,
    ProviderCheckSnapshot,
)
from autoclaw.persistence.session import dispose_db_engine
from autoclaw.platform.provider_environment import (
    ANTHROPIC_API_KEY,
    OPENCLAW_GATEWAY_TOKEN,
    read_provider_secret_environment,
)
from autoclaw.runtime.providers import (
    ProviderAuthenticationMethod,
    ProviderCheckAxisStatus,
)
from click.testing import CliRunner

from tests.unit.cli.cli_test_support import (
    build_provider_check_snapshot,
    write_local_cli_config,
)


def test_guided_flow_requires_tty_and_explicit_human_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TerminalStream:
        def isatty(self) -> bool:
            return True

    terminal = TerminalStream()
    monkeypatch.setattr(guided_setup.sys, "stdin", terminal)
    monkeypatch.setattr(guided_setup.sys, "stdout", terminal)

    assert guided_setup.should_run_guided_flow(
        is_non_interactive=False,
        is_json_output=False,
    )
    assert not guided_setup.should_run_guided_flow(
        is_non_interactive=True,
        is_json_output=False,
    )
    assert not guided_setup.should_run_guided_flow(
        is_non_interactive=False,
        is_json_output=True,
    )


def test_guided_init_confirms_recommended_local_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    data_dir = tmp_path / "data"
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)

    result = CliRunner().invoke(
        build_parser(),
        [
            "init",
            "--config",
            str(config_path),
            "--data-dir",
            str(data_dir),
        ],
        input="y\n",
    )

    assert result.exit_code == 0, result.output
    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert payload["paths"]["data_dir"] == str(data_dir)
    assert data_dir.joinpath("autoclaw.persistence").is_file()
    assert "Use these recommended local settings?" in result.output
    assert "Next: autoclaw setup" in result.output


def test_guided_init_rerun_keeps_config_and_verifies_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    data_dir = tmp_path / "data"
    config_path.write_text(
        settings_to_config_text(
            data_dir=data_dir,
            database_url=f"sqlite+aiosqlite:///{data_dir / 'autoclaw.persistence'}",
            host="127.0.0.1",
            port=18125,
            log_level="WARNING",
        )
        + '\n[codex]\nenabled = true\n\n[runtime]\ndefault_provider = "codex"\n',
        encoding="utf-8",
    )
    previous_config = config_path.read_bytes()
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)

    try:
        result = CliRunner().invoke(
            build_parser(),
            ["init", "--config", str(config_path)],
            input="\n",
        )
    finally:
        asyncio.run(dispose_db_engine())

    assert result.exit_code == 0, result.output
    assert config_path.read_bytes() == previous_config
    assert data_dir.joinpath("autoclaw.persistence").is_file()
    assert "Keep and verify" in result.output


def test_guided_init_replacement_requires_final_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    with config_path.open("a", encoding="utf-8") as stream:
        stream.write("\n[codex]\nenabled = true\n")
    previous_config = config_path.read_bytes()
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)

    result = CliRunner().invoke(
        build_parser(),
        ["init", "--config", str(config_path)],
        input="replace\ny\nn\n",
    )

    assert result.exit_code == 0, result.output
    assert config_path.read_bytes() == previous_config
    assert "Replace the existing local config" in result.output
    assert "Cancelled" in result.output


def test_guided_setup_collects_openclaw_gateway_route_and_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    checks = iter(
        (
            build_provider_check_snapshot(
                ProviderKind.OPENCLAW,
                outcome=ProviderCheckOutcome.AUTHENTICATION_FAILED,
                is_ready=False,
                detail="openclaw_authentication_failed",
                authentication=ProviderCheckAxisStatus.FAILED,
            ),
            build_provider_check_snapshot(
                ProviderKind.OPENCLAW,
                outcome=ProviderCheckOutcome.READY,
                is_ready=True,
                detail="openclaw_experimental",
                authentication=ProviderCheckAxisStatus.PASSED,
            ),
        )
    )
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)
    monkeypatch.setattr(guided_setup, "collect_provider_check", lambda *_args: next(checks))

    result = CliRunner().invoke(
        build_parser(),
        ["setup", "--config", str(config_path), "--provider", "openclaw"],
        input="\n\n\ngateway-secret\nn\n",
    )

    assert result.exit_code == 0, result.output
    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert payload["openclaw"]["gateway_url"] == "ws://127.0.0.1:18789"
    assert payload["openclaw"]["gateway_auth_mode"] == "token"
    assert read_provider_secret_environment(config_path.parent / "autoclaw.env") == {
        OPENCLAW_GATEWAY_TOKEN: "gateway-secret"
    }
    assert "gateway-secret" not in result.output


def test_guided_setup_imports_shell_api_key_for_the_managed_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    checks = iter(
        (
            build_provider_check_snapshot(
                ProviderKind.CLAUDE,
                outcome=ProviderCheckOutcome.AUTHENTICATION_FAILED,
                is_ready=False,
                detail="claude_authentication_required",
                authentication=ProviderCheckAxisStatus.FAILED,
            ),
            build_provider_check_snapshot(
                ProviderKind.CLAUDE,
                outcome=ProviderCheckOutcome.READY,
                is_ready=True,
                detail="claude_available",
                authentication=ProviderCheckAxisStatus.PASSED,
                authentication_method=ProviderAuthenticationMethod.API_KEY,
            ),
        )
    )
    monkeypatch.setenv(ANTHROPIC_API_KEY, "shell-anthropic-secret")
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)
    monkeypatch.setattr(guided_setup, "collect_provider_check", lambda *_args: next(checks))

    result = CliRunner().invoke(
        build_parser(),
        ["setup", "--config", str(config_path), "--provider", "claude"],
        input="\n\nn\n",
    )

    assert result.exit_code == 0, result.output
    assert (
        "Existing Claude API key found in this shell. Store it for the AutoClaw service? [Y/n]"
    ) in result.output
    assert read_provider_secret_environment(config_path.parent / "autoclaw.env") == {
        ANTHROPIC_API_KEY: "shell-anthropic-secret"
    }
    assert "shell-anthropic-secret" not in result.output


def test_guided_setup_confirms_reuse_of_ready_openclaw_service_credential(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)
    monkeypatch.setattr(
        guided_setup,
        "collect_provider_check",
        lambda *_args: build_provider_check_snapshot(
            ProviderKind.OPENCLAW,
            outcome=ProviderCheckOutcome.READY,
            is_ready=True,
            detail="openclaw_experimental",
            authentication=ProviderCheckAxisStatus.PASSED,
            authentication_method=ProviderAuthenticationMethod.TOKEN,
        ),
    )
    monkeypatch.setattr(
        guided_setup,
        "invoke_provider_identity_action",
        lambda *_args, **_kwargs: pytest.fail("ready OpenClaw credential was replaced"),
    )

    result = CliRunner().invoke(
        build_parser(),
        ["setup", "--config", str(config_path), "--provider", "openclaw"],
        input="\n\n\n\nn\n",
    )

    assert result.exit_code == 0, result.output
    assert "Using existing openclaw Gateway token" in result.output
    assert (
        "Existing OpenClaw Gateway token stored for the AutoClaw service. Use it? [Y/n]"
        in result.output
    )


def test_guided_setup_adds_provider_without_replacing_primary_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    checked: list[ProviderKind] = []
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)

    def ready_check(_settings: object, provider: ProviderKind) -> ProviderCheckSnapshot:
        checked.append(provider)
        return build_provider_check_snapshot(
            provider,
            outcome=ProviderCheckOutcome.READY,
            is_ready=True,
            detail=f"{provider.value}_available",
        )

    monkeypatch.setattr(guided_setup, "collect_provider_check", ready_check)

    result = CliRunner().invoke(
        build_parser(),
        ["setup", "--config", str(config_path), "--provider", "claude"],
        input="\n\ny\nopenclaw\n\n\n\n\nn\n",
    )

    assert result.exit_code == 0, result.output
    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert payload["runtime"]["default_provider"] == "claude"
    assert payload["claude"]["enabled"] is True
    assert payload["openclaw"]["enabled"] is True
    assert checked == [ProviderKind.CLAUDE, ProviderKind.OPENCLAW]
    assert "OpenClaw is experimental" in result.output


def test_guided_setup_points_to_a_nonready_additional_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)

    def provider_state(
        _settings: object,
        provider: ProviderKind,
    ) -> ProviderCheckSnapshot:
        if provider is ProviderKind.CODEX:
            return build_provider_check_snapshot(
                provider,
                outcome=ProviderCheckOutcome.READY,
                is_ready=True,
                detail="codex_available",
                authentication=ProviderCheckAxisStatus.PASSED,
            )
        return build_provider_check_snapshot(
            provider,
            outcome=ProviderCheckOutcome.NOT_INSTALLED,
            is_ready=False,
            detail="claude_not_installed",
        )

    monkeypatch.setattr(guided_setup, "collect_provider_check", provider_state)

    result = CliRunner().invoke(
        build_parser(),
        ["setup", "--config", str(config_path), "--provider", "codex"],
        input="\n\ny\nclaude\nn\n",
    )

    assert result.exit_code == 1, result.output
    assert "claude: not_installed" in result.output
    assert "Next: autoclaw providers check claude" in result.output
    assert "Next: autoclaw serve" not in result.output


def test_guided_setup_explicit_primary_choice_replaces_existing_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    with config_path.open("a", encoding="utf-8") as stream:
        stream.write('\n[codex]\nenabled = true\n\n[runtime]\ndefault_provider = "codex"\n')
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)
    monkeypatch.setattr(
        guided_setup,
        "collect_provider_check",
        lambda _settings, provider: build_provider_check_snapshot(
            provider,
            outcome=ProviderCheckOutcome.READY,
            is_ready=True,
            detail=f"{provider.value}_available",
        ),
    )

    result = CliRunner().invoke(
        build_parser(),
        ["setup", "--config", str(config_path)],
        input="claude\n\n\nn\n",
    )

    assert result.exit_code == 0, result.output
    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert payload["codex"]["enabled"] is True
    assert payload["claude"]["enabled"] is True
    assert payload["runtime"]["default_provider"] == "claude"


def test_guided_setup_discloses_environment_default_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    with config_path.open("a", encoding="utf-8") as stream:
        stream.write('\n[codex]\nenabled = true\n\n[runtime]\ndefault_provider = "codex"\n')
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)
    monkeypatch.setattr(
        guided_setup,
        "collect_provider_check",
        lambda _settings, provider: build_provider_check_snapshot(
            provider,
            outcome=ProviderCheckOutcome.READY,
            is_ready=True,
            detail=f"{provider.value}_available",
        ),
    )

    result = CliRunner().invoke(
        build_parser(),
        ["setup", "--config", str(config_path), "--provider", "codex"],
        input="\n\nn\n",
        env={
            "AUTOCLAW_CLAUDE__ENABLED": "true",
            "AUTOCLAW_RUNTIME__DEFAULT_PROVIDER": "claude",
        },
    )

    assert result.exit_code == 0, result.output
    assert "Current default: codex" in result.output
    assert "Effective default: claude (environment override)" in result.output
    assert "Effective environment-overridden default: claude" in result.output


def test_setup_non_interactive_keeps_the_deterministic_command_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    monkeypatch.setattr(
        cli_root,
        "guide_provider_setup",
        lambda _args: pytest.fail("non-interactive setup entered the guided flow"),
    )
    monkeypatch.setattr(
        "autoclaw.interfaces.cli.commands.providers.collect_provider_check",
        lambda _settings, provider: build_provider_check_snapshot(
            provider,
            outcome=ProviderCheckOutcome.READY,
            is_ready=True,
            detail="codex_available",
            authentication=ProviderCheckAxisStatus.PASSED,
        ),
    )

    result = CliRunner().invoke(
        build_parser(),
        [
            "setup",
            "--config",
            str(config_path),
            "--provider",
            "codex",
            "--non-interactive",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert payload["runtime"]["default_provider"] == "codex"
