from __future__ import annotations

import http.client
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


def wait_for_controller_state(
    *,
    inspect: ManagedServiceInspector,
    settings: Settings,
    log_path: Path,
    attempts: int = 12,
    interval_seconds: float = 0.25,
    probe: ControllerStateProbe | None = None,
) -> ManagedServiceResult:
    active_probe = probe or probe_controller_state
    result = build_managed_service_result(
        inspection=inspect(),
        settings=settings,
        log_path=log_path,
        probe=active_probe,
    )
    for _ in range(max(0, attempts - 1)):
        if result.controller_state is not ManagedServiceControllerState.STARTING:
            break
        time.sleep(interval_seconds)
        result = build_managed_service_result(
            inspection=inspect(),
            settings=settings,
            log_path=log_path,
            probe=active_probe,
        )
    return result


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
    ready_status = _read_health_status(host, port, "/readyz")
    if ready_status == 200:
        return ManagedServiceControllerState.READY

    health_status = _read_health_status(host, port, "/healthz")
    if health_status == 200:
        return ManagedServiceControllerState.FAILED
    if execution_state is ManagedServiceExecutionState.FAILED:
        return ManagedServiceControllerState.FAILED
    if execution_state is ManagedServiceExecutionState.STOPPED:
        return ManagedServiceControllerState.STOPPED
    if execution_state in {
        ManagedServiceExecutionState.RUNNING,
        ManagedServiceExecutionState.STARTING,
    }:
        return ManagedServiceControllerState.STARTING
    return ManagedServiceControllerState.UNKNOWN


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
    "ControllerStateProbe",
    "ManagedServiceInspector",
    "build_managed_service_result",
    "probe_controller_state",
    "wait_for_controller_state",
]
