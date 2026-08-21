from __future__ import annotations

import logging
import os
import plistlib
from pathlib import Path

import pytest

import banksia.platform.managed_services.launchd as launchd_module
import banksia.platform.managed_services.systemd as systemd_module
from banksia.config import Settings
from banksia.platform.managed_services import (
    LAUNCHD_SERVICE_NAME,
    SERVICE_LOGGER_NAME,
    ManagedServiceCommandError,
    ManagedServiceControllerState,
    ManagedServiceExecutionState,
    ManagedServiceInspection,
    ManagedServiceInstallationState,
    ManagedServiceStartupState,
    ManagedServiceTarget,
    SystemdUserServiceManager,
    build_managed_service_result,
    configure_service_logging,
    get_managed_service_manager,
    parse_launchctl_print,
    probe_controller_state,
    wait_for_controller_shutdown,
    wait_for_controller_state,
)
from banksia.platform.managed_services.definition_files import (
    replace_service_definition,
)
from banksia.platform.managed_services.launchd import LaunchdUserServiceManager


def test_manager_selection_rejects_unknown_hosts() -> None:
    assert type(get_managed_service_manager(platform_name="Linux")).__name__ == (
        "SystemdUserServiceManager"
    )
    assert type(get_managed_service_manager(platform_name="Darwin")).__name__ == (
        "LaunchdUserServiceManager"
    )
    assert type(get_managed_service_manager(platform_name="Windows")).__name__ == (
        "ScheduledTaskUserServiceManager"
    )
    with pytest.raises(RuntimeError, match=r"Linux, macOS, and Windows only.*native FreeBSD"):
        get_managed_service_manager(platform_name="FreeBSD")


def test_systemd_definition_is_fixed_and_service_scoped(tmp_path: Path) -> None:
    target = _target_with_special_paths(tmp_path)
    rendered = SystemdUserServiceManager(
        definition_dir=tmp_path / "units",
    ).render_definition(target)

    assert 'ExecStart="' in rendered
    assert "-m banksia serve" in rendered
    assert "--service-log" in rendered
    assert "KillMode=control-group" in rendered
    assert "UMask=" not in rendered
    assert "EnvironmentFile=" not in rendered
    assert "ExecStartPre=" not in rendered
    assert "python%%bin" in rendered
    assert "config %% with space" in rendered


def test_systemd_manager_reconciles_one_fixed_unit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name != "posix":
        pytest.skip("fake systemd executable requires POSIX process semantics")
    command_log = tmp_path / "systemctl.log"
    systemctl = tmp_path / "systemctl"
    _write_fake_systemctl(systemctl, command_log)
    monkeypatch.setattr(systemd_module.sys, "platform", "linux")
    target = _target(tmp_path)
    manager = SystemdUserServiceManager(
        definition_dir=tmp_path / "units",
        systemctl_bin=str(systemctl),
    )

    installed = manager.install(target, should_start=True)
    stopped = manager.stop(target)
    removed = manager.uninstall(target)

    assert installed.installation_state is ManagedServiceInstallationState.INSTALLED
    assert stopped.execution_state is ManagedServiceExecutionState.STOPPED
    assert removed.installation_state is ManagedServiceInstallationState.ABSENT
    commands = command_log.read_text(encoding="utf-8").splitlines()
    assert "daemon-reload" in commands
    assert "enable banksia.service" in commands
    assert "restart banksia.service" in commands
    assert "stop banksia.service" in commands
    assert "disable --now banksia.service" in commands
    assert not manager.definition_path.exists()


def test_systemd_crash_loop_is_failed_instead_of_indefinitely_starting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name != "posix":
        pytest.skip("fake systemd executable requires POSIX process semantics")
    systemctl = tmp_path / "systemctl"
    systemctl.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                "echo LoadState=loaded",
                "echo UnitFileState=enabled",
                "echo ActiveState=activating",
                "echo SubState=auto-restart",
                "echo Result=exit-code",
                "echo ExecMainCode=1",
                "echo ExecMainStatus=1",
                "echo NRestarts=25",
                f"echo FragmentPath={tmp_path / 'units' / 'banksia.service'}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
    monkeypatch.setattr(systemd_module.sys, "platform", "linux")
    manager = SystemdUserServiceManager(
        definition_dir=tmp_path / "units",
        systemctl_bin=str(systemctl),
    )

    inspection = manager.inspect(_target(tmp_path))

    assert inspection.execution_state is ManagedServiceExecutionState.FAILED
    assert dict(inspection.technical_state) == {
        "LoadState": "loaded",
        "UnitFileState": "enabled",
        "ActiveState": "activating",
        "SubState": "auto-restart",
        "Result": "exit-code",
        "ExecMainCode": "1",
        "ExecMainStatus": "1",
        "NRestarts": "25",
    }


