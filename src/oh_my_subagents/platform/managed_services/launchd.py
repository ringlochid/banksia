from __future__ import annotations

import os
import plistlib
import re
import subprocess
import sys
import time
from dataclasses import dataclass
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
_LAUNCHCTL_FIELD_PATTERN = re.compile(r"^\s*([a-z][a-z ]+)\s*=\s*(.*?)\s*$")
_LAUNCHD_UNLOAD_TIMEOUT_SECONDS = 3.0
_LAUNCHD_UNLOAD_POLL_INTERVAL_SECONDS = 0.05


@dataclass(frozen=True, slots=True)
class LaunchdJobSnapshot:
    is_loaded: bool
    state: str | None = None
    process_id: int | None = None
    last_exit_code: int | None = None


class LaunchdUserServiceManager:
    manager_name = LAUNCHD_MANAGER_NAME
    service_name = LAUNCHD_SERVICE_NAME
    readiness_timeout_seconds = 3.0

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
        current = read_service_definition(self.definition_path)
        expected = self.render_definition(target).encode("utf-8")
        if current is not None and _launchd_definitions_match(current, expected):
            self._execute(
                "enable",
                self.service_target,
                operation="enable",
                command_observer=command_observer,
            )
            if should_start:
                return self.start(target, command_observer=command_observer)
            return self.inspect(target)
        self._unload_job(operation="reload", command_observer=command_observer)
        replace_service_definition(
            self.definition_path,
            expected,
        )
        self._execute(
            "enable",
            self.service_target,
            operation="enable",
            command_observer=command_observer,
        )
        inspection = self.inspect(target)
        if not inspection.is_definition_current:
            raise RuntimeError(
                "launchd did not retain the current Oh My Subagents service definition"
            )
        if should_start:
            return self.start(target, command_observer=command_observer)
        return inspection

    def uninstall(
        self,
        target: ManagedServiceTarget,
        *,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection:
        self._require_supported()
        del target
        self._unload_job(operation="uninstall", command_observer=command_observer)
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
        inspection = self.inspect(target)
        if inspection.execution_state in {
            ManagedServiceExecutionState.RUNNING,
            ManagedServiceExecutionState.STARTING,
        }:
            return inspection
        self._execute(
            "enable",
            self.service_target,
            operation="enable",
            command_observer=command_observer,
        )
        if self._inspect_job().is_loaded:
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
        return _as_started_inspection(self.inspect(target))

    def stop(
        self,
        target: ManagedServiceTarget,
        *,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection:
        self._require_current_definition(target)
        self._unload_job(operation="stop", command_observer=command_observer)
        return self.inspect(target)

    def restart(
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
        if self._inspect_job().is_loaded:
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
        return _as_started_inspection(self.inspect(target))

    def inspect(self, target: ManagedServiceTarget) -> ManagedServiceInspection:
        self._require_supported()
        current = read_service_definition(self.definition_path)
        if current is None:
            return self._absent_inspection()
        expected = self.render_definition(target).encode("utf-8")
        job = self._inspect_job()
        return ManagedServiceInspection(
            manager=self.manager_name,
            service_name=self.service_name,
            definition_path=self.definition_path,
            installation_state=ManagedServiceInstallationState.INSTALLED,
            startup_state=self._inspect_startup_state(),
            execution_state=_launchd_execution_state(job),
            is_definition_current=_launchd_definitions_match(current, expected),
            technical_state=tuple(
                (key, value)
                for key, value in (
                    ("loaded", str(job.is_loaded).lower()),
                    ("state", job.state),
                    ("pid", str(job.process_id) if job.process_id is not None else None),
                    (
                        "last_exit_code",
                        str(job.last_exit_code) if job.last_exit_code is not None else None,
                    ),
                )
                if value is not None
            ),
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
        return _current_posix_user_id()

    def _require_supported(self) -> None:
        if sys.platform != "darwin":
            raise RuntimeError(
                "Oh My Subagents background services use a current-user LaunchAgent on macOS; "
                "this host is not macOS"
            )

    def _require_current_definition(self, target: ManagedServiceTarget) -> None:
        current = read_service_definition(self.definition_path)
        if current is None:
            raise RuntimeError(
                "Oh My Subagents background service is not installed; run `oms service install`"
            )
        expected = self.render_definition(target).encode("utf-8")
        if not _launchd_definitions_match(current, expected):
            raise RuntimeError(
                "Oh My Subagents background service definition is out of date; "
                "run `oms service install`"
            )

    def _inspect_job(self) -> LaunchdJobSnapshot:
        completed = self._execute(
            "print",
            self.service_target,
            operation="inspect",
            should_check=False,
        )
        if completed.returncode != 0:
            return LaunchdJobSnapshot(is_loaded=False)
        return parse_launchctl_print(completed.stdout)

    def _inspect_startup_state(self) -> ManagedServiceStartupState:
        completed = self._execute(
            "print-disabled",
            self.domain_target,
            operation="inspect startup",
            should_check=False,
        )
        if completed.returncode != 0:
            return ManagedServiceStartupState.UNKNOWN
        pattern = re.compile(
            rf'^\s*"{re.escape(self.service_name)}"\s*=>\s*(true|false)\s*$',
            re.MULTILINE,
        )
        match = pattern.search(completed.stdout)
        if match is not None and match.group(1) == "true":
            return ManagedServiceStartupState.DISABLED
        return ManagedServiceStartupState.ENABLED

    def _unload_job(
        self,
        *,
        operation: str,
        command_observer: ManagedServiceCommandObserver | None,
    ) -> None:
        if not self._inspect_job().is_loaded:
            return
        self._execute(
            "bootout",
            self.service_target,
            operation=operation,
            command_observer=command_observer,
        )
        deadline = time.monotonic() + _LAUNCHD_UNLOAD_TIMEOUT_SECONDS
        while self._inspect_job().is_loaded:
            if time.monotonic() >= deadline:
                raise RuntimeError("launchd did not unload the Oh My Subagents background service")
            time.sleep(_LAUNCHD_UNLOAD_POLL_INTERVAL_SECONDS)

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
            is_definition_current=False,
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


def parse_launchctl_print(output: str) -> LaunchdJobSnapshot:
    values: dict[str, str] = {}
    for line in output.splitlines():
        match = _LAUNCHCTL_FIELD_PATTERN.match(line)
        if match is not None:
            values.setdefault(match.group(1).strip(), match.group(2))
    return LaunchdJobSnapshot(
        is_loaded=True,
        state=values.get("state"),
        process_id=_parse_launchctl_integer(values.get("pid")),
        last_exit_code=_parse_launchctl_integer(
            values.get("last exit code") or values.get("last exit status")
        ),
    )


def _launchd_definitions_match(actual: bytes, expected: bytes) -> bool:
    try:
        return bool(plistlib.loads(actual) == plistlib.loads(expected))
    except plistlib.InvalidFileException:
        return False


def _launchd_execution_state(job: LaunchdJobSnapshot) -> ManagedServiceExecutionState:
    if not job.is_loaded:
        return ManagedServiceExecutionState.STOPPED
    if job.process_id is not None or job.state == "running":
        return ManagedServiceExecutionState.RUNNING
    if job.last_exit_code not in {None, 0}:
        return ManagedServiceExecutionState.FAILED
    if job.state in {"spawn scheduled", "starting"}:
        return ManagedServiceExecutionState.STARTING
    if job.state in {"stopped", "waiting"} or job.last_exit_code == 0:
        return ManagedServiceExecutionState.STOPPED
    return ManagedServiceExecutionState.UNKNOWN


def _as_started_inspection(inspection: ManagedServiceInspection) -> ManagedServiceInspection:
    if inspection.execution_state in {
        ManagedServiceExecutionState.RUNNING,
        ManagedServiceExecutionState.STARTING,
    }:
        return inspection
    return inspection.with_execution_state(ManagedServiceExecutionState.STARTING)


def _parse_launchctl_integer(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value, 0)
    except ValueError:
        return None


def _current_posix_user_id() -> int:
    get_user_id = getattr(os, "getuid", None)
    if get_user_id is None:
        raise RuntimeError("launchd user selection requires a POSIX host with os.getuid()")
    return int(get_user_id())


__all__ = [
    "LAUNCHD_MANAGER_NAME",
    "LAUNCHD_SERVICE_NAME",
    "LaunchdJobSnapshot",
    "LaunchdUserServiceManager",
    "parse_launchctl_print",
    "render_launch_agent_plist",
]
