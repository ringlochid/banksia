from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Protocol

ManagedServiceCommandObserver = Callable[[tuple[str, ...]], None]


class ManagedServiceInstallationState(StrEnum):
    ABSENT = "absent"
    INSTALLED = "installed"


class ManagedServiceStartupState(StrEnum):
    DISABLED = "disabled"
    ENABLED = "enabled"
    UNKNOWN = "unknown"


class ManagedServiceExecutionState(StrEnum):
    FAILED = "failed"
    RUNNING = "running"
    STARTING = "starting"
    STOPPED = "stopped"
    UNKNOWN = "unknown"


class ManagedServiceControllerState(StrEnum):
    FAILED = "failed"
    READY = "ready"
    STARTING = "starting"
    STOPPED = "stopped"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ManagedServiceTarget:
    config_path: Path
    python_executable: Path
    log_path: Path


@dataclass(frozen=True, slots=True)
class ManagedServiceInspection:
    manager: str
    service_name: str
    definition_path: Path | None
    installation_state: ManagedServiceInstallationState
    startup_state: ManagedServiceStartupState
    execution_state: ManagedServiceExecutionState
    is_definition_current: bool
    technical_state: tuple[tuple[str, str], ...] = ()

    @property
    def is_installed(self) -> bool:
        return self.installation_state is ManagedServiceInstallationState.INSTALLED

    @property
    def is_running(self) -> bool:
        return self.execution_state is ManagedServiceExecutionState.RUNNING

    def with_execution_state(
        self,
        execution_state: ManagedServiceExecutionState,
    ) -> ManagedServiceInspection:
        return replace(self, execution_state=execution_state)


@dataclass(frozen=True, slots=True)
class ManagedServiceResult:
    inspection: ManagedServiceInspection
    controller_state: ManagedServiceControllerState
    api_url: str
    log_path: Path

    @property
    def owns_bind_target(self) -> bool:
        return (
            self.inspection.is_installed
            and self.inspection.execution_state
            in {
                ManagedServiceExecutionState.RUNNING,
                ManagedServiceExecutionState.STARTING,
            }
            and self.controller_state
            in {
                ManagedServiceControllerState.READY,
                ManagedServiceControllerState.STARTING,
            }
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "ok": True,
            "manager": self.inspection.manager,
            "service_name": self.inspection.service_name,
            "definition_path": (
                str(self.inspection.definition_path)
                if self.inspection.definition_path is not None
                else None
            ),
            "installation_state": self.inspection.installation_state.value,
            "definition_current": self.inspection.is_definition_current,
            "startup_state": self.inspection.startup_state.value,
            "controller_state": self.controller_state.value,
            "api_url": self.api_url,
            "log_path": str(self.log_path),
        }


class ManagedServiceCommandError(RuntimeError):
    """A failed native service operation with bounded manager output."""

    def __init__(
        self,
        *,
        manager: str,
        operation: str,
        service_name: str,
        command: tuple[str, ...],
        return_code: int,
        detail: str | None,
    ) -> None:
        self.manager = manager
        self.operation = operation
        self.service_name = service_name
        self.command = command
        self.return_code = return_code
        self.detail = detail
        super().__init__(detail or f"service manager exited with status {return_code}")


class ManagedServiceManager(Protocol):
    manager_name: str
    service_name: str
    readiness_timeout_seconds: float

    def render_definition(self, target: ManagedServiceTarget) -> str: ...

    def install(
        self,
        target: ManagedServiceTarget,
        *,
        should_start: bool,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection: ...

    def uninstall(
        self,
        target: ManagedServiceTarget,
        *,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection: ...

    def start(
        self,
        target: ManagedServiceTarget,
        *,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection: ...

    def stop(
        self,
        target: ManagedServiceTarget,
        *,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection: ...

    def restart(
        self,
        target: ManagedServiceTarget,
        *,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection: ...

    def inspect(self, target: ManagedServiceTarget) -> ManagedServiceInspection: ...


def bounded_service_command_detail(
    value: str,
    *,
    limit: int = 600,
) -> str | None:
    normalized = " ".join(value.split())
    if not normalized:
        return None
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1]}…"


__all__ = [
    "ManagedServiceCommandError",
    "ManagedServiceCommandObserver",
    "ManagedServiceControllerState",
    "ManagedServiceExecutionState",
    "ManagedServiceInspection",
    "ManagedServiceInstallationState",
    "ManagedServiceManager",
    "ManagedServiceResult",
    "ManagedServiceStartupState",
    "ManagedServiceTarget",
    "bounded_service_command_detail",
]