@pytest.mark.parametrize(
    "transient_state",
    (
        ManagedServiceExecutionState.FAILED,
        ManagedServiceExecutionState.STOPPED,
    ),
)
def test_readiness_poll_recovers_from_a_transient_native_state(
    tmp_path: Path,
    transient_state: ManagedServiceExecutionState,
) -> None:
    inspections = iter(
        (
            _inspection(transient_state),
            _inspection(ManagedServiceExecutionState.RUNNING),
        )
    )
    inspection_count = 0

    def inspect() -> ManagedServiceInspection:
        nonlocal inspection_count
        inspection_count += 1
        return next(inspections)

    result = wait_for_controller_state(
        initial_inspection=_inspection(ManagedServiceExecutionState.STARTING),
        inspect=inspect,
        settings=Settings(),
        log_path=tmp_path / "controller.log",
        timeout_seconds=1,
        interval_seconds=0,
        probe=lambda host, port, state: (
            ManagedServiceControllerState.READY
            if state is ManagedServiceExecutionState.RUNNING
            else ManagedServiceControllerState(state.value)
        ),
    )

    assert inspection_count == 2
    assert result.inspection.execution_state is ManagedServiceExecutionState.RUNNING
    assert result.controller_state is ManagedServiceControllerState.READY


def test_shutdown_waits_for_the_native_instance_and_bind_target(tmp_path: Path) -> None:
    inspections = iter((_inspection(ManagedServiceExecutionState.STOPPED),))
    listening = iter((True, False))
    inspection_count = 0

    def inspect() -> ManagedServiceInspection:
        nonlocal inspection_count
        inspection_count += 1
        return next(inspections)

    result = wait_for_controller_shutdown(
        initial_inspection=_inspection(ManagedServiceExecutionState.STOPPED),
        inspect=inspect,
        settings=Settings(api_port=65534),
        log_path=tmp_path / "controller.log",
        timeout_seconds=1,
        interval_seconds=0,
        is_bind_target_listening=lambda host, port: next(listening),
    )

    assert inspection_count == 1
    assert result.inspection.execution_state is ManagedServiceExecutionState.STOPPED
    assert result.controller_state is ManagedServiceControllerState.STOPPED


def test_shutdown_rejects_a_lingering_bind_target(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match=r"API bind target 127\.0\.0\.1:65534 remained in use"):
        wait_for_controller_shutdown(
            initial_inspection=_inspection(ManagedServiceExecutionState.STOPPED),
            inspect=lambda: _inspection(ManagedServiceExecutionState.STOPPED),
            settings=Settings(api_port=65534),
            log_path=tmp_path / "controller.log",
            timeout_seconds=0,
            is_bind_target_listening=lambda host, port: True,
        )


def test_ready_endpoint_does_not_override_stopped_native_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import banksia.platform.managed_services.controller_status as controller_status_module

    monkeypatch.setattr(controller_status_module, "_read_health_status", lambda *args: 200)

    state = probe_controller_state(
        "127.0.0.1",
        18125,
        ManagedServiceExecutionState.STOPPED,
    )

    assert state is ManagedServiceControllerState.STOPPED


def test_bind_target_ownership_requires_an_active_native_service(tmp_path: Path) -> None:
    def ready_probe(
        host: str, port: int, state: ManagedServiceExecutionState
    ) -> ManagedServiceControllerState:
        del host, port, state
        return ManagedServiceControllerState.READY

    running = build_managed_service_result(
        inspection=_inspection(ManagedServiceExecutionState.RUNNING),
        settings=Settings(),
        log_path=tmp_path / "controller.log",
        probe=ready_probe,
    )
    stopped = build_managed_service_result(
        inspection=_inspection(ManagedServiceExecutionState.STOPPED),
        settings=Settings(),
        log_path=tmp_path / "controller.log",
        probe=ready_probe,
    )

    assert running.owns_bind_target is True
    assert stopped.owns_bind_target is False


def test_service_lifecycle_log_survives_warning_application_threshold(tmp_path: Path) -> None:
    logger_names = ("", SERVICE_LOGGER_NAME, "uvicorn", "uvicorn.error", "uvicorn.access")
    logger_state = {
        name: (
            list(logging.getLogger(name).handlers),
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
        )
        for name in logger_names
    }
    log_path = tmp_path / "controller.log"
    try:
        configure_service_logging(log_path, level="WARNING")
        logging.getLogger(SERVICE_LOGGER_NAME).info("background controller starting")
        for handler in logging.getLogger().handlers:
            handler.flush()
    finally:
        configured_handlers = list(logging.getLogger().handlers)
        for name, (handlers, level, propagate) in logger_state.items():
            logger = logging.getLogger(name)
            logger.handlers.clear()
            logger.handlers.extend(handlers)
            logger.setLevel(level)
            logger.propagate = propagate
        for handler in configured_handlers:
            handler.close()

    assert "INFO banksia.service background controller starting" in log_path.read_text(
        encoding="utf-8"
    )


