from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

import pytest

import banksia.interfaces.cli as cli
import banksia.interfaces.cli.commands.service as service_commands
from banksia.interfaces.cli.errors import unexpected_failure
from banksia.platform.managed_services import (
    ManagedServiceCommandError,
    ManagedServiceControllerState,
    ManagedServiceExecutionState,
    ManagedServiceInspection,
    ManagedServiceInstallationState,
    ManagedServiceResult,
    ManagedServiceStartupState,
    ManagedServiceTarget,
)


class StubManagedServiceManager:
    manager_name = "test-user-manager"
    service_name = "banksia"
    readiness_timeout_seconds = 0.0

    def __init__(self, inspection: ManagedServiceInspection) -> None:
        self.inspection = inspection
        self.operations: list[str] = []

    def render_definition(self, target: ManagedServiceTarget) -> str:
        return (
            f"python={target.python_executable}\n"
            f"config={target.config_path}\n"
            f"log={target.log_path}\n"
        )

    def inspect(self, target: ManagedServiceTarget) -> ManagedServiceInspection:
        del target
        return self.inspection

    def start(self, target: ManagedServiceTarget, **kwargs: object) -> ManagedServiceInspection:
        del target, kwargs
        self.operations.append("start")
        self.inspection = self.inspection.with_execution_state(ManagedServiceExecutionState.RUNNING)
        return self.inspection

    def stop(self, target: ManagedServiceTarget, **kwargs: object) -> ManagedServiceInspection:
        del target, kwargs
        self.operations.append("stop")
        self.inspection = self.inspection.with_execution_state(ManagedServiceExecutionState.STOPPED)
        return self.inspection


def test_service_status_uses_product_language_and_controller_truth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = _write_config(tmp_path, port=65534)
    manager = StubManagedServiceManager(_installed_stopped_inspection(tmp_path))
    monkeypatch.setattr(
        service_commands,
        "get_managed_service_manager",
        lambda: manager,
    )

    result = cli.cmd_service_status(argparse.Namespace(config=str(config_path), json=False))

    output = capsys.readouterr().out
    assert result == 0
    assert "Banksia background service" in output
    assert "Definition:" in output
    assert "Starts at sign-in: Enabled" in output
    assert "Controller: stopped" in output
    assert "Log:" in output
    assert "systemd state" not in output
    assert "journalctl" not in output


def test_service_status_json_uses_portable_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = _write_config(tmp_path, port=65533)
    manager = StubManagedServiceManager(_installed_stopped_inspection(tmp_path))
    monkeypatch.setattr(
        service_commands,
        "get_managed_service_manager",
        lambda: manager,
    )

    result = cli.cmd_service_status(argparse.Namespace(config=str(config_path), json=True))

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload == {
        "api_url": "http://127.0.0.1:65533",
        "controller_state": "stopped",
        "definition_current": True,
        "definition_path": str(tmp_path / "banksia.definition"),
        "installation_state": "installed",
        "log_path": str(service_commands.default_service_log_path()),
        "manager": "test-user-manager",
        "ok": True,
        "service_name": "banksia",
        "startup_state": "enabled",
    }
    assert "active_state" not in payload
    assert "fragment_path" not in payload
    assert "healthy" not in payload


def test_service_status_exposes_an_outdated_definition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = _write_config(tmp_path, port=65531)
    outdated = replace(
        _installed_stopped_inspection(tmp_path),
        is_definition_current=False,
    )
    monkeypatch.setattr(
        service_commands,
        "get_managed_service_manager",
        lambda: StubManagedServiceManager(outdated),
    )

    result = cli.cmd_service_status(argparse.Namespace(config=str(config_path), json=False))

    output = capsys.readouterr().out
    assert result == 0
    assert "needs reinstall" in output.casefold()
    assert "Definition: Out of date" in output
    assert "banksia service install" in output


def test_failed_service_status_directs_the_operator_to_bounded_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = _write_config(tmp_path, port=65532)
    failed = _installed_stopped_inspection(tmp_path).with_execution_state(
        ManagedServiceExecutionState.FAILED
    )
    monkeypatch.setattr(
        service_commands,
        "get_managed_service_manager",
        lambda: StubManagedServiceManager(failed),
    )

    result = cli.cmd_service_status(argparse.Namespace(config=str(config_path), json=False))

    output = capsys.readouterr().out
    assert result == 0
    assert "needs attention" in output.casefold()
    assert "banksia service logs --lines 200" in output


