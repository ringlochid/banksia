from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from oh_my_subagents.product_identity import OMS_IDENTITY

_TASK_CREATE_OR_UPDATE = 6
_TASK_LOGON_INTERACTIVE_TOKEN = 3

_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class WindowsScheduledTaskSnapshot:
    definition: str
    is_enabled: bool
    state: int
    last_result: int
    running_instance_count: int


class WindowsTaskScheduler(Protocol):
    def inspect(self) -> WindowsScheduledTaskSnapshot | None: ...

    def register(self, *, definition: str, user_id: str) -> None: ...

    def delete(self) -> None: ...

    def start_task(self) -> None: ...

    def stop(self) -> None: ...


class WindowsTaskSchedulerError(RuntimeError):
    def __init__(self, *, operation: str, return_code: int, detail: str) -> None:
        self.operation = operation
        self.return_code = return_code
        self.detail = detail
        super().__init__(detail)


class ComWindowsTaskScheduler:
    """Task Scheduler 2.0 scripting API boundary for one fixed OMS task."""

    def __init__(self, *, service_name: str = OMS_IDENTITY.scheduled_task_service_name) -> None:
        folder_path, separator, task_name = service_name.rpartition("\\")
        if separator != "\\" or not folder_path.startswith("\\") or not task_name:
            raise ValueError(f"invalid scheduled Task service name: {service_name!r}")
        self._task_folder_path = folder_path
        self._task_folder_name = folder_path.removeprefix("\\")
        self._task_name = task_name

    def inspect(self) -> WindowsScheduledTaskSnapshot | None:
        def read_task() -> WindowsScheduledTaskSnapshot | None:
            service = self._connect()
            folder = self._find_folder(service)
            if folder is None:
                return None
            task = self._find_task(folder)
            if task is None:
                return None
            instances = task.GetInstances(0)
            return WindowsScheduledTaskSnapshot(
                definition=str(task.Xml),
                is_enabled=bool(task.Enabled),
                state=int(task.State),
                last_result=int(task.LastTaskResult),
                running_instance_count=int(instances.Count),
            )

        return self._invoke("inspect", read_task)

    def register(self, *, definition: str, user_id: str) -> None:
        def register_task() -> None:
            service = self._connect()
            folder = self._find_folder(service)
            if folder is None:
                root = service.GetFolder("\\")
                folder = root.CreateFolder(self._task_folder_name)
            folder.RegisterTask(
                self._task_name,
                definition,
                _TASK_CREATE_OR_UPDATE,
                user_id,
                None,
                _TASK_LOGON_INTERACTIVE_TOKEN,
            )

        self._invoke("install", register_task)

    def delete(self) -> None:
        def delete_task() -> None:
            service = self._connect()
            folder = self._find_folder(service)
            if folder is None or self._find_task(folder) is None:
                return
            folder.DeleteTask(self._task_name, 0)

        self._invoke("uninstall", delete_task)

    def start_task(self) -> None:
        self._invoke("start", lambda: self._require_task().Run(None))

    def stop(self) -> None:
        self._invoke("stop", lambda: self._require_task().Stop(0))

    @staticmethod
    def _connect() -> Any:
        import win32com.client

        service = win32com.client.Dispatch("Schedule.Service")
        service.Connect()
        return service

    def _require_task(self) -> Any:
        service = self._connect()
        folder = self._find_folder(service)
        task = self._find_task(folder) if folder is not None else None
        if task is None:
            raise WindowsTaskSchedulerError(
                operation="inspect",
                return_code=-1,
                detail="Oh My Subagents background service task is not registered",
            )
        return task

    def _find_folder(self, service: Any) -> Any | None:
        try:
            return service.GetFolder(self._task_folder_path)
        except Exception as exc:
            if _is_windows_not_found_error(exc):
                return None
            raise

    def _find_task(self, folder: Any) -> Any | None:
        try:
            return folder.GetTask(self._task_name)
        except Exception as exc:
            if _is_windows_not_found_error(exc):
                return None
            raise

    @staticmethod
    def _invoke(operation: str, action: Callable[[], _T]) -> _T:
        try:
            return action()
        except WindowsTaskSchedulerError:
            raise
        except Exception as exc:
            raise WindowsTaskSchedulerError(
                operation=operation,
                return_code=_windows_error_code(exc),
                detail=str(exc),
            ) from exc


def _is_windows_not_found_error(exc: Exception) -> bool:
    return _windows_error_code(exc) & 0xFFFFFFFF in {0x80070002, 0x80070003}


def _windows_error_code(exc: Exception) -> int:
    excepinfo = getattr(exc, "excepinfo", None)
    if isinstance(excepinfo, tuple) and len(excepinfo) >= 6:
        scode = excepinfo[5]
        if isinstance(scode, int) and scode != 0:
            return scode
    value = getattr(exc, "hresult", -1)
    return int(value) if isinstance(value, int) else -1


__all__ = [
    "ComWindowsTaskScheduler",
    "WindowsScheduledTaskSnapshot",
    "WindowsTaskScheduler",
    "WindowsTaskSchedulerError",
]
