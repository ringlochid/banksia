from __future__ import annotations

import ntpath
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar
from xml.etree import ElementTree
from xml.sax.saxutils import escape

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
from .windows_task_scheduler import (
    ComWindowsTaskScheduler,
    WindowsScheduledTaskSnapshot,
    WindowsTaskScheduler,
    WindowsTaskSchedulerError,
)

SCHEDULED_TASK_MANAGER_NAME = "windows-task-scheduler"
SCHEDULED_TASK_SERVICE_NAME = r"\Banksia\Controller"
_TASK_NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"
_TASK_STATE_DISABLED = 1
_TASK_STATE_QUEUED = 2
_TASK_STATE_READY = 3
_TASK_STATE_RUNNING = 4
_TASK_STATUS_RESULTS = frozenset({0, *(range(0x00041300, 0x00041309)), 0x00041325})
_STOP_ATTEMPTS = 40
_STOP_INTERVAL_SECONDS = 0.1

WindowsIdentityResolver = Callable[[str], str]
_T = TypeVar("_T")


class ScheduledTaskUserServiceManager:
    """Current-user Windows Task Scheduler lifecycle for the Banksia controller."""

    manager_name = SCHEDULED_TASK_MANAGER_NAME
    service_name = SCHEDULED_TASK_SERVICE_NAME
    readiness_timeout_seconds = 30.0

    def __init__(
        self,
        *,
        task_scheduler: WindowsTaskScheduler | None = None,
        user_id: str | None = None,
        identity_resolver: WindowsIdentityResolver | None = None,
    ) -> None:
        self._task_scheduler = task_scheduler or ComWindowsTaskScheduler()
        self._user_id = user_id
        self._identity_resolver = identity_resolver or _resolve_windows_identity

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
        existing = self._inspect_snapshot()
        expected = self.render_definition(target)
        is_current = existing is not None and scheduled_task_definitions_match(
            existing.definition,
            expected,
            resolve_identity=self._identity_resolver,
        )
        if existing is not None and is_current and existing.is_enabled:
            if should_start:
                return self.start(target, command_observer=command_observer)
            return self._inspection_from_snapshot(existing, is_definition_current=True)
        if existing is not None and _snapshot_is_active(existing):
            self._stop_and_wait(command_observer=command_observer)

        user_id = self._resolved_user_id()
        self._invoke_scheduler(
            "install",
            command_observer,
            lambda: self._task_scheduler.register(definition=expected, user_id=user_id),
        )
        inspection = self.inspect(target)
        if not inspection.is_definition_current:
            raise RuntimeError(
                "Task Scheduler did not retain the current Banksia background service definition"
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
        snapshot = self._inspect_snapshot()
        if snapshot is None:
            return self._absent_inspection()
        if _snapshot_is_active(snapshot):
            self._stop_and_wait(command_observer=command_observer)
        self._invoke_scheduler("uninstall", command_observer, self._task_scheduler.delete)
        return self._absent_inspection()

    def start(
        self,
        target: ManagedServiceTarget,
        *,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection:
        snapshot = self._require_current_snapshot(target)
        if _snapshot_is_active(snapshot):
            return self._inspection_from_snapshot(snapshot, is_definition_current=True)
        self._invoke_scheduler("start", command_observer, self._task_scheduler.start_task)
        inspection = self.inspect(target)
        if inspection.execution_state in {
            ManagedServiceExecutionState.RUNNING,
            ManagedServiceExecutionState.STARTING,
        }:
            return inspection
        return inspection.with_execution_state(ManagedServiceExecutionState.STARTING)

    def stop(
        self,
        target: ManagedServiceTarget,
        *,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection:
        snapshot = self._require_current_snapshot(target)
        if _snapshot_is_active(snapshot):
            snapshot = self._stop_and_wait(command_observer=command_observer)
        return self._inspection_from_snapshot(snapshot, is_definition_current=True)

    def restart(
        self,
        target: ManagedServiceTarget,
        *,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection:
        snapshot = self._require_current_snapshot(target)
        if _snapshot_is_active(snapshot):
            self._stop_and_wait(command_observer=command_observer)
        return self.start(target, command_observer=command_observer)

    def inspect(self, target: ManagedServiceTarget) -> ManagedServiceInspection:
        self._require_supported()
        snapshot = self._inspect_snapshot()
        if snapshot is None:
            return self._absent_inspection()
        is_current = scheduled_task_definitions_match(
            snapshot.definition,
            self.render_definition(target),
            resolve_identity=self._identity_resolver,
        )
        return self._inspection_from_snapshot(snapshot, is_definition_current=is_current)

    def _require_current_snapshot(
        self,
        target: ManagedServiceTarget,
    ) -> WindowsScheduledTaskSnapshot:
        self._require_supported()
        snapshot = self._inspect_snapshot()
        if snapshot is None:
            raise RuntimeError(
                "Banksia background service is not installed; run `banksia service install`"
            )
        if not scheduled_task_definitions_match(
            snapshot.definition,
            self.render_definition(target),
            resolve_identity=self._identity_resolver,
        ):
            raise RuntimeError(
                "Banksia background service definition is out of date; "
                "run `banksia service install`"
            )
        return snapshot

    def _inspect_snapshot(self) -> WindowsScheduledTaskSnapshot | None:
        return self._invoke_scheduler("inspect", None, self._task_scheduler.inspect)

    def _stop_and_wait(
        self,
        *,
        command_observer: ManagedServiceCommandObserver | None,
    ) -> WindowsScheduledTaskSnapshot:
        self._invoke_scheduler("stop", command_observer, self._task_scheduler.stop)
        for attempt in range(_STOP_ATTEMPTS):
            snapshot = self._inspect_snapshot()
            if snapshot is None:
                raise RuntimeError("Banksia background service disappeared while stopping")
            if not _snapshot_is_active(snapshot):
                return snapshot
            if attempt + 1 < _STOP_ATTEMPTS:
                time.sleep(_STOP_INTERVAL_SECONDS)
        raise ManagedServiceCommandError(
            manager=self.manager_name,
            operation="stop",
            service_name=self.service_name,
            command=("Task Scheduler 2.0", "stop", self.service_name),
            return_code=-1,
            detail="the scheduled task did not stop within 4 seconds",
        )

    def _inspection_from_snapshot(
        self,
        snapshot: WindowsScheduledTaskSnapshot,
        *,
        is_definition_current: bool,
    ) -> ManagedServiceInspection:
        return ManagedServiceInspection(
            manager=self.manager_name,
            service_name=self.service_name,
            definition_path=None,
            installation_state=ManagedServiceInstallationState.INSTALLED,
            startup_state=(
                ManagedServiceStartupState.ENABLED
                if snapshot.is_enabled
                else ManagedServiceStartupState.DISABLED
            ),
            execution_state=_scheduled_task_execution_state(snapshot),
            is_definition_current=is_definition_current,
            technical_state=(
                ("task_state", str(snapshot.state)),
                ("last_task_result", str(snapshot.last_result)),
                ("running_instances", str(snapshot.running_instance_count)),
            ),
        )

    def _invoke_scheduler(
        self,
        operation: str,
        command_observer: ManagedServiceCommandObserver | None,
        action: Callable[[], _T],
    ) -> _T:
        command = ("Task Scheduler 2.0", operation, self.service_name)
        if command_observer is not None:
            command_observer(command)
        try:
            return action()
        except WindowsTaskSchedulerError as exc:
            raise ManagedServiceCommandError(
                manager=self.manager_name,
                operation=operation,
                service_name=self.service_name,
                command=command,
                return_code=exc.return_code,
                detail=bounded_service_command_detail(exc.detail),
            ) from exc

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
            is_definition_current=False,
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


def scheduled_task_definitions_match(
    actual: str,
    expected: str,
    *,
    resolve_identity: WindowsIdentityResolver,
) -> bool:
    try:
        actual_root = ElementTree.fromstring(actual)
        expected_root = ElementTree.fromstring(expected)
    except ElementTree.ParseError:
        return False
    return _normalized_definition_values(
        actual_root,
        resolve_identity=resolve_identity,
    ) == _normalized_definition_values(
        expected_root,
        resolve_identity=resolve_identity,
    )


def _normalized_definition_values(
    root: ElementTree.Element,
    *,
    resolve_identity: WindowsIdentityResolver,
) -> tuple[str | None, ...]:
    namespace = {"t": _TASK_NAMESPACE}
    trigger_user = _element_text(root.find("./t:Triggers/t:LogonTrigger/t:UserId", namespace))
    principal_user = _element_text(root.find("./t:Principals/t:Principal/t:UserId", namespace))
    run_level = _element_text(root.find("./t:Principals/t:Principal/t:RunLevel", namespace))
    return (
        _casefolded_text(root, "./t:Triggers/t:LogonTrigger/t:Enabled", namespace) or "true",
        _normalized_identity(trigger_user, resolve_identity=resolve_identity),
        _normalized_identity(principal_user, resolve_identity=resolve_identity),
        _casefolded_text(root, "./t:Principals/t:Principal/t:LogonType", namespace),
        (run_level or "LeastPrivilege").casefold(),
        _casefolded_text(root, "./t:Settings/t:MultipleInstancesPolicy", namespace),
        _casefolded_text(root, "./t:Settings/t:Enabled", namespace) or "true",
        _element_text(root.find("./t:Settings/t:ExecutionTimeLimit", namespace)),
        _normalized_windows_path(root, "./t:Actions/t:Exec/t:Command", namespace),
        _element_text(root.find("./t:Actions/t:Exec/t:Arguments", namespace)),
        _normalized_windows_path(root, "./t:Actions/t:Exec/t:WorkingDirectory", namespace),
    )


def _normalized_identity(
    value: str | None,
    *,
    resolve_identity: WindowsIdentityResolver,
) -> str | None:
    if value is None:
        return None
    return resolve_identity(value).casefold()


def _resolve_windows_identity(value: str) -> str:
    if value.casefold().startswith("s-1-"):
        return value
    import pywintypes
    import win32security

    try:
        sid, _, _ = win32security.LookupAccountName(None, value)
    except pywintypes.error:
        return value
    return str(win32security.ConvertSidToStringSid(sid))


def _casefolded_text(
    root: ElementTree.Element,
    path: str,
    namespace: dict[str, str],
) -> str | None:
    value = _element_text(root.find(path, namespace))
    return value.casefold() if value is not None else None


def _normalized_windows_path(
    root: ElementTree.Element,
    path: str,
    namespace: dict[str, str],
) -> str | None:
    value = _element_text(root.find(path, namespace))
    return ntpath.normcase(ntpath.normpath(value)) if value is not None else None


def _element_text(element: ElementTree.Element | None) -> str | None:
    return element.text if element is not None else None


def _snapshot_is_active(snapshot: WindowsScheduledTaskSnapshot) -> bool:
    return snapshot.running_instance_count > 0 or snapshot.state in {
        _TASK_STATE_QUEUED,
        _TASK_STATE_RUNNING,
    }


def _scheduled_task_execution_state(
    snapshot: WindowsScheduledTaskSnapshot,
) -> ManagedServiceExecutionState:
    if snapshot.running_instance_count > 0 or snapshot.state == _TASK_STATE_RUNNING:
        return ManagedServiceExecutionState.RUNNING
    if snapshot.state == _TASK_STATE_QUEUED:
        return ManagedServiceExecutionState.STARTING
    if snapshot.state in {_TASK_STATE_DISABLED, _TASK_STATE_READY}:
        if _task_result_is_failure(snapshot.last_result):
            return ManagedServiceExecutionState.FAILED
        return ManagedServiceExecutionState.STOPPED
    return ManagedServiceExecutionState.UNKNOWN


def _task_result_is_failure(value: int) -> bool:
    return value & 0xFFFFFFFF not in _TASK_STATUS_RESULTS


def _background_python(executable: Path) -> Path:
    candidate = executable.with_name("pythonw.exe")
    return candidate if candidate.is_file() else executable


__all__ = [
    "SCHEDULED_TASK_MANAGER_NAME",
    "SCHEDULED_TASK_SERVICE_NAME",
    "ScheduledTaskUserServiceManager",
    "render_scheduled_task_xml",
    "scheduled_task_definitions_match",
]
