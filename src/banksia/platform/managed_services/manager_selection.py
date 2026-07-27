from __future__ import annotations

import platform

from .contracts import ManagedServiceManager
from .launchd import LaunchdUserServiceManager
from .systemd import SystemdUserServiceManager


def get_managed_service_manager(
    *,
    platform_name: str | None = None,
) -> ManagedServiceManager:
    reported_platform = platform_name or platform.system()
    normalized_platform = reported_platform.casefold()
    if normalized_platform == "darwin":
        return LaunchdUserServiceManager()
    if normalized_platform == "linux":
        return SystemdUserServiceManager()
    raise RuntimeError(
        "Banksia background services support Linux and macOS only; "
        f"native {reported_platform or 'unknown'} is unsupported. "
        "On Windows, use WSL2 or run Banksia on a supported host."
    )


__all__ = ["get_managed_service_manager"]
