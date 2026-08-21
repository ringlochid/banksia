from __future__ import annotations

import http.client
import socket
import time
from collections.abc import Callable
from pathlib import Path

from banksia.config import Settings, format_loopback_authority

from .contracts import (
    ManagedServiceControllerState,
    ManagedServiceExecutionState,
    ManagedServiceInspection,
    ManagedServiceResult,
)

ControllerStateProbe = Callable[
    [str, int, ManagedServiceExecutionState],
    ManagedServiceControllerState,
]
ManagedServiceInspector = Callable[[], ManagedServiceInspection]
BindTargetProbe = Callable[[str, int], bool]

DEFAULT_CONTROLLER_READINESS_TIMEOUT_SECONDS = 3.0
DEFAULT_CONTROLLER_SHUTDOWN_TIMEOUT_SECONDS = 10.0


def wait_for_controller_state(
    *,
    initial_inspection: ManagedServiceInspection,
    inspect: ManagedServiceInspector,
    settings: Settings,
    log_path: Path,
    timeout_seconds: float = DEFAULT_CONTROLLER_READINESS_TIMEOUT_SECONDS,
    interval_seconds: float = 0.25,
    probe: ControllerStateProbe | None = None,
) -> ManagedServiceResult:
    active_probe = probe or probe_controller_state
    result = build_managed_service_result(
        inspection=initial_inspection,
        settings=settings,
        log_path=log_path,
        probe=active_probe,
    )
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    pending_states = {
        ManagedServiceControllerState.FAILED,
        ManagedServiceControllerState.STARTING,
    }
    while result.controller_state in pending_states:
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            break
        time.sleep(min(max(0.0, interval_seconds), remaining_seconds))
        result = build_managed_service_result(
            inspection=inspect(),
            settings=settings,
            log_path=log_path,
            probe=active_probe,
        )
    return result


def wait_for_controller_shutdown(
    *,
    initial_inspection: ManagedServiceInspection,
    inspect: ManagedServiceInspector,
    settings: Settings,
    log_path: Path,
    timeout_seconds: float = DEFAULT_CONTROLLER_SHUTDOWN_TIMEOUT_SECONDS,
    interval_seconds: float = 0.1,
    is_bind_target_listening: BindTargetProbe | None = None,
) -> ManagedServiceResult:
    active_probe = is_bind_target_listening or probe_bind_target
    inspection = initial_inspection
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        native_is_active = inspection.execution_state in {
            ManagedServiceExecutionState.RUNNING,
            ManagedServiceExecutionState.STARTING,
        }
        bind_target_is_listening = active_probe(settings.api_host, settings.api_port)
        if not native_is_active and not bind_target_is_listening:
            return build_managed_service_result(
                inspection=inspection,
                settings=settings,
                log_path=log_path,
            )
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            detail = (
                "the native background service remained active"
                if native_is_active
                else f"the API bind target {settings.api_host}:{settings.api_port} remained in use"
            )
            raise RuntimeError(f"Oh My Subagents background service did not stop cleanly: {detail}")
        time.sleep(min(max(0.0, interval_seconds), remaining_seconds))
        inspection = inspect()


def build_managed_service_result(
    *,
    inspection: ManagedServiceInspection,
    settings: Settings,
    log_path: Path,
    probe: ControllerStateProbe | None = None,
) -> ManagedServiceResult:
    active_probe = probe or probe_controller_state
    controller_state = active_probe(
        settings.api_host,
        settings.api_port,
        inspection.execution_state,
    )
    return ManagedServiceResult(
        inspection=inspection,
        controller_state=controller_state,
        api_url=f"http://{format_loopback_authority(settings.api_host, settings.api_port)}",
        log_path=log_path,
    )


def probe_controller_state(
    host: str,
    port: int,
    execution_state: ManagedServiceExecutionState,
) -> ManagedServiceControllerState:
    if execution_state is ManagedServiceExecutionState.FAILED:
        return ManagedServiceControllerState.FAILED
    if execution_state is ManagedServiceExecutionState.STOPPED:
        return ManagedServiceControllerState.STOPPED
    if execution_state is ManagedServiceExecutionState.UNKNOWN:
        return ManagedServiceControllerState.UNKNOWN

    ready_status = _read_health_status(host, port, "/readyz")
    if ready_status == 200:
        return ManagedServiceControllerState.READY

    health_status = _read_health_status(host, port, "/healthz")
    if health_status == 200:
        return ManagedServiceControllerState.FAILED
    return ManagedServiceControllerState.STARTING


def probe_bind_target(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return True
    except OSError:
        return False


def _read_health_status(host: str, port: int, path: str) -> int | None:
    connection = http.client.HTTPConnection(host, port, timeout=0.35)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        response.read(8_192)
        return response.status
    except OSError:
        return None
    finally:
        connection.close()


__all__ = [
    "DEFAULT_CONTROLLER_READINESS_TIMEOUT_SECONDS",
    "DEFAULT_CONTROLLER_SHUTDOWN_TIMEOUT_SECONDS",
    "BindTargetProbe",
    "ControllerStateProbe",
    "ManagedServiceInspector",
    "build_managed_service_result",
    "probe_bind_target",
    "probe_controller_state",
    "wait_for_controller_shutdown",
    "wait_for_controller_state",
]
