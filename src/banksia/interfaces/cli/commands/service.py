from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from banksia.config import Settings, load_settings
from banksia.interfaces.cli.commands.bootstrap import ensure_database_ready
from banksia.interfaces.cli.commands.server_config import (
    build_server_bind_check_payload,
    emit_server_bind_check_failure,
)
from banksia.interfaces.cli.context import CliContext
from banksia.interfaces.cli.progress import CliProgress
from banksia.interfaces.cli.support import coerce_path, command_env, print_json
from banksia.paths import default_config_path
from banksia.platform.managed_services import (
    SERVICE_LOG_LINE_LIMIT,
    ManagedServiceControllerState,
    ManagedServiceInspection,
    ManagedServiceManager,
    ManagedServiceResult,
    ManagedServiceStartupState,
    ManagedServiceTarget,
    build_managed_service_result,
    default_service_log_path,
    follow_service_log,
    get_managed_service_manager,
    read_service_log_tail,
    wait_for_controller_state,
)
from banksia.platform.provider_environment import (
    ensure_private_environment_file,
    provider_environment_file_path,
    read_provider_secret_environment,
)

DEFAULT_PROVIDER_ENV_TEXT = """# Banksia-managed provider credentials.
# Use `banksia setup` or `banksia providers login`; do not add other settings.
"""


def cmd_service_render(args: argparse.Namespace) -> int:
    target = build_managed_service_target(_config_path_from_args(args))
    print(get_managed_service_manager().render_definition(target))
    return 0


def cmd_service_install(
    args: argparse.Namespace,
    *,
    progress: CliProgress | None = None,
) -> int:
    active_progress = progress or CliProgress.from_args(args)
    config_path = _config_path_from_args(args)
    with command_env(config_path=config_path):
        settings = load_settings()
        asyncio.run(ensure_database_ready(progress=active_progress))

    existing_service = collect_service_status(config_path)
    if existing_service is not None and existing_service.controller_state in {
        ManagedServiceControllerState.READY,
        ManagedServiceControllerState.STARTING,
    }:
        active_progress.step(
            "server",
            "Reusing the bind target owned by the Banksia background service",
        )
    else:
        active_progress.step(
            "server",
            f"Checking local API bind target {settings.api_host}:{settings.api_port}",
        )
        server_payload = build_server_bind_check_payload(
            settings.api_host,
            settings.api_port,
        )
        if not server_payload["ok"]:
            return emit_server_bind_check_failure(
                command_name="Banksia service install",
                args=args,
                server_payload=server_payload,
                stopped_before="stopped before background service install",
            )
    environment_path = provider_environment_file_path(config_path)
    ensure_private_environment_file(
        environment_path,
        initial_text=DEFAULT_PROVIDER_ENV_TEXT,
    )
    read_provider_secret_environment(environment_path)

    manager = get_managed_service_manager()
    target = build_managed_service_target(config_path)
    active_progress.step("service", "Reconciling the Banksia background service")
    inspection = manager.install(
        target,
        should_start=not bool(getattr(args, "no_start", False)),
        command_observer=active_progress.command_args,
    )
    result = _build_result(
        manager=manager,
        inspection=inspection,
        settings=settings,
        target=target,
        should_wait=not bool(getattr(args, "no_start", False)),
    )
    active_progress.done("service", "Banksia background service installed")
    _emit_service_result(args, result)
    return 0


def cmd_service_uninstall(args: argparse.Namespace) -> int:
    config_path = _config_path_from_args(args)
    manager = get_managed_service_manager()
    target, settings = _load_target_and_settings(config_path)
    inspection = manager.uninstall(
        target,
        command_observer=CliProgress.from_args(args).command_args,
    )
    result = build_managed_service_result(
        inspection=inspection,
        settings=settings,
        log_path=target.log_path,
    )
    _emit_service_result(args, result)
    return 0


