from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from banksia.platform.managed_services.resources import get_systemd_service_template

from .contracts import (
    ManagedServiceCommandError,
    ManagedServiceCommandObserver,
    ManagedServiceExecutionState,
    ManagedServiceInspection,
    ManagedServiceInstallationState,
    ManagedServiceStartupState,
    ManagedServiceTarget,
    bounded_service_command_detail,
)
from .definition_files import (
    read_service_definition,
    remove_service_definition,
    replace_service_definition,
)

SYSTEMD_MANAGER_NAME = "systemd-user"
SYSTEMD_SERVICE_NAME = "banksia.service"
_SYSTEMD_CLD_EXITED = "1"


class SystemdUserServiceManager:
    manager_name = SYSTEMD_MANAGER_NAME
    service_name = SYSTEMD_SERVICE_NAME

    def __init__(
        self,
        *,
        definition_dir: Path | None = None,
        systemctl_bin: str | None = None,
    ) -> None:
        self._definition_dir = definition_dir
        self._systemctl_bin = systemctl_bin

    def render_definition(self, target: ManagedServiceTarget) -> str:
        return render_systemd_service_unit(
            python_executable=target.python_executable,
            config_path=target.config_path,
            log_path=target.log_path,
        )

    def install(
        self,
        target: ManagedServiceTarget,
        *,
        should_start: bool,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection:
        self._require_supported()
        replace_service_definition(
            self.definition_path,
            self.render_definition(target).encode("utf-8"),
        )
        self._execute("daemon-reload", command_observer=command_observer)
        self._execute(
            "enable",
            self.service_name,
            command_observer=command_observer,
        )
        if should_start:
            self._execute(
                "restart",
                self.service_name,
                command_observer=command_observer,
            )
        return self.inspect(target)

    def uninstall(
        self,
        target: ManagedServiceTarget,
        *,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection:
        self._require_supported()
        del target
        self._execute(
            "disable",
            "--now",
            self.service_name,
            should_check=False,
            command_observer=command_observer,
        )
        remove_service_definition(self.definition_path)
        self._execute("daemon-reload", command_observer=command_observer)
        return self._absent_inspection()

    def start(
        self,
        target: ManagedServiceTarget,
        *,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection:
        self._require_current_definition(target)
        self._execute("start", self.service_name, command_observer=command_observer)
        return self.inspect(target)

    def stop(
        self,
        target: ManagedServiceTarget,
        *,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection:
        self._require_current_definition(target)
        self._execute("stop", self.service_name, command_observer=command_observer)
        return self.inspect(target)

    def restart(
        self,
        target: ManagedServiceTarget,
        *,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection:
        self._require_current_definition(target)
        self._execute("restart", self.service_name, command_observer=command_observer)
        return self.inspect(target)

    def inspect(self, target: ManagedServiceTarget) -> ManagedServiceInspection:
        self._require_supported()
        del target
        completed = self._execute(
            "show",
            self.service_name,
            (
                "--property=LoadState,UnitFileState,ActiveState,SubState,Result,"
                "ExecMainCode,ExecMainStatus,NRestarts,FragmentPath"
            ),
            should_check=False,
        )
        values = parse_systemd_show(completed.stdout)
        load_state = values.get("LoadState")
        if load_state in {None, "", "not-found"}:
            return self._absent_inspection()
        return ManagedServiceInspection(
            manager=self.manager_name,
            service_name=self.service_name,
            definition_path=Path(values.get("FragmentPath") or self.definition_path),
            installation_state=ManagedServiceInstallationState.INSTALLED,
            startup_state=_systemd_startup_state(values.get("UnitFileState")),
            execution_state=_systemd_execution_state(values),
            technical_state=tuple(
                (key, value)
                for key in (
                    "LoadState",
                    "UnitFileState",
                    "ActiveState",
                    "SubState",
                    "Result",
                    "ExecMainCode",
                    "ExecMainStatus",
                    "NRestarts",
                )
                if (value := values.get(key)) is not None
            ),
        )

    @property
    def definition_path(self) -> Path:
        definition_dir = self._definition_dir or get_linux_user_unit_dir()
        return definition_dir / self.service_name

    def _require_supported(self) -> None:
        if not is_systemd_supported():
            raise RuntimeError(
                "Banksia background services use systemd --user on Linux; this host is not Linux"
            )

    def _require_current_definition(self, target: ManagedServiceTarget) -> None:
        current = read_service_definition(self.definition_path)
        if current is None:
            raise RuntimeError(
                "Banksia background service is not installed; run `banksia service install`"
            )
        expected = self.render_definition(target).encode("utf-8")
        if current != expected:
            raise RuntimeError(
                "Banksia background service definition is out of date; "
                "run `banksia service install`"
            )

    def _execute(
        self,
        *args: str,
        should_check: bool = True,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> subprocess.CompletedProcess[str]:
        operation = args[0] if args else "inspect"
        command = (self._resolve_systemctl_bin(), "--user", *args)
        if command_observer is not None:
            command_observer(command)
        try:
            completed = subprocess.run(
                list(command),
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise ManagedServiceCommandError(
                manager=self.manager_name,
                operation=operation,
                service_name=self.service_name,
                command=command,
                return_code=-1,
                detail=str(exc),
            ) from exc
        if should_check and completed.returncode != 0:
            raise ManagedServiceCommandError(
                manager=self.manager_name,
                operation=operation,
                service_name=self.service_name,
                command=command,
                return_code=completed.returncode,
                detail=bounded_service_command_detail(completed.stderr or completed.stdout),
            )
        return completed

    def _resolve_systemctl_bin(self) -> str:
        return self._systemctl_bin or os.environ.get(
            "BANKSIA_SYSTEMCTL_BIN",
            "systemctl",
        )

    def _absent_inspection(self) -> ManagedServiceInspection:
        return ManagedServiceInspection(
            manager=self.manager_name,
            service_name=self.service_name,
            definition_path=self.definition_path,
            installation_state=ManagedServiceInstallationState.ABSENT,
            startup_state=ManagedServiceStartupState.DISABLED,
            execution_state=ManagedServiceExecutionState.STOPPED,
        )


def render_systemd_service_unit(
    *,
    python_executable: Path,
    config_path: Path,
    log_path: Path,
) -> str:
    rendered = get_systemd_service_template().read_text(encoding="utf-8")
    replacements = {
        "@BANKSIA_PYTHON@": _escape_systemd_quoted_value(str(python_executable)),
        "@BANKSIA_CONFIG@": _escape_systemd_quoted_value(str(config_path)),
        "@BANKSIA_SERVICE_LOG@": _escape_systemd_quoted_value(str(log_path)),
    }
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    return rendered


def parse_systemd_show(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def get_linux_user_unit_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def is_systemd_supported() -> bool:
    return os.name != "nt" and sys.platform.startswith("linux")


def _systemd_startup_state(value: str | None) -> ManagedServiceStartupState:
    if value in {"enabled", "enabled-runtime", "linked", "linked-runtime"}:
        return ManagedServiceStartupState.ENABLED
    if value in {"disabled", "masked", "masked-runtime"}:
        return ManagedServiceStartupState.DISABLED
    return ManagedServiceStartupState.UNKNOWN


def _systemd_execution_state(values: dict[str, str]) -> ManagedServiceExecutionState:
    active_state = values.get("ActiveState")
    if active_state == "active":
        return ManagedServiceExecutionState.RUNNING
    if active_state in {"activating", "reloading"}:
        if _systemd_restart_follows_failure(values):
            return ManagedServiceExecutionState.FAILED
        return ManagedServiceExecutionState.STARTING
    if active_state == "failed":
        return ManagedServiceExecutionState.FAILED
    if active_state in {"inactive", "deactivating"}:
        if _systemd_restart_follows_failure(values):
            return ManagedServiceExecutionState.FAILED
        return ManagedServiceExecutionState.STOPPED
    return ManagedServiceExecutionState.UNKNOWN


def _systemd_restart_follows_failure(values: dict[str, str]) -> bool:
    if values.get("SubState") != "auto-restart":
        return False
    result = values.get("Result")
    if result not in {None, ""}:
        return result != "success"
    exit_code = values.get("ExecMainCode")
    exit_status = values.get("ExecMainStatus")
    if exit_code in {None, "", "0"}:
        return False
    if exit_code == _SYSTEMD_CLD_EXITED:
        return exit_status not in {None, "", "0"}
    return True


def _escape_systemd_quoted_value(value: str) -> str:
    if "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError("managed service paths must fit on one line")
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")


__all__ = [
    "SYSTEMD_MANAGER_NAME",
    "SYSTEMD_SERVICE_NAME",
    "SystemdUserServiceManager",
    "get_linux_user_unit_dir",
    "is_systemd_supported",
    "parse_systemd_show",
    "render_systemd_service_unit",
]
