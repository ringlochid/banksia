from __future__ import annotations

from .contracts import (
    ManagedServiceCommandError,
    ManagedServiceCommandObserver,
    ManagedServiceControllerState,
    ManagedServiceExecutionState,
    ManagedServiceInspection,
    ManagedServiceInstallationState,
    ManagedServiceManager,
    ManagedServiceResult,
    ManagedServiceStartupState,
    ManagedServiceTarget,
)
from .controller_status import (
    build_managed_service_result,
    probe_controller_state,
    wait_for_controller_state,
)
from .launchd import (
    LAUNCHD_MANAGER_NAME,
    LAUNCHD_SERVICE_NAME,
    LaunchdUserServiceManager,
    render_launch_agent_plist,
)
from .manager_selection import get_managed_service_manager
from .service_logs import (
    SERVICE_LOG_LINE_LIMIT,
    configure_service_logging,
    default_service_log_path,
    follow_service_log,
    read_service_log_tail,
)
from .systemd import (
    SYSTEMD_MANAGER_NAME,
    SYSTEMD_SERVICE_NAME,
    SystemdUserServiceManager,
    get_linux_user_unit_dir,
    is_systemd_supported,
    parse_systemd_show,
    render_systemd_service_unit,
)

__all__ = [
    "LAUNCHD_MANAGER_NAME",
    "LAUNCHD_SERVICE_NAME",
    "SERVICE_LOG_LINE_LIMIT",
    "SYSTEMD_MANAGER_NAME",
    "SYSTEMD_SERVICE_NAME",
    "LaunchdUserServiceManager",
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
    "SystemdUserServiceManager",
    "build_managed_service_result",
    "configure_service_logging",
    "default_service_log_path",
    "follow_service_log",
    "get_linux_user_unit_dir",
    "get_managed_service_manager",
    "is_systemd_supported",
    "parse_systemd_show",
    "probe_controller_state",
    "read_service_log_tail",
    "render_launch_agent_plist",
    "render_systemd_service_unit",
    "wait_for_controller_state",
]