def cmd_service_status(args: argparse.Namespace) -> int:
    config_path = _config_path_from_args(args)
    target, settings = _load_target_and_settings(config_path)
    inspection = get_managed_service_manager().inspect(target)
    result = build_managed_service_result(
        inspection=inspection,
        settings=settings,
        log_path=target.log_path,
    )
    _emit_service_result(args, result)
    return 0


def cmd_service_start(args: argparse.Namespace) -> int:
    return execute_service_lifecycle(
        args,
        "start",
        progress=CliProgress.from_args(args),
    )


def cmd_service_stop(args: argparse.Namespace) -> int:
    return execute_service_lifecycle(
        args,
        "stop",
        progress=CliProgress.from_args(args),
    )


def cmd_service_restart(args: argparse.Namespace) -> int:
    return execute_service_lifecycle(
        args,
        "restart",
        progress=CliProgress.from_args(args),
    )


def cmd_service_logs(args: argparse.Namespace) -> int:
    line_count = int(getattr(args, "lines", 200))
    if not 1 <= line_count <= SERVICE_LOG_LINE_LIMIT:
        raise ValueError(f"--lines must be between 1 and {SERVICE_LOG_LINE_LIMIT}")
    log_path = default_service_log_path()
    lines = read_service_log_tail(log_path, line_count=line_count)
    if bool(getattr(args, "json", False)):
        print_json(
            {
                "ok": True,
                "log_path": str(log_path),
                "lines": lines,
                "is_missing": not log_path.exists(),
            }
        )
        return 0
    if not lines and not log_path.exists():
        print(f"No Banksia background service log exists yet: {log_path}")
    else:
        for line in lines:
            print(line)
    if not bool(getattr(args, "follow", False)):
        return 0
    try:
        for line in follow_service_log(log_path):
            if line:
                print(line, flush=True)
            else:
                time.sleep(0.25)
    except KeyboardInterrupt:
        return 0
    return 0


def execute_service_lifecycle(
    args: argparse.Namespace,
    operation: str,
    *,
    progress: CliProgress,
) -> int:
    config_path = _config_path_from_args(args)
    target, settings = _load_target_and_settings(config_path)
    manager = get_managed_service_manager()
    action = getattr(manager, operation)
    inspection = action(
        target,
        command_observer=progress.command_args,
    )
    result = _build_result(
        manager=manager,
        inspection=inspection,
        settings=settings,
        target=target,
        should_wait=operation in {"start", "restart"},
    )
    progress.done("service", f"Background service {operation} complete")
    _emit_service_result(args, result)
    return 0


def collect_service_status(config_path: Path) -> ManagedServiceResult | None:
    try:
        target, settings = _load_target_and_settings(config_path)
        inspection = get_managed_service_manager().inspect(target)
        return build_managed_service_result(
            inspection=inspection,
            settings=settings,
            log_path=target.log_path,
        )
    except RuntimeError:
        return None


def build_managed_service_target(config_path: Path) -> ManagedServiceTarget:
    return ManagedServiceTarget(
        config_path=config_path,
        python_executable=Path(sys.executable).absolute(),
        log_path=default_service_log_path(),
    )


def render_service_definition(
    *,
    python_executable: Path,
    config_path: Path,
    log_path: Path | None = None,
    manager: ManagedServiceManager | None = None,
) -> str:
    target = ManagedServiceTarget(
        config_path=config_path,
        python_executable=python_executable,
        log_path=log_path or default_service_log_path(),
    )
    return (manager or get_managed_service_manager()).render_definition(target)


def _load_target_and_settings(
    config_path: Path,
) -> tuple[ManagedServiceTarget, Settings]:
    with command_env(config_path=config_path):
        settings = load_settings()
    return build_managed_service_target(config_path), settings


def _build_result(
    *,
    manager: ManagedServiceManager,
    inspection: ManagedServiceInspection,
    settings: Settings,
    target: ManagedServiceTarget,
    should_wait: bool,
) -> ManagedServiceResult:
    if should_wait:
        return wait_for_controller_state(
            inspect=lambda: manager.inspect(target),
            settings=settings,
            log_path=target.log_path,
        )
    return build_managed_service_result(
        inspection=inspection,
        settings=settings,
        log_path=target.log_path,
    )


