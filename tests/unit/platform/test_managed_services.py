from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

import banksia.platform.managed_services.launchd as launchd_module
from banksia.platform.managed_services import (
    LAUNCHD_SERVICE_NAME,
    ManagedServiceCommandError,
    ManagedServiceExecutionState,
    ManagedServiceInstallationState,
    ManagedServiceStartupState,
    ManagedServiceTarget,
    SystemdUserServiceManager,
    get_managed_service_manager,
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
    with pytest.raises(RuntimeError, match=r"Linux and macOS only.*native Windows"):
        get_managed_service_manager(platform_name="Windows")
    with pytest.raises(RuntimeError, match=r"Linux and macOS only.*native FreeBSD"):
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
) -> None:
    command_log = tmp_path / "systemctl.log"
    systemctl = tmp_path / "systemctl"
    _write_fake_systemctl(systemctl, command_log)
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
    command_log = tmp_path / "launchctl.log"
    loaded_marker = tmp_path / "loaded"
    launchctl = tmp_path / "launchctl"
    _write_fake_launchctl(launchctl, command_log, loaded_marker)
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
    removed = manager.uninstall(target)

    assert installed.execution_state is ManagedServiceExecutionState.STARTING
    assert installed.startup_state is ManagedServiceStartupState.UNKNOWN
    assert stopped.execution_state is ManagedServiceExecutionState.STOPPED
    assert restarted.execution_state is ManagedServiceExecutionState.STARTING
    assert removed.installation_state is ManagedServiceInstallationState.ABSENT
    commands = command_log.read_text(encoding="utf-8").splitlines()
    assert f"enable gui/501/{LAUNCHD_SERVICE_NAME}" in commands
    assert any(command.startswith("bootstrap gui/501 ") for command in commands)
    assert f"bootout gui/501/{LAUNCHD_SERVICE_NAME}" in commands
    assert f"kickstart -k gui/501/{LAUNCHD_SERVICE_NAME}" in commands
    assert not manager.definition_path.exists()


def test_native_command_error_carries_explicit_operation_and_manager(
    tmp_path: Path,
) -> None:
    systemctl = tmp_path / "systemctl"
    systemctl.write_text(
        "#!/bin/sh\necho simulated failure >&2\nexit 7\n",
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
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
) -> None:
    path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "from pathlib import Path",
                "import sys",
                f"log = Path({str(command_log)!r})",
                f"loaded = Path({str(loaded_marker)!r})",
                "args = sys.argv[1:]",
                "with log.open('a', encoding='utf-8') as stream:",
                "    stream.write(' '.join(args) + '\\n')",
                "if args[0] == 'print': raise SystemExit(0 if loaded.exists() else 1)",
                "if args[0] in {'bootstrap', 'kickstart'}: loaded.touch()",
                "if args[0] == 'bootout': loaded.unlink(missing_ok=True)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
