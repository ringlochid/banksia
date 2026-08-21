from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from banksia.platform.managed_services.windows_task_scheduler import (
    ComWindowsTaskScheduler,
    WindowsTaskScheduler,
)

from .legacy_state import (
    LegacyStateOracle,
    assert_legacy_state_unchanged,
    create_legacy_state_oracle,
)
from .processes import (
    available_loopback_port,
    create_offline_venv,
    install_wheel,
    isolated_environment,
    run_json_command,
    venv_executable,
    venv_python,
)

SYSTEMCTL_INSPECTION_CALL_PREFIX = "--user show banksia.service "
EXPECTED_INSTALL_SYSTEMCTL_CHANGE_CALLS = (
    "--user daemon-reload",
    "--user enable banksia.service",
)
EXPECTED_LIFECYCLE_SYSTEMCTL_CHANGE_CALLS = (
    *EXPECTED_INSTALL_SYSTEMCTL_CHANGE_CALLS,
    "--user start banksia.service",
    "--user stop banksia.service",
    "--user start banksia.service",
    "--user stop banksia.service",
    "--user disable --now banksia.service",
    "--user daemon-reload",
)


@dataclass(frozen=True)
class ServiceProbeContext:
    install_root: Path
    data_home: Path
    venv_path: Path
    unit_dir: Path
    config_path: Path
    env_file: Path
    unit_path: Path
    systemctl_log: Path
    env: dict[str, str]
    executable: Path
    port: int


@dataclass(frozen=True)
class WindowsServiceProbeContext:
    install_root: Path
    config_path: Path
    executable: Path
    env: dict[str, str]


def verify_user_service_installer(
    *,
    wheel_path: Path,
    workspace: Path,
    dependency_site_packages: Path,
) -> dict[str, object]:
    if os.name == "nt":
        return verify_windows_user_service_installer(
            wheel_path=wheel_path,
            workspace=workspace,
            dependency_site_packages=dependency_site_packages,
        )
    context, legacy_state = prepare_service_probe(
        workspace=workspace,
        dependency_site_packages=dependency_site_packages,
    )
    installation_payload = install_user_service(
        context=context,
        wheel_path=wheel_path,
    )
    verify_service_installation(context)
    lifecycle_payloads = exercise_service_lifecycle(context)
    uninstall_payload, final_calls = uninstall_user_service(context)
    assert_legacy_state_unchanged(legacy_state)
    return {
        "config_path": str(context.config_path),
        "installation": installation_payload,
        "lifecycle": lifecycle_payloads,
        "uninstall": uninstall_payload,
        "systemctl_calls": final_calls,
        "unit_removed": True,
        "config_preserved": True,
        "provider_environment_preserved": True,
        "legacy_state_untouched": True,
    }


def verify_windows_user_service_installer(
    *,
    wheel_path: Path,
    workspace: Path,
    dependency_site_packages: Path,
) -> dict[str, object]:
    assert_windows_service_probe_is_safe()
    context, initialization = prepare_windows_service_probe(
        wheel_path=wheel_path,
        workspace=workspace,
        dependency_site_packages=dependency_site_packages,
    )
    installation = run_windows_service_operation(context, "install", "--no-start")
    try:
        status = run_windows_service_operation(context, "status")
        lifecycle = exercise_windows_service_lifecycle(context)
        logs = read_windows_service_logs(context)
        validate_windows_service_lifecycle(
            initialization=initialization,
            installation=installation,
            status=status,
            lifecycle=lifecycle,
            logs=logs,
        )
    finally:
        uninstall = run_windows_service_operation(context, "uninstall")
    if uninstall.get("installation_state") != "absent":
        raise AssertionError(f"Windows service uninstall failed: {uninstall}")
    return {
        "initialization": initialization,
        "installation": installation,
        "status": status,
        "lifecycle": lifecycle,
        "logs": logs,
        "uninstall": uninstall,
        "native_task_removed": True,
    }