def _emit_service_result(
    args: argparse.Namespace,
    result: ManagedServiceResult,
) -> None:
    if bool(getattr(args, "json", False)):
        print_json(result.to_payload())
    else:
        _print_service_status(result)


def _config_path_from_args(args: argparse.Namespace) -> Path:
    return coerce_path(getattr(args, "config", default_config_path()))


def _print_service_status(result: ManagedServiceResult) -> None:
    context = CliContext()
    if not context.rich_enabled():
        _print_plain_service_status(result)
        return

    label, style, symbol = _service_state(result)
    summary = Text.assemble((f"{symbol}  ", style), (label, f"bold {style}"))
    facts = Table.grid(padding=(0, 2))
    facts.add_column(style="muted", no_wrap=True)
    facts.add_column(overflow="fold")
    facts.add_row("Definition", _definition_label(result))
    facts.add_row("Starts at sign-in", _startup_label(result))
    facts.add_row("Controller", result.controller_state.value.replace("_", " ").title())
    facts.add_row("Log", str(result.log_path))
    context.console().print(
        Panel(
            Group(summary, Text(), facts),
            title="Banksia background service",
            title_align="left",
            border_style=style,
            padding=(0, 1),
        )
    )
    next_action = _service_next_action(result)
    if next_action is not None:
        context.console().print(Text.assemble(("Next  ", "muted"), (next_action, "accent")))


def _print_plain_service_status(result: ManagedServiceResult) -> None:
    label, _, _ = _service_state(result)
    print("Banksia background service")
    print(f"Status: {label.casefold()}")
    print(f"Definition: {_definition_label(result)}")
    print(f"Starts at sign-in: {_startup_label(result)}")
    print(f"Controller: {result.controller_state.value}")
    print(f"Log: {result.log_path}")
    next_action = _service_next_action(result)
    if next_action is not None:
        print(f"Next: {next_action}")


def _service_state(result: ManagedServiceResult) -> tuple[str, str, str]:
    if not result.inspection.is_installed:
        return "Not installed", "muted", "○"
    if result.controller_state is ManagedServiceControllerState.READY:
        return "Ready", "success", "✓"
    if result.controller_state is ManagedServiceControllerState.STARTING:
        return "Starting", "warn", "!"
    if result.controller_state is ManagedServiceControllerState.FAILED:
        return "Needs attention", "error", "!"
    if result.controller_state is ManagedServiceControllerState.STOPPED:
        return "Stopped", "warn", "○"
    return "Status unknown", "warn", "!"


def _definition_label(result: ManagedServiceResult) -> str:
    if not result.inspection.is_installed:
        return "Not installed"
    if result.inspection.definition_path is None:
        return "Installed"
    return str(result.inspection.definition_path)


def _startup_label(result: ManagedServiceResult) -> str:
    labels = {
        ManagedServiceStartupState.ENABLED: "Enabled",
        ManagedServiceStartupState.DISABLED: "Disabled",
        ManagedServiceStartupState.UNKNOWN: "Unknown",
    }
    return labels[result.inspection.startup_state]


def _service_next_action(result: ManagedServiceResult) -> str | None:
    if not result.inspection.is_installed:
        return "banksia service install"
    if result.controller_state in {
        ManagedServiceControllerState.FAILED,
        ManagedServiceControllerState.UNKNOWN,
    }:
        return "banksia service logs --lines 200"
    if result.controller_state is ManagedServiceControllerState.STOPPED:
        return "banksia service start"
    return None


__all__ = [
    "build_managed_service_target",
    "cmd_service_install",
    "cmd_service_logs",
    "cmd_service_render",
    "cmd_service_restart",
    "cmd_service_start",
    "cmd_service_status",
    "cmd_service_stop",
    "cmd_service_uninstall",
    "collect_service_status",
    "render_service_definition",
]