def test_service_render_uses_selected_native_definition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config with space" / "config.toml"
    manager = StubManagedServiceManager(_installed_stopped_inspection(tmp_path))
    monkeypatch.setattr(
        service_commands,
        "get_managed_service_manager",
        lambda: manager,
    )

    result = cli.cmd_service_render(argparse.Namespace(config=str(config_path)))

    output = capsys.readouterr().out
    assert result == 0
    assert f"config={config_path.resolve()}" in output
    assert "log=" in output


def test_service_restart_releases_the_bind_target_before_starting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = _write_config(tmp_path, port=65530)
    manager = StubManagedServiceManager(_installed_stopped_inspection(tmp_path))
    events = manager.operations
    monkeypatch.setattr(service_commands, "get_managed_service_manager", lambda: manager)

    def wait_for_shutdown(**kwargs: object) -> ManagedServiceResult:
        events.append("release")
        inspection = kwargs["initial_inspection"]
        assert isinstance(inspection, ManagedServiceInspection)
        return _service_result(inspection, tmp_path, ManagedServiceControllerState.STOPPED)

    def build_start_result(**kwargs: object) -> ManagedServiceResult:
        events.append("readiness")
        inspection = kwargs["inspection"]
        assert isinstance(inspection, ManagedServiceInspection)
        return _service_result(inspection, tmp_path, ManagedServiceControllerState.READY)

    monkeypatch.setattr(service_commands, "wait_for_controller_shutdown", wait_for_shutdown)
    monkeypatch.setattr(service_commands, "_build_result", build_start_result)

    result = cli.cmd_service_restart(argparse.Namespace(config=str(config_path), json=True))

    assert result == 0
    assert events == ["stop", "release", "start", "readiness"]
    assert json.loads(capsys.readouterr().out)["controller_state"] == "ready"


def test_service_target_preserves_the_active_environment_interpreter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment_python = tmp_path / "venv" / "bin" / "python"
    environment_python.parent.mkdir(parents=True)
    environment_python.symlink_to("/usr/bin/python3")
    monkeypatch.setattr(service_commands.sys, "executable", str(environment_python))

    target = service_commands.build_managed_service_target(tmp_path / "config.toml")

    assert target.python_executable == environment_python


def test_service_logs_returns_a_bounded_tail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    log_path = tmp_path / "controller.log"
    log_path.write_text("one\ntwo\nthree\n", encoding="utf-8")
    monkeypatch.setattr(service_commands, "default_service_log_path", lambda: log_path)

    result = cli.cmd_service_logs(argparse.Namespace(lines=2, follow=False, json=True))

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload == {
        "is_missing": False,
        "lines": ["two", "three"],
        "log_path": str(log_path),
        "ok": True,
    }


def test_service_logs_rejects_unbounded_line_request() -> None:
    with pytest.raises(ValueError, match="between 1 and 2000"):
        cli.cmd_service_logs(argparse.Namespace(lines=2_001, follow=False, json=False))


def test_service_command_failure_is_manager_neutral() -> None:
    failure = unexpected_failure(
        ManagedServiceCommandError(
            manager="launchd-user",
            operation="start",
            service_name="io.github.ringlochid.banksia",
            command=("launchctl", "kickstart", "gui/501/io.github.ringlochid.banksia"),
            return_code=5,
            detail="service is disabled",
        )
    )

    assert failure.title == "Background service start failed"
    assert "operating system could not start" in failure.message
    assert "service is disabled" in failure.message
    assert failure.hint is not None
    assert "banksia service status" in failure.hint
    assert "banksia service logs --lines 200" in failure.hint
    assert "systemctl" not in failure.hint
    assert failure.details["manager"] == "launchd-user"


def _write_config(tmp_path: Path, *, port: int) -> Path:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[server]",
                'host = "127.0.0.1"',
                f"port = {port}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return config_path


def _installed_stopped_inspection(tmp_path: Path) -> ManagedServiceInspection:
    return ManagedServiceInspection(
        manager="test-user-manager",
        service_name="banksia",
        definition_path=tmp_path / "banksia.definition",
        installation_state=ManagedServiceInstallationState.INSTALLED,
        startup_state=ManagedServiceStartupState.ENABLED,
        execution_state=ManagedServiceExecutionState.STOPPED,
        is_definition_current=True,
    )


def _service_result(
    inspection: ManagedServiceInspection,
    tmp_path: Path,
    controller_state: ManagedServiceControllerState,
) -> ManagedServiceResult:
    return ManagedServiceResult(
        inspection=inspection,
        controller_state=controller_state,
        api_url="http://127.0.0.1:65530",
        log_path=tmp_path / "controller.log",
    )