def assert_windows_service_probe_is_safe(
    scheduler: WindowsTaskScheduler | None = None,
) -> None:
    selected_scheduler = scheduler or ComWindowsTaskScheduler()
    if selected_scheduler.inspect() is None:
        return
    raise AssertionError(
        "refusing installed-distribution verification because the fixed "
        r"Windows service task \Banksia\Controller already exists; "
        "use a clean Windows host or uninstall the user service explicitly first"
    )


def prepare_windows_service_probe(
    *,
    wheel_path: Path,
    workspace: Path,
    dependency_site_packages: Path,
) -> tuple[WindowsServiceProbeContext, dict[str, Any]]:
    install_root = workspace / "windows-installer"
    home = install_root / "home"
    data_dir = home / "data" / "banksia"
    config_path = home / "config" / "banksia" / "config.toml"
    venv_path = install_root / "venv"
    install_root.mkdir(parents=True, exist_ok=True)
    create_offline_venv(venv_path, dependency_site_packages)
    install_wheel(venv_path, wheel_path, install_root)
    executable = venv_executable(venv_path, "oms")
    env = isolated_environment(home)
    port = available_loopback_port()
    context = WindowsServiceProbeContext(
        install_root=install_root,
        config_path=config_path,
        executable=executable,
        env=env,
    )
    initialization = run_json_command(
        executable,
        (
            "init",
            "--non-interactive",
            "--config",
            str(config_path),
            "--data-dir",
            str(data_dir),
            "--workspace",
            str(install_root),
            "--port",
            str(port),
            "--json",
        ),
        cwd=install_root,
        env=env,
    )
    return context, initialization


def run_windows_service_operation(
    context: WindowsServiceProbeContext,
    verb: str,
    *verb_arguments: str,
) -> dict[str, Any]:
    return run_json_command(
        context.executable,
        (
            "service",
            verb,
            *verb_arguments,
            "--config",
            str(context.config_path),
            "--json",
        ),
        cwd=context.install_root,
        env=context.env,
    )


def read_windows_service_logs(context: WindowsServiceProbeContext) -> dict[str, Any]:
    return run_json_command(
        context.executable,
        ("service", "logs", "--lines", "20", "--json"),
        cwd=context.install_root,
        env=context.env,
    )


def exercise_windows_service_lifecycle(
    context: WindowsServiceProbeContext,
) -> dict[str, dict[str, Any]]:
    return {
        label: run_windows_service_operation(context, verb)
        for label, verb in (
            ("start", "start"),
            ("start_again", "start"),
            ("restart", "restart"),
            ("stop", "stop"),
        )
    }


def validate_windows_service_lifecycle(
    *,
    initialization: dict[str, Any],
    installation: dict[str, Any],
    status: dict[str, Any],
    lifecycle: dict[str, dict[str, Any]],
    logs: dict[str, Any],
) -> None:
    if initialization.get("ok") is not True:
        raise AssertionError(f"Windows initialization returned unexpected data: {initialization}")
    if any(
        payload.get("manager") != "windows-task-scheduler"
        for payload in (installation, status, *lifecycle.values())
    ):
        raise AssertionError(
            "installed Windows service returned unexpected manager data: "
            f"{installation}, {status}, {lifecycle}"
        )
    if installation.get("definition_current") is not True:
        raise AssertionError(f"Windows service definition did not round-trip: {installation}")
    expected_states = ("ready", "ready", "ready", "stopped")
    if tuple(payload.get("controller_state") for payload in lifecycle.values()) != expected_states:
        raise AssertionError(f"Windows service lifecycle returned unexpected data: {lifecycle}")
    if not logs.get("lines"):
        raise AssertionError(f"Windows service log remained empty: {logs}")


