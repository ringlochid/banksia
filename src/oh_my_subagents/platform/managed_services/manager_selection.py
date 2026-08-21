from __future__ import annotations

import platform

from oh_my_subagents.product_identity import OMS_IDENTITY, ProductIdentity

from .contracts import ManagedServiceManager
from .launchd import LaunchdUserServiceManager
from .scheduled_tasks import ScheduledTaskUserServiceManager
from .systemd import SystemdUserServiceManager


def get_managed_service_manager(
    *,
    platform_name: str | None = None,
    identity: ProductIdentity = OMS_IDENTITY,
) -> ManagedServiceManager:
    reported_platform = platform_name or platform.system()
    normalized_platform = reported_platform.casefold()
    if normalized_platform == "darwin":
        return LaunchdUserServiceManager(service_name=identity.launchd_service_name)
    if normalized_platform == "linux":
        return SystemdUserServiceManager(service_name=identity.systemd_service_name)
    if normalized_platform == "windows":
        return ScheduledTaskUserServiceManager(service_name=identity.scheduled_task_service_name)
    raise RuntimeError(
        "Oh My Subagents background services support Linux, macOS, and Windows only; "
        f"native {reported_platform or 'unknown'} is unsupported. "
        "Run Oh My Subagents on a supported host."
    )


__all__ = ["get_managed_service_manager"]
