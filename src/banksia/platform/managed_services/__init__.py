from __future__ import annotations

from .contracts import (
    ManagedServiceCommandError,
    ManagedServiceCommandObserver,
    ManagedServiceManager,
    ManagedServiceStatus,
    ServiceInstallRequest,
    ServiceUninstallRequest,
)
from .launchd import LaunchdUserServiceManager
from .manager_selection import get_managed_service_manager
from .scheduled_tasks import ScheduledTaskServiceManager
from .systemd import (
    DEFAULT_SERVICE_ENV_TEXT,
    SystemdUserServiceManager,
    build_service_unit_name,
    execute_systemctl,
    get_linux_user_unit_dir,
    is_systemd_supported,
    read_systemd_status,
    render_systemd_service_unit,
    require_supported_systemd,
    resolve_systemctl_bin,
)

__all__ = [
    "DEFAULT_SERVICE_ENV_TEXT",
    "LaunchdUserServiceManager",
    "ManagedServiceCommandError",
    "ManagedServiceCommandObserver",
    "ManagedServiceManager",
    "ManagedServiceStatus",
    "ScheduledTaskServiceManager",
    "ServiceInstallRequest",
    "ServiceUninstallRequest",
    "SystemdUserServiceManager",
    "build_service_unit_name",
    "execute_systemctl",
    "get_linux_user_unit_dir",
    "get_managed_service_manager",
    "is_systemd_supported",
    "read_systemd_status",
    "render_systemd_service_unit",
    "require_supported_systemd",
    "resolve_systemctl_bin",
]
