from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

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

LAUNCHD_MANAGER_NAME = "launchd-user"
LAUNCHD_SERVICE_NAME = "io.github.ringlochid.banksia"


class LaunchdUserServiceManager:
    manager_name = LAUNCHD_MANAGER_NAME
    service_name = LAUNCHD_SERVICE_NAME

    def __init__(
        self,
        *,
        definition_dir: Path | None = None,
        launchctl_bin: str | None = None,
        user_id: int | None = None,
    ) -> None:
        self._definition_dir = definition_dir
        self._launchctl_bin = launchctl_bin
        self._user_id = user_id

    def render_definition(self, target: ManagedServiceTarget) -> str:
        return render_launch_agent_plist(
            label=self.service_name,
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
        self._execute(
            "enable",
            self.service_target,
            operation="enable",
            command_observer=command_observer,
        )
        if not should_start:
            return self.inspect(target)
        if self._is_loaded():
            self._execute(
                "bootout",
                self.service_target,
                operation="reload",
                command_observer=command_observer,
            )
        self._execute(
            "bootstrap",
            self.domain_target,
            str(self.definition_path),
            operation="install",
            command_observer=command_observer,
        )
        return self.inspect(target).with_execution_state(ManagedServiceExecutionState.STARTING)

    def uninstall(
        self,
        target: ManagedServiceTarget,
        *,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection:
        self._require_supported()
        del target
        if self._is_loaded():
            self._execute(
                "bootout",
                self.service_target,
                operation="uninstall",
                command_observer=command_observer,
            )
        self._execute(
            "enable",
            self.service_target,
            operation="clear disabled state",
            should_check=False,
            command_observer=command_observer,
        )
        remove_service_definition(self.definition_path)
        return self._absent_inspection()

    def start(
        self,
        target: ManagedServiceTarget,
        *,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection:
        self._require_current_definition(target)
        self._execute(
            "enable",
            self.service_target,
            operation="enable",
            command_observer=command_observer,
        )
        if self._is_loaded():
            self._execute(
                "kickstart",
                self.service_target,
                operation="start",
                command_observer=command_observer,
            )
        else:
            self._execute(
                "bootstrap",
                self.domain_target,
                str(self.definition_path),
                operation="start",
                command_observer=command_observer,
            )
        return self.inspect(target).with_execution_state(ManagedServiceExecutionState.STARTING)

    def stop(
        self,
        target: ManagedServiceTarget,
        *,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection:
        self._require_current_definition(target)
        if self._is_loaded():
            self._execute(
                "bootout",
                self.service_target,
                operation="stop",
                command_observer=command_observer,
            )
        return self.inspect(target).with_execution_state(ManagedServiceExecutionState.STOPPED)

    def restart(
        self,
        target: ManagedServiceTarget,
        *,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection:
        self._require_current_definition(target)
        if self._is_loaded():
            self._execute(
                "kickstart",
                "-k",
                self.service_target,
                operation="restart",
                command_observer=command_observer,
            )
        else:
            self._execute(
                "bootstrap",
                self.domain_target,
                str(self.definition_path),
                operation="restart",
                command_observer=command_observer,
            )
        return self.inspect(target).with_execution_state(ManagedServiceExecutionState.STARTING)

    def inspect(self, target: ManagedServiceTarget) -> ManagedServiceInspection:
        self._require_supported()
        del target
        if read_service_definition(self.definition_path) is None:
            return self._absent_inspection()
        is_loaded = self._is_loaded()
        return ManagedServiceInspection(
            manager=self.manager_name,
            service_name=self.service_name,
            definition_path=self.definition_path,
            installation_state=ManagedServiceInstallationState.INSTALLED,
            startup_state=ManagedServiceStartupState.UNKNOWN,
            execution_state=(
                ManagedServiceExecutionState.UNKNOWN
                if is_loaded
                else ManagedServiceExecutionState.STOPPED
            ),
            technical_state=(("loaded", str(is_loaded).lower()),),
        )

    @property
    def definition_path(self) -> Path:
        definition_dir = self._definition_dir or Path.home() / "Library" / "LaunchAgents"
        return definition_dir / f"{self.service_name}.plist"

    @property
    def domain_target(self) -> str:
        return f"gui/{self._resolved_user_id()}"

    @property
    def service_target(self) -> str:
        return f"{self.domain_target}/{self.service_name}"

    def _resolved_user_id(self) -> int:
        if self._user_id is not None:
            return self._user_id
        return os.getuid()

    def _require_supported(self) -> None:
        if sys.platform != "darwin":
            raise RuntimeError(
                "Banksia background services use a current-user LaunchAgent on macOS; "
                "this host is not macOS"
            )

    def _require_current_definition(self, target: ManagedServiceTarget) -> None:
        current = read_service_definition(self.definition_path)
        if current is None:
            raise RuntimeError(
                "Banksia background service is not installed; run `banksia service install`"
            )
        expected = self.render_definition(target).encode("utf-8")
        try:
            is_current = plistlib.loads(current) == plistlib.loads(expected)
        except plistlib.InvalidFileException as exc:
            raise RuntimeError(
                "Banksia background service definition is invalid; run `banksia service install`"
            ) from exc
        if not is_current:
            raise RuntimeError(
                "Banksia background service definition is out of date; "
                "run `banksia service install`"
            )

    def _is_loaded(self) -> bool:
        completed = self._execute(
            "print",
            self.service_target,
            operation="inspect",
            should_check=False,
        )
        return completed.returncode == 0

    def _execute(
        self,
        *args: str,
        operation: str,
        should_check: bool = True,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = (self._launchctl_bin or "launchctl", *args)
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

    def _absent_inspection(self) -> ManagedServiceInspection:
        return ManagedServiceInspection(
            manager=self.manager_name,
            service_name=self.service_name,
            definition_path=self.definition_path,
            installation_state=ManagedServiceInstallationState.ABSENT,
            startup_state=ManagedServiceStartupState.DISABLED,
            execution_state=ManagedServiceExecutionState.STOPPED,
        )


def render_launch_agent_plist(
    *,
    label: str,
    python_executable: Path,
    config_path: Path,
    log_path: Path,
) -> str:
    definition = {
        "Label": label,
        "ProgramArguments": [
            str(python_executable),
            "-m",
            "banksia",
            "serve",
            "--config",
            str(config_path),
            "--service-log",
            str(log_path),
        ],
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 5,
    }
    return plistlib.dumps(
        definition,
        fmt=plistlib.FMT_XML,
        sort_keys=False,
    ).decode("utf-8")


__all__ = [
    "LAUNCHD_MANAGER_NAME",
    "LAUNCHD_SERVICE_NAME",
    "LaunchdUserServiceManager",
    "render_launch_agent_plist",
]
