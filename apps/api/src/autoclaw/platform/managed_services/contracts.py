from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

ManagedServiceCommandObserver = Callable[[tuple[str, ...]], None]


class ManagedServiceCommandError(RuntimeError):
    """A failed local service-manager command with bounded manager output."""

    def __init__(
        self,
        *,
        command: tuple[str, ...],
        return_code: int,
        detail: str | None,
    ) -> None:
        self.command = command
        self.return_code = return_code
        self.detail = detail
        super().__init__(detail or f"service manager exited with status {return_code}")

    @property
    def action(self) -> str:
        return self.command[2] if len(self.command) > 2 else "command"

    @property
    def service_name(self) -> str | None:
        return self.command[3] if len(self.command) > 3 else None


@dataclass(frozen=True)
class ManagedServiceStatus:
    manager: str
    service_name: str
    is_installed: bool
    is_enabled: bool
    is_running: bool
    is_healthy: bool | None
    fragment_path: str | None
    active_state: str | None
    sub_state: str | None

    def to_payload(self) -> dict[str, object]:
        return {
            "ok": True,
            "manager": self.manager,
            "service_name": self.service_name,
            "installed": self.is_installed,
            "enabled": self.is_enabled,
            "running": self.is_running,
            "healthy": self.is_healthy,
            "fragment_path": self.fragment_path,
            "active_state": self.active_state,
            "sub_state": self.sub_state,
        }


@dataclass(frozen=True)
class ServiceInstallRequest:
    config_path: Path
    service_name: str
    unit_dir: Path | None
    should_skip_start: bool
    command_observer: ManagedServiceCommandObserver | None = None


@dataclass(frozen=True)
class ServiceUninstallRequest:
    config_path: Path
    service_name: str
    unit_dir: Path | None
    should_remove_env_file: bool


class ManagedServiceManager(Protocol):
    def install(self, request: ServiceInstallRequest) -> None: ...

    def uninstall(self, request: ServiceUninstallRequest) -> None: ...

    def start(self, service_name: str) -> ManagedServiceStatus: ...

    def stop(self, service_name: str) -> ManagedServiceStatus: ...

    def restart(self, service_name: str) -> ManagedServiceStatus: ...

    def status(self, service_name: str) -> ManagedServiceStatus: ...


__all__ = [
    "ManagedServiceCommandError",
    "ManagedServiceCommandObserver",
    "ManagedServiceManager",
    "ManagedServiceStatus",
    "ServiceInstallRequest",
    "ServiceUninstallRequest",
]