def test_atomic_definition_replacement_rejects_a_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.write_text("unchanged", encoding="utf-8")
    definition = tmp_path / "banksia.service"
    definition.symlink_to(outside)

    with pytest.raises(RuntimeError, match="regular file"):
        replace_service_definition(definition, b"replacement")

    assert outside.read_text(encoding="utf-8") == "unchanged"
    assert definition.is_symlink()


def test_launch_agent_definition_has_only_the_bounded_user_job_contract(
    tmp_path: Path,
) -> None:
    target = _target_with_special_paths(tmp_path)
    manager = LaunchdUserServiceManager(
        definition_dir=tmp_path / "Launch Agents",
        user_id=501,
    )

    definition = plistlib.loads(manager.render_definition(target).encode("utf-8"))

    assert definition == {
        "Label": LAUNCHD_SERVICE_NAME,
        "ProgramArguments": [
            str(target.python_executable),
            "-m",
            "banksia",
            "serve",
            "--config",
            str(target.config_path),
            "--service-log",
            str(target.log_path),
        ],
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 5,
    }
    assert "ProcessType" not in definition
    assert "Umask" not in definition
    assert "EnvironmentVariables" not in definition


def test_launch_agent_lifecycle_uses_current_gui_domain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name != "posix":
        pytest.skip("fake launchctl executable requires POSIX process semantics")
    command_log = tmp_path / "launchctl.log"
    loaded_marker = tmp_path / "loaded"
    launchctl = tmp_path / "launchctl"
    _write_fake_launchctl(
        launchctl,
        command_log,
        loaded_marker,
        bootout_delay_inspections=3,
    )
    monkeypatch.setattr(launchd_module.sys, "platform", "darwin")
    target = _target(tmp_path)
    manager = LaunchdUserServiceManager(
        definition_dir=tmp_path / "LaunchAgents",
        launchctl_bin=str(launchctl),
        user_id=501,
    )

    installed = manager.install(target, should_start=True)
    restarted = manager.restart(target)
    stopped = manager.stop(target)
    resumed = manager.start(target)
    removed = manager.uninstall(target)

    assert installed.execution_state is ManagedServiceExecutionState.RUNNING
    assert installed.startup_state is ManagedServiceStartupState.ENABLED
    assert stopped.execution_state is ManagedServiceExecutionState.STOPPED
    assert restarted.execution_state is ManagedServiceExecutionState.RUNNING
    assert resumed.execution_state is ManagedServiceExecutionState.RUNNING
    assert removed.installation_state is ManagedServiceInstallationState.ABSENT
    commands = command_log.read_text(encoding="utf-8").splitlines()
    assert f"enable gui/501/{LAUNCHD_SERVICE_NAME}" in commands
    assert any(command.startswith("bootstrap gui/501 ") for command in commands)
    assert f"bootout gui/501/{LAUNCHD_SERVICE_NAME}" in commands
    assert f"kickstart -k gui/501/{LAUNCHD_SERVICE_NAME}" in commands
    stop_index = commands.index(f"bootout gui/501/{LAUNCHD_SERVICE_NAME}")
    assert any(command.startswith("bootstrap gui/501 ") for command in commands[stop_index + 1 :])
    assert not manager.definition_path.exists()


def test_launchctl_print_parser_reads_runtime_state() -> None:
    snapshot = parse_launchctl_print(
        """gui/501/io.github.ringlochid.banksia = {
    state = running
    pid = 4312
    last exit code = 0
}
"""
    )

    assert snapshot.is_loaded is True
    assert snapshot.state == "running"
    assert snapshot.process_id == 4312
    assert snapshot.last_exit_code == 0


def test_launchd_user_selection_rejects_a_host_without_posix_user_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(launchd_module.os, "getuid", raising=False)
    manager = LaunchdUserServiceManager(definition_dir=tmp_path / "LaunchAgents")

    with pytest.raises(RuntimeError, match="requires a POSIX host"):
        _ = manager.domain_target


