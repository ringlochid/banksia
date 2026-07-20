from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import cast

import autoclaw.interfaces.cli as cli
import pytest
from autoclaw.platform.provider_environment import ANTHROPIC_API_KEY, persist_provider_secret
from click import Group
from click.testing import CliRunner


def test_build_parser_supports_baseline_commands() -> None:
    parser = cli.build_parser()
    runner = CliRunner()

    result = runner.invoke(parser, ["--help"])
    init_help = runner.invoke(parser, ["init", "--help"])
    setup_help = runner.invoke(parser, ["setup", "--help"])
    service_install_help = runner.invoke(parser, ["service", "install", "--help"])
    service_start_help = runner.invoke(parser, ["service", "start", "--help"])

    assert result.exit_code == 0
    assert init_help.exit_code == 0
    assert setup_help.exit_code == 0
    assert service_install_help.exit_code == 0
    assert "onboard" not in parser.commands
    assert "configure" not in parser.commands
    assert "doctor" not in parser.commands
    assert "--port INTEGER" in service_install_help.output
    assert "--data-dir" not in service_install_help.output
    assert "--env-file" not in service_install_help.output
    assert "--force" not in service_install_help.output
    assert "--config" not in service_start_help.output
    assert "--non-interactive" in init_help.output
    assert "--non-interactive" in setup_help.output
    assert "--provider [codex|claude|openclaw]" in setup_help.output
    assert "openclaw" not in parser.commands
    assert "status" in parser.commands
    assert "setup" in parser.commands
    assert "providers" in parser.commands
    assert "service" in parser.commands
    assert "definitions" in parser.commands
    assert "task-compose" in parser.commands
    service_group = cast(Group, parser.commands["service"])
    definitions_group = cast(Group, parser.commands["definitions"])
    task_compose_group = cast(Group, parser.commands["task-compose"])
    providers_group = cast(Group, parser.commands["providers"])
    assert "install" in service_group.commands
    assert "status" in service_group.commands
    assert "import" in definitions_group.commands
    assert "start" in task_compose_group.commands
    assert set(providers_group.commands) == {
        "check",
        "configure",
        "list",
        "login",
        "logout",
        "set-default",
        "status",
    }


def test_render_service_unit_uses_python_module_entrypoint(tmp_path: Path) -> None:
    rendered = cli.render_service_unit(
        python_bin=Path("/tmp/autoclaw-venv/bin/python"),
        config_path=tmp_path / "config.toml",
    )

    assert "openclaw check" not in rendered
    assert 'ExecStartPre="/tmp/autoclaw-venv/bin/python" -m autoclaw db upgrade' in rendered
    assert 'ExecStart="/tmp/autoclaw-venv/bin/python" -m autoclaw serve' in rendered
    assert "AUTOCLAW_DATA_DIR" not in rendered
    assert "UnsetEnvironment=CODEX_HOME CLAUDE_CONFIG_DIR OPENCLAW_STATE_DIR" in rendered


def test_render_service_unit_quotes_spaces_and_systemd_specifiers(tmp_path: Path) -> None:
    rendered = cli.render_service_unit(
        python_bin=tmp_path / "venv with space" / "python%bin",
        config_path=tmp_path / "config with space%" / "config.toml",
    )

    assert f'ExecStart="{tmp_path}/venv with space/python%%bin"' in rendered
    assert f'--config "{tmp_path}/config with space%%/config.toml"' in rendered
    assert f"EnvironmentFile=-{tmp_path}/config\\x20with\\x20space%%/autoclaw.env" in rendered


def test_serve_does_not_run_global_provider_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "autoclaw-config.toml"
    config_path.write_text(
        """
[openclaw]
enabled = true
gateway_url = "not-a-websocket-url"
gateway_profile = "experimental"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    run_called = False
    persist_provider_secret(
        tmp_path / "autoclaw.env",
        key=ANTHROPIC_API_KEY,
        value="stored-api-key",
    )
    monkeypatch.delenv(ANTHROPIC_API_KEY, raising=False)

    def unexpected_uvicorn_run(*args: object, **kwargs: object) -> None:
        nonlocal run_called
        run_called = True
        assert os.environ[ANTHROPIC_API_KEY] == "stored-api-key"

    monkeypatch.setattr("uvicorn.run", unexpected_uvicorn_run)

    result = cli.cmd_serve(argparse.Namespace(config=str(config_path)))

    assert result == 0
    assert run_called is True
    assert ANTHROPIC_API_KEY not in os.environ
    assert "preflight" not in capsys.readouterr().out.casefold()
