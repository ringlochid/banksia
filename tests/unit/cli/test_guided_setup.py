from __future__ import annotations

import asyncio
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

from banksia.interfaces.cli import root as cli_root
from banksia.interfaces.cli.bootstrap.config import (
    build_initial_config_sections,
    config_sections_to_text,
)
from banksia.interfaces.cli.commands import provider_setup as guided_provider_setup
from banksia.interfaces.cli.commands import settings as guided_setup
from banksia.interfaces.cli.main import build_parser
from banksia.interfaces.cli.providers import inspection as provider_inspection
from banksia.interfaces.cli.providers.contracts import (
    ProviderCheckOutcome,
    ProviderCheckSnapshot,
)
from banksia.persistence.session import dispose_db_engine
from banksia.platform.provider_environment import (
    ANTHROPIC_API_KEY,
    OPENCLAW_GATEWAY_TOKEN,
    read_provider_secret_environment,
)
from banksia.providers import ProviderKind
from banksia.runtime.providers import (
    ProviderAuthenticationMethod,
    ProviderCheckAxisStatus,
    ProviderCheckResult,
    ProviderCheckStatus,
)
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
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
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
        input="\ny\ncancel\n\n",
    )

    assert result.exit_code == 0, result.output
    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert payload["paths"]["data_dir"] == str(data_dir)
    assert payload["paths"]["workspace"] == str(workspace)
    assert data_dir.joinpath("banksia.persistence").is_file()
    assert "Default workspace" in result.output
    assert "Use these recommended local settings?" in result.output
    assert "Banksia Task provider setup" in result.output
    assert "Provider to configure (codex, claude, openclaw, cancel)" in result.output
    assert "Provider setup cancelled. No provider changes were made." in result.output
    assert "Operator provider (Codex, Claude, Not now)" in result.output
    assert result.output.count("Initialization complete") == 1
    assert "Local initialization complete" not in result.output
    assert "Provider setup summary" not in result.output


def test_guided_init_runs_provider_diagnostic_outside_database_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)
    monkeypatch.setattr(
        provider_inspection,
        "is_provider_integration_available",
        lambda *_args: True,
    )

    def run_diagnostic(
        _settings: object,
        provider: ProviderKind,
    ) -> ProviderCheckResult:
        async def read_result() -> ProviderCheckResult:
            return ProviderCheckResult(
                kind=provider,
                status=ProviderCheckStatus.AVAILABLE,
                code="codex_available",
                authentication=ProviderCheckAxisStatus.PASSED,
                authentication_method=ProviderAuthenticationMethod.SUBSCRIPTION,
            )

        return asyncio.run(read_result())

    monkeypatch.setattr(
        provider_inspection,
        "execute_provider_diagnostic",
        run_diagnostic,
    )

    result = CliRunner().invoke(
        build_parser(),
        [
            "init",
            "--config",
            str(config_path),
            "--data-dir",
            str(data_dir),
        ],
        input="\ny\ncodex\n\ny\nn\ncodex\nn\n",
    )

    assert result.exit_code == 0, result.output
    output = result.output.casefold()
    assert "credential" in output
    assert "found" in output
    assert "codex" in output
    assert "ready" in output
    assert "check_failed" not in output
    assert tomllib.loads(config_path.read_text(encoding="utf-8"))["operator"] == {
        "provider": "codex"
    }
    assert result.output.count("Initialization complete") == 1
    assert "Local initialization complete" not in result.output
    assert "Provider setup summary" not in result.output
    assert "Operator setup complete" not in result.output
    assert result.output.count("Next: banksia serve") == 1


def test_guided_init_rerun_keeps_config_and_verifies_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    data_dir = tmp_path / "data"
    config_path.write_text(
        config_sections_to_text(
            build_initial_config_sections(
                data_dir=data_dir,
                database_url=f"sqlite+aiosqlite:///{data_dir / 'banksia.persistence'}",
                host="127.0.0.1",
                port=18125,
                log_level="WARNING",
            )
        )
        + (
            '\n[codex]\nenabled = true\n\n[operator]\nprovider = "codex"\n\n'
            '[runtime]\ndefault_provider = "codex"\n'
        ),
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
    assert data_dir.joinpath("banksia.persistence").is_file()
    assert "Keep and verify" in result.output
    assert "Banksia Task provider setup" not in result.output
    assert "optional Operator setup" not in result.output
    assert "banksia serve" in result.output


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
        input="replace\n\ny\nn\n",
    )

    assert result.exit_code == 0, result.output
    assert config_path.read_bytes() == previous_config
    assert "Replace the existing local config" in result.output
    assert "Cancelled" in result.output