def test_native_command_error_carries_explicit_operation_and_manager(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name != "posix":
        pytest.skip("fake systemctl executable requires POSIX process semantics")
    systemctl = tmp_path / "systemctl"
    systemctl.write_text(
        "#!/bin/sh\necho simulated failure >&2\nexit 7\n",
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
    monkeypatch.setattr(systemd_module.sys, "platform", "linux")
    manager = SystemdUserServiceManager(
        definition_dir=tmp_path / "units",
        systemctl_bin=str(systemctl),
    )

    with pytest.raises(ManagedServiceCommandError) as failure:
        manager.install(_target(tmp_path), should_start=False)

    assert failure.value.manager == "systemd-user"
    assert failure.value.operation == "daemon-reload"
    assert failure.value.service_name == "banksia.service"
    assert failure.value.return_code == 7
    assert failure.value.detail == "simulated failure"


def _target(tmp_path: Path) -> ManagedServiceTarget:
    return ManagedServiceTarget(
        config_path=tmp_path / "config" / "config.toml",
        python_executable=tmp_path / "venv" / "python.exe",
        log_path=tmp_path / "logs" / "controller.log",
    )


def _target_with_special_paths(tmp_path: Path) -> ManagedServiceTarget:
    return ManagedServiceTarget(
        config_path=tmp_path / 'config % with space "桉树"' / "config.toml",
        python_executable=tmp_path / "venv with space" / "python%bin",
        log_path=tmp_path / "log with space" / "controller.log",
    )


def _inspection(execution_state: ManagedServiceExecutionState) -> ManagedServiceInspection:
    return ManagedServiceInspection(
        manager="test-user-manager",
        service_name="banksia",
        definition_path=Path("banksia.service"),
        installation_state=ManagedServiceInstallationState.INSTALLED,
        startup_state=ManagedServiceStartupState.ENABLED,
        execution_state=execution_state,
        is_definition_current=True,
    )


def _write_fake_systemctl(path: Path, command_log: Path) -> None:
    running_marker = path.with_suffix(".running")
    path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "from pathlib import Path",
                "import sys",
                f"log = Path({str(command_log)!r})",
                f"running = Path({str(running_marker)!r})",
                "args = sys.argv[1:]",
                "if args and args[0] == '--user': args = args[1:]",
                "with log.open('a', encoding='utf-8') as stream:",
                "    stream.write(' '.join(args) + '\\n')",
                "if args and args[0] in {'start', 'restart'}: running.touch()",
                "if args and args[0] in {'stop', 'disable'}: running.unlink(missing_ok=True)",
                "if args and args[0] == 'show':",
                "    state = 'active' if running.exists() else 'inactive'",
                "    detail = 'running' if running.exists() else 'dead'",
                "    print('LoadState=loaded')",
                "    print('UnitFileState=enabled')",
                "    print(f'ActiveState={state}')",
                "    print(f'SubState={detail}')",
                f"    print('FragmentPath={path.parent / 'units' / 'banksia.service'}')",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_fake_launchctl(
    path: Path,
    command_log: Path,
    loaded_marker: Path,
    *,
    bootout_delay_inspections: int = 0,
) -> None:
    unloading_marker = loaded_marker.with_suffix(".unloading")
    path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "from pathlib import Path",
                "import sys",
                f"log = Path({str(command_log)!r})",
                f"loaded = Path({str(loaded_marker)!r})",
                f"unloading = Path({str(unloading_marker)!r})",
                f"bootout_delay = {bootout_delay_inspections!r}",
                "args = sys.argv[1:]",
                "with log.open('a', encoding='utf-8') as stream:",
                "    stream.write(' '.join(args) + '\\n')",
                "if args[0] == 'print-disabled':",
                "    print('disabled services = {')",
                "    print('}')",
                "elif args[0] == 'print':",
                "    if unloading.exists():",
                "        remaining = int(unloading.read_text(encoding='utf-8'))",
                "        if remaining <= 0:",
                "            unloading.unlink()",
                "            loaded.unlink(missing_ok=True)",
                "            raise SystemExit(1)",
                "        unloading.write_text(str(remaining - 1), encoding='utf-8')",
                "    if not loaded.exists(): raise SystemExit(1)",
                "    print('gui/501/io.github.ringlochid.banksia = {')",
                "    print('    state = running')",
                "    print('    pid = 4312')",
                "    print('    last exit code = 0')",
                "    print('}')",
                "if args[0] == 'bootstrap':",
                "    loaded.touch()",
                "    unloading.unlink(missing_ok=True)",
                "if args[0] == 'kickstart' and not unloading.exists(): loaded.touch()",
                "if args[0] == 'bootout':",
                "    if bootout_delay:",
                "        unloading.write_text(str(bootout_delay), encoding='utf-8')",
                "    else:",
                "        loaded.unlink(missing_ok=True)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
