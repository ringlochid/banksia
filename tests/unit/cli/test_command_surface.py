from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import cast

import pytest
from click import Group
from click.testing import CliRunner

import oh_my_subagents.interfaces.cli as cli
from oh_my_subagents.platform.managed_services import SystemdUserServiceManager
from oh_my_subagents.platform.provider_environment import ANTHROPIC_API_KEY, persist_provider_secret


def test_build_parser_supports_baseline_commands() -> None:
    parser = cli.build_parser()
    runner = CliRunner()

    result = runner.invoke(parser, ["--help"])
    init_help = runner.invoke(parser, ["init", "--help"])
    setup_help = runner.invoke(parser, ["setup", "--help"])
    operator_setup_help = runner.invoke(parser, ["operator", "setup", "--help"])
    service_install_help = runner.invoke(parser, ["service", "install", "--help"])
    service_start_help = runner.invoke(parser, ["service", "start", "--help"])

    assert result.exit_code == 0
    assert init_help.exit_code == 0
    assert setup_help.exit_code == 0
    assert operator_setup_help.exit_code == 0
    assert service_install_help.exit_code == 0
    assert "Oh My Subagents: durable supervision for accountable AI teams." in result.output
    assert "onboard" not in parser.commands
    assert "configure" not in parser.commands
    assert "doctor" not in parser.commands
    assert "--port" not in service_install_help.output
    assert "--data-dir" not in service_install_help.output
    assert "--env-file" not in service_install_help.output
    assert "--force" not in service_install_help.output
    assert "--config" in service_start_help.output
    assert "--non-interactive" in init_help.output
    assert "--non-interactive" in setup_help.output
    assert "--provider [codex|claude]" in setup_help.output
    assert "--provider [codex|claude]" in operator_setup_help.output
    assert "openclaw" not in parser.commands
    assert "status" in parser.commands
    assert "setup" in parser.commands
    assert "providers" in parser.commands
    assert "operator" in parser.commands
    assert "service" in parser.commands
    assert "workflow" in parser.commands
    assert "task" in parser.commands
    assert "task-compose" not in parser.commands
    service_group = cast(Group, parser.commands["service"])
    workflow_group = cast(Group, parser.commands["workflow"])
    task_group = cast(Group, parser.commands["task"])
    providers_group = cast(Group, parser.commands["providers"])
    operator_group = cast(Group, parser.commands["operator"])
    assert "install" in service_group.commands
    assert "status" in service_group.commands
    assert set(workflow_group.commands) == {"import", "export"}
    assert set(task_group.commands) == {"start"}
    assert set(providers_group.commands) == {
        "check",
        "configure",
        "list",
        "login",
        "logout",
        "set-default",
        "status",
    }
    assert set(operator_group.commands) == {"disable", "setup", "status"}


def test_parse_failure_directs_users_to_the_canonical_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["serve", "127.0.0.1:18125"]) == 2

    output = capsys.readouterr().out
    assert "Try: oms serve 127.0.0.1:18125 --help" in output
    assert "Try: banksia" not in output


@pytest.mark.skipif(os.name == "nt", reason="systemd definitions use POSIX paths")
def test_render_service_definition_uses_python_module_entrypoint(
    tmp_path: Path,
) -> None:
    rendered = cli.render_service_definition(
        python_executable=Path("/tmp/oms-venv/bin/python"),
        config_path=tmp_path / "config.toml",
        log_path=tmp_path / "controller.log",
        manager=SystemdUserServiceManager(),
    )

    assert "openclaw check" not in rendered
    assert 'ExecStart="/tmp/oms-venv/bin/python" -m oh_my_subagents serve' in rendered
    assert f'--service-log "{tmp_path}/controller.log"' in rendered
    assert "KillMode=control-group" in rendered
    assert "OMS_DATA_DIR" not in rendered
    assert "EnvironmentFile=" not in rendered


@pytest.mark.skipif(os.name == "nt", reason="systemd definitions use POSIX paths")
def test_render_service_definition_quotes_spaces_and_systemd_specifiers(
    tmp_path: Path,
) -> None:
    rendered = cli.render_service_definition(
        python_executable=tmp_path / "venv with space" / "python%bin",
        config_path=tmp_path / "config with space%" / "config.toml",
        log_path=tmp_path / "log with space%" / "controller.log",
        manager=SystemdUserServiceManager(),
    )

    assert f'ExecStart="{tmp_path}/venv with space/python%%bin"' in rendered
    assert f'--config "{tmp_path}/config with space%%/config.toml"' in rendered
    assert f'--service-log "{tmp_path}/log with space%%/controller.log"' in rendered


def test_serve_does_not_run_global_provider_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "oms-config.toml"
    config_path.write_text("[codex]\nenabled = true\n", encoding="utf-8")
    run_called = False
    persist_provider_secret(
        tmp_path / "oms.env",
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