def test_guided_init_replacement_preserves_provider_and_operator_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    replacement_data_dir = tmp_path / "replacement-data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with config_path.open("a", encoding="utf-8") as stream:
        stream.write(
            '\n[codex]\nenabled = true\nmodel = "task-model"\n'
            '\n[claude]\nenabled = true\neffort = "high"\n'
            '\n[operator]\nprovider = "claude"\nmodel = "operator-model"\neffort = "medium"\n'
            '\n[runtime]\ndefault_provider = "codex"\n'
        )
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)

    result = CliRunner().invoke(
        build_parser(),
        [
            "init",
            "--config",
            str(config_path),
            "--data-dir",
            str(replacement_data_dir),
            "--port",
            "19191",
            "--skip-db-upgrade",
        ],
        input="replace\n\ny\ny\n",
    )

    assert result.exit_code == 0, result.output
    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert payload["paths"]["data_dir"] == str(replacement_data_dir)
    assert payload["paths"]["workspace"] == str(workspace)
    assert payload["server"]["port"] == 19191
    assert payload["codex"] == {"enabled": True, "model": "task-model"}
    assert payload["claude"] == {"enabled": True, "effort": "high"}
    assert payload["operator"] == {
        "provider": "claude",
        "model": "operator-model",
        "effort": "medium",
    }
    assert payload["runtime"] == {"default_provider": "codex"}
    assert "Banksia Task provider setup" not in result.output
    assert "optional Operator setup" not in result.output


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
    monkeypatch.setattr(
        guided_provider_setup,
        "collect_provider_check",
        lambda *_args: next(checks),
    )

    result = CliRunner().invoke(
        build_parser(),
        ["setup", "--config", str(config_path), "--provider", "openclaw"],
        input="\n\n\ngateway-secret\nn\n",
    )

    assert result.exit_code == 0, result.output
    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert payload["openclaw"]["gateway_url"] == "ws://127.0.0.1:18789"
    assert payload["openclaw"]["gateway_auth_mode"] == "token"
    assert read_provider_secret_environment(config_path.parent / "banksia.env") == {
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
    monkeypatch.setattr(
        guided_provider_setup,
        "collect_provider_check",
        lambda *_args: next(checks),
    )

    result = CliRunner().invoke(
        build_parser(),
        ["setup", "--config", str(config_path), "--provider", "claude"],
        input="\n\nn\n",
    )

    assert result.exit_code == 0, result.output
    assert (
        "Existing Claude API key found in this shell. Store it for the Banksia service? [Y/n]"
    ) in result.output
    assert read_provider_secret_environment(config_path.parent / "banksia.env") == {
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
        guided_provider_setup,
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
        guided_provider_setup,
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
        "Existing OpenClaw Gateway token stored for the Banksia service. Use it? [Y/n]"
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

    monkeypatch.setattr(
        guided_provider_setup,
        "collect_provider_check",
        ready_check,
    )

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

    monkeypatch.setattr(
        guided_provider_setup,
        "collect_provider_check",
        provider_state,
    )

    result = CliRunner().invoke(
        build_parser(),
        ["setup", "--config", str(config_path), "--provider", "codex"],
        input="\n\ny\nclaude\nn\n",
    )

    assert result.exit_code == 1, result.output
    assert "claude: not_installed" in result.output
    assert "Next: banksia providers check claude" in result.output
    assert "Next: banksia serve" not in result.output


def test_guided_setup_explicit_provider_preserves_existing_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    with config_path.open("a", encoding="utf-8") as stream:
        stream.write('\n[codex]\nenabled = true\n\n[runtime]\ndefault_provider = "codex"\n')
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)
    monkeypatch.setattr(
        guided_provider_setup,
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
        ["setup", "--config", str(config_path), "--provider", "claude"],
        input="\n\nn\n",
    )

    assert result.exit_code == 0, result.output
    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert payload["codex"]["enabled"] is True
    assert payload["claude"]["enabled"] is True
    assert payload["runtime"]["default_provider"] == "codex"


def test_guided_setup_discloses_environment_default_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    with config_path.open("a", encoding="utf-8") as stream:
        stream.write('\n[codex]\nenabled = true\n\n[runtime]\ndefault_provider = "codex"\n')
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)
    monkeypatch.setattr(
        guided_provider_setup,
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
            "BANKSIA_CLAUDE__ENABLED": "true",
            "BANKSIA_RUNTIME__DEFAULT_PROVIDER": "claude",
        },
    )

    assert result.exit_code == 0, result.output
    assert "Current default: codex" in result.output
    assert "Effective default: claude (environment override)" in result.output
    assert "Effective environment-overridden default: claude" in result.output


def test_guided_setup_routes_through_workspace_and_returns_to_hub(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = write_local_cli_config(tmp_path)
    workspace = tmp_path / "selected-workspace"
    workspace.mkdir()
    monkeypatch.setattr(cli_root, "should_run_guided_flow", lambda **_kwargs: True)

    result = CliRunner().invoke(
        build_parser(),
        ["setup", "--config", str(config_path)],
        input=f"Default workspace\n{workspace}\nDone\n",
    )

    assert result.exit_code == 0, result.output
    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert payload["paths"]["workspace"] == str(workspace)
    assert "Task providers" in result.output
    assert "Operator" in result.output
    assert "Default workspace updated" in result.output
