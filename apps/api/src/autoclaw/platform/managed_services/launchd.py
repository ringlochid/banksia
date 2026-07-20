from __future__ import annotations

from .contracts import (
    ManagedServiceStatus,
    ServiceInstallRequest,
    ServiceUninstallRequest,
)


class LaunchdUserServiceManager:
    def _unsupported(self) -> RuntimeError:
        return RuntimeError(
            "AutoClaw launchd service management is not implemented in this checkout"
        )

    def install(self, request: ServiceInstallRequest) -> None:
        del request
        raise self._unsupported()

    def uninstall(self, request: ServiceUninstallRequest) -> None:
        del request
        raise self._unsupported()

    def start(self, service_name: str) -> ManagedServiceStatus:
        del service_name
        raise self._unsupported()

    def stop(self, service_name: str) -> ManagedServiceStatus:
        del service_name
        raise self._unsupported()

    def restart(self, service_name: str) -> ManagedServiceStatus:
        del service_name
        raise self._unsupported()

    def status(self, service_name: str) -> ManagedServiceStatus:
        del service_name
        raise self._unsupported()


__all__ = ["LaunchdUserServiceManager"]
