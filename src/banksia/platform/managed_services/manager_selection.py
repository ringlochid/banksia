from __future__ import annotations

import os
import sys

from .contracts import ManagedServiceManager
from .launchd import LaunchdUserServiceManager
from .scheduled_tasks import ScheduledTaskServiceManager
from .systemd import SystemdUserServiceManager


def get_managed_service_manager() -> ManagedServiceManager:
    if os.name == "nt":
        return ScheduledTaskServiceManager()
    if sys.platform == "darwin":
        return LaunchdUserServiceManager()
    return SystemdUserServiceManager()


__all__ = ["get_managed_service_manager"]