def prepare_service_probe(
    *,
    workspace: Path,
    dependency_site_packages: Path,
) -> tuple[ServiceProbeContext, LegacyStateOracle]:
    install_root = workspace / "installer"
    home = install_root / "home"
    config_home = install_root / "config"
    data_home = install_root / "data"
    state_home = install_root / "state"
    venv_path = install_root / "venv"
    unit_dir = home / ".config" / "systemd" / "user"
    config_path = config_home / "banksia" / "config.toml"
    env_file = config_home / "banksia" / "banksia.env"
    systemctl_log = install_root / "systemctl.log"
    systemctl_state = install_root / "systemctl.state"
    fake_systemctl = install_root / "systemctl"
    install_root.mkdir(parents=True, exist_ok=True)
    legacy_state = create_legacy_state_oracle(
        config_home=config_home,
        data_home=data_home,
        cache_home=home / "cache",
    )
    create_offline_venv(venv_path, dependency_site_packages)
    write_fake_systemctl(fake_systemctl)
    env = isolated_environment(home)
    env.update(
        {
            "OMS_CONFIG": str(config_path),
            "OMS_DATA_DIR": str(data_home / "banksia"),
            "OMS_SYSTEMCTL_BIN": str(fake_systemctl),
            "OMS_SYSTEMCTL_LOG": str(systemctl_log),
            "OMS_SYSTEMCTL_STATE": str(systemctl_state),
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_IGNORE_INSTALLED": "1",
            "PIP_NO_INDEX": "1",
            "XDG_CONFIG_HOME": str(config_home),
            "XDG_DATA_HOME": str(data_home),
            "XDG_STATE_HOME": str(state_home),
        }
    )
    context = ServiceProbeContext(
        install_root=install_root,
        data_home=data_home,
        venv_path=venv_path,
        unit_dir=unit_dir,
        config_path=config_path,
        env_file=env_file,
        unit_path=unit_dir / "banksia.service",
        systemctl_log=systemctl_log,
        env=env,
        executable=venv_executable(venv_path, "oms"),
        port=available_loopback_port(),
    )
    return context, legacy_state


def install_user_service(
    *,
    context: ServiceProbeContext,
    wheel_path: Path,
) -> dict[str, Any]:
    install_wheel(
        context.venv_path,
        wheel_path,
        context.install_root,
    )
    initialization = run_json_command(
        context.executable,
        (
            "init",
            "--non-interactive",
            "--config",
            str(context.config_path),
            "--data-dir",
            str(context.data_home / "banksia"),
            "--workspace",
            str(context.install_root),
            "--port",
            str(context.port),
            "--json",
        ),
        cwd=context.install_root,
        env=context.env,
    )
    if initialization.get("ok") is not True:
        raise AssertionError(f"installed initialization returned unexpected data: {initialization}")
    installation = run_json_command(
        context.executable,
        (
            "service",
            "install",
            "--config",
            str(context.config_path),
            "--no-start",
            "--json",
        ),
        cwd=context.install_root,
        env=context.env,
    )
    if (
        installation.get("manager") != "systemd-user"
        or installation.get("installation_state") != "installed"
        or installation.get("definition_current") is not True
        or installation.get("startup_state") != "enabled"
        or installation.get("controller_state") != "stopped"
    ):
        raise AssertionError(f"installed service setup returned unexpected data: {installation}")
    return {
        "initialization": initialization,
        "service": installation,
    }


def verify_service_installation(context: ServiceProbeContext) -> None:
    generated_paths = (
        context.config_path,
        context.data_home / "banksia",
        context.env_file,
        context.unit_path,
    )
    for generated_path in generated_paths:
        if not generated_path.exists() or not generated_path.resolve().is_relative_to(
            context.install_root
        ):
            raise AssertionError(f"installer wrote outside its isolated tree: {generated_path}")
    unit_text = context.unit_path.read_text(encoding="utf-8")
    if str(venv_python(context.venv_path)) not in unit_text:
        raise AssertionError("installed unit does not use the dedicated virtual environment")
    systemctl_calls = tuple(context.systemctl_log.read_text(encoding="utf-8").splitlines())
    if systemctl_change_calls(systemctl_calls) != EXPECTED_INSTALL_SYSTEMCTL_CHANGE_CALLS:
        raise AssertionError(f"unexpected install systemctl calls: {systemctl_calls}")


