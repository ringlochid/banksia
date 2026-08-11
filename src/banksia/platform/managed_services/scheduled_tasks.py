from __future__ import annotations

import locale
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from banksia.platform.workspace_files import protect_private_path

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

SCHEDULED_TASK_MANAGER_NAME = "windows-task-scheduler"
SCHEDULED_TASK_SERVICE_NAME = r"\Banksia\Controller"
_TASK_NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"


class ScheduledTaskUserServiceManager:
    """Current-user Windows Task Scheduler lifecycle for the Banksia controller."""

    manager_name = SCHEDULED_TASK_MANAGER_NAME
    service_name = SCHEDULED_TASK_SERVICE_NAME

    def __init__(
        self,
        *,
        schtasks_bin: str | None = None,
        user_id: str | None = None,
    ) -> None:
        self._schtasks_bin = schtasks_bin
        self._user_id = user_id

    def render_definition(self, target: ManagedServiceTarget) -> str:
        return render_scheduled_task_xml(
            user_id=self._resolved_user_id(),
            python_executable=_background_python(target.python_executable),
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
        definition_path = target.config_path.parent / f".scheduled-task-{uuid4().hex}.xml"
        definition_path.parent.mkdir(parents=True, exist_ok=True)
        definition_path.write_bytes(self.render_definition(target).encode("utf-16"))
        protect_private_path(definition_path, is_directory=False)
        try:
            self._execute(
                "/Create",
                "/TN",
                self.service_name,
                "/XML",
                str(definition_path),
                "/F",
                operation="install",
                command_observer=command_observer,
            )
        finally:
            definition_path.unlink(missing_ok=True)
        if should_start:
            self._execute(
                "/Run",
                "/TN",
                self.service_name,
                operation="start",
                command_observer=command_observer,
            )
            return self.inspect(target).with_execution_state(ManagedServiceExecutionState.STARTING)
        return self.inspect(target)

    def uninstall(
        self,
        target: ManagedServiceTarget,
        *,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection:
        self._require_supported()
        del target
        if self._query_definition() is None:
            return self._absent_inspection()
        self._execute(
            "/End",
            "/TN",
            self.service_name,
            operation="stop",
            should_check=False,
            command_observer=command_observer,
        )
        self._execute(
            "/Delete",
            "/TN",
            self.service_name,
            "/F",
            operation="uninstall",
            command_observer=command_observer,
        )
        return self._absent_inspection()

    def start(
        self,
        target: ManagedServiceTarget,
        *,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection:
        self._require_current_definition(target)
        self._execute(
            "/Run",
            "/TN",
            self.service_name,
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
        self._execute(
            "/End",
            "/TN",
            self.service_name,
            operation="stop",
            should_check=False,
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
        self._execute(
            "/End",
            "/TN",
            self.service_name,
            operation="stop",
            should_check=False,
            command_observer=command_observer,
        )
        return self.start(target, command_observer=command_observer)

    def inspect(self, target: ManagedServiceTarget) -> ManagedServiceInspection:
        self._require_supported()
        definition = self._query_definition()
        if definition is None:
            return self._absent_inspection()
        is_current = _definitions_match(definition, self.render_definition(target))
        return ManagedServiceInspection(
            manager=self.manager_name,
            service_name=self.service_name,
            definition_path=None,
            installation_state=ManagedServiceInstallationState.INSTALLED,
            startup_state=ManagedServiceStartupState.ENABLED,
            execution_state=ManagedServiceExecutionState.UNKNOWN,
            technical_state=(("definition_current", str(is_current).lower()),),
        )

    def _require_current_definition(self, target: ManagedServiceTarget) -> None:
        definition = self._query_definition()
        if definition is None:
            raise RuntimeError(
                "Banksia background service is not installed; run `banksia service install`"
            )
        if not _definitions_match(definition, self.render_definition(target)):
            raise RuntimeError(
                "Banksia background service definition is out of date; "
                "run `banksia service install`"
            )

    def _query_definition(self) -> str | None:
        completed = self._execute(
            "/Query",
            "/TN",
            self.service_name,
            "/XML",
            operation="inspect",
            should_check=False,
        )
        return completed.stdout if completed.returncode == 0 else None

    def _resolved_user_id(self) -> str:
        if self._user_id is not None:
            return self._user_id
        self._require_supported()
        import win32api
        import win32con
        import win32security

        token: Any = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(),
            win32con.TOKEN_QUERY,
        )
        try:
            sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        finally:
            win32api.CloseHandle(int(token))
        return str(win32security.ConvertSidToStringSid(sid))

    def _execute(
        self,
        *args: str,
        operation: str,
        should_check: bool = True,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = (self._schtasks_bin or "schtasks.exe", *args)
        if command_observer is not None:
            command_observer(command)
        try:
            raw = subprocess.run(list(command), check=False, capture_output=True)
        except OSError as exc:
            raise ManagedServiceCommandError(
                manager=self.manager_name,
                operation=operation,
                service_name=self.service_name,
                command=command,
                return_code=-1,
                detail=str(exc),
            ) from exc
        completed = subprocess.CompletedProcess(
            raw.args,
            raw.returncode,
            _decode_native_output(raw.stdout),
            _decode_native_output(raw.stderr),
        )
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

    @staticmethod
    def _require_supported() -> None:
        if sys.platform != "win32":
            raise RuntimeError(
                "Banksia background services use a current-user Scheduled Task on Windows; "
                "this host is not Windows"
            )

    def _absent_inspection(self) -> ManagedServiceInspection:
        return ManagedServiceInspection(
            manager=self.manager_name,
            service_name=self.service_name,
            definition_path=None,
            installation_state=ManagedServiceInstallationState.ABSENT,
            startup_state=ManagedServiceStartupState.DISABLED,
            execution_state=ManagedServiceExecutionState.STOPPED,
        )


def render_scheduled_task_xml(
    *,
    user_id: str,
    python_executable: Path,
    config_path: Path,
    log_path: Path,
) -> str:
    arguments = subprocess.list2cmdline(
        [
            "-m",
            "banksia",
            "serve",
            "--config",
            str(config_path),
            "--service-log",
            str(log_path),
        ]
    )
    values = {
        "user": escape(user_id),
        "command": escape(str(python_executable)),
        "arguments": escape(arguments),
        "working_directory": escape(str(config_path.parent)),
    }
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="{_TASK_NAMESPACE}">
  <RegistrationInfo><Description>Banksia local controller</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{values["user"]}</UserId></LogonTrigger></Triggers>
  <Principals><Principal id="Author">
    <UserId>{values["user"]}</UserId>
    <LogonType>InteractiveToken</LogonType>
    <RunLevel>LeastPrivilege</RunLevel>
  </Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author"><Exec>
    <Command>{values["command"]}</Command>
    <Arguments>{values["arguments"]}</Arguments>
    <WorkingDirectory>{values["working_directory"]}</WorkingDirectory>
  </Exec></Actions>
</Task>
"""


def _definitions_match(actual: str, expected: str) -> bool:
    try:
        actual_root = ElementTree.fromstring(actual)
        expected_root = ElementTree.fromstring(expected)
    except ElementTree.ParseError:
        return False
    selected_paths = (
        "./t:Triggers/t:LogonTrigger/t:Enabled",
        "./t:Triggers/t:LogonTrigger/t:UserId",
        "./t:Principals/t:Principal/t:UserId",
        "./t:Principals/t:Principal/t:LogonType",
        "./t:Principals/t:Principal/t:RunLevel",
        "./t:Settings/t:MultipleInstancesPolicy",
        "./t:Settings/t:Enabled",
        "./t:Settings/t:ExecutionTimeLimit",
        "./t:Actions/t:Exec/t:Command",
        "./t:Actions/t:Exec/t:Arguments",
        "./t:Actions/t:Exec/t:WorkingDirectory",
    )
    namespace = {"t": _TASK_NAMESPACE}
    return all(
        _element_text(actual_root.find(path, namespace))
        == _element_text(expected_root.find(path, namespace))
        for path in selected_paths
    )


def _element_text(element: ElementTree.Element | None) -> str | None:
    return element.text if element is not None else None


def _decode_native_output(payload: bytes) -> str:
    if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        return payload.decode("utf-16")
    return payload.decode(locale.getpreferredencoding(False), errors="replace")


def _background_python(executable: Path) -> Path:
    candidate = executable.with_name("pythonw.exe")
    return candidate if candidate.is_file() else executable


__all__ = [
    "SCHEDULED_TASK_MANAGER_NAME",
    "SCHEDULED_TASK_SERVICE_NAME",
    "ScheduledTaskUserServiceManager",
    "render_scheduled_task_xml",
]