def exercise_service_lifecycle(
    context: ServiceProbeContext,
) -> dict[str, dict[str, Any]]:
    lifecycle_payloads = {
        verb: run_json_command(
            context.executable,
            (
                "service",
                verb,
                "--config",
                str(context.config_path),
                "--json",
            ),
            cwd=context.install_root,
            env=context.env,
        )
        for verb in ("start", "status", "restart", "stop")
    }
    if any(payload.get("manager") != "systemd-user" for payload in lifecycle_payloads.values()):
        raise AssertionError(
            f"installed service lifecycle returned unexpected data: {lifecycle_payloads}"
        )
    for verb, controller_state in {
        "start": "starting",
        "status": "starting",
        "restart": "starting",
        "stop": "stopped",
    }.items():
        payload = lifecycle_payloads[verb]
        if (
            payload.get("installation_state") != "installed"
            or payload.get("definition_current") is not True
            or payload.get("startup_state") != "enabled"
            or payload.get("controller_state") != controller_state
        ):
            raise AssertionError(f"installed service {verb} returned unexpected state: {payload}")
    log_payload = run_json_command(
        context.executable,
        ("service", "logs", "--lines", "5", "--json"),
        cwd=context.install_root,
        env=context.env,
    )
    if log_payload.get("ok") is not True or not isinstance(log_payload.get("lines"), list):
        raise AssertionError(f"installed service logs returned unexpected data: {log_payload}")
    lifecycle_payloads["logs"] = log_payload
    return lifecycle_payloads


def uninstall_user_service(
    context: ServiceProbeContext,
) -> tuple[dict[str, Any], list[str]]:
    payload = run_json_command(
        context.executable,
        (
            "service",
            "uninstall",
            "--config",
            str(context.config_path),
            "--json",
        ),
        cwd=context.install_root,
        env=context.env,
    )
    if (
        payload.get("installation_state") != "absent"
        or payload.get("controller_state") != "stopped"
    ):
        raise AssertionError(f"service uninstall returned unexpected data: {payload}")
    if context.unit_path.exists():
        raise AssertionError("service uninstall left its native definition behind")
    if not context.config_path.is_file() or not context.env_file.is_file():
        raise AssertionError("service uninstall removed persistent Oh My Subagents settings")
    final_calls = context.systemctl_log.read_text(encoding="utf-8").splitlines()
    if systemctl_change_calls(final_calls) != EXPECTED_LIFECYCLE_SYSTEMCTL_CHANGE_CALLS:
        raise AssertionError(f"unexpected service lifecycle systemctl calls: {final_calls}")
    return payload, final_calls


def systemctl_change_calls(calls: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(call for call in calls if not call.startswith(SYSTEMCTL_INSPECTION_CALL_PREFIX))


def write_fake_systemctl(path: Path) -> None:
    path.write_text(
        """#!/bin/sh
set -eu
printf '%s\n' "$*" >> "$OMS_SYSTEMCTL_LOG"
case "${2:-}" in
  start|restart)
    printf '%s\n' active > "$OMS_SYSTEMCTL_STATE"
    ;;
  stop|disable)
    printf '%s\n' inactive > "$OMS_SYSTEMCTL_STATE"
    ;;
esac
if [ "${2:-}" = "show" ]; then
  unit="$HOME/.config/systemd/user/banksia.service"
  if [ ! -f "$unit" ]; then
    printf '%s\n' 'LoadState=not-found'
    exit 0
  fi
  state=inactive
  if [ -f "$OMS_SYSTEMCTL_STATE" ]; then
    state=$(cat "$OMS_SYSTEMCTL_STATE")
  fi
  if [ "$state" = active ]; then
    sub_state=running
  else
    sub_state=dead
  fi
  printf '%s\n' \
    'LoadState=loaded' \
    'UnitFileState=enabled' \
    "ActiveState=$state" \
    "SubState=$sub_state" \
    "FragmentPath=$unit"
fi
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
