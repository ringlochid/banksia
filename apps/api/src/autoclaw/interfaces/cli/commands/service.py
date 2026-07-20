from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from autoclaw.config import load_settings
from autoclaw.interfaces.cli.commands.server_config import (
    build_server_bind_check_payload,
    emit_server_bind_check_failure,
    update_server_config_overrides,
)
from autoclaw.interfaces.cli.context import CliContext
from autoclaw.interfaces.cli.progress import CliProgress
from autoclaw.interfaces.cli.support import coerce_path, command_env, print_json
from autoclaw.platform.managed_services import (
    ManagedServiceStatus,
    ServiceInstallRequest,
    ServiceUninstallRequest,
    get_managed_service_manager,
)
from autoclaw.platform.managed_services.systemd import (
    build_service_unit_name,
    render_systemd_service_unit,
)

DEFAULT_SERVICE_NAME = "autoclaw"
SERVICE_MANAGER = get_managed_service_manager()


def cmd_service_render(args: argparse.Namespace) -> int:
    config_path = coerce_path(args.config)
    print(
        render_service_unit(
            python_bin=Path(sys.executable),
            config_path=config_path,
        )
    )
    return 0


def cmd_service_install(
    args: argparse.Namespace,
    *,
    progress: CliProgress | None = None,
) -> int:
    active_progress = progress or CliProgress.from_args(args)
    config_path = coerce_path(args.config)
    requested_port = getattr(args, "port", None)
    with command_env(config_path=config_path):
        initial_settings = load_settings()
    effective_port = requested_port if requested_port is not None else initial_settings.api_port
    existing_service = (
        collect_service_status(args.name)
        if requested_port is None or requested_port == initial_settings.api_port
        else None
    )
    if existing_service is not None and existing_service.is_running:
        active_progress.step(
            "server",
            "Reusing the bind target owned by the running managed service",
        )
    else:
        active_progress.step(
            "server",
            f"Checking local API bind target {initial_settings.api_host}:{effective_port}",
        )
        server_payload = build_server_bind_check_payload(
            initial_settings.api_host,
            effective_port,
        )
        if not server_payload["ok"]:
            return emit_server_bind_check_failure(
                command_name="AutoClaw service install",
                args=args,
                server_payload=server_payload,
                stopped_before="stopped before managed service install",
            )
    if requested_port is not None:
        active_progress.step("config", f"Persisting service port override {requested_port}")
        update_server_config_overrides(config_path, port=requested_port)

    active_progress.step("service", "Writing managed service unit")
    SERVICE_MANAGER.install(
        ServiceInstallRequest(
            config_path=config_path,
            service_name=args.name,
            unit_dir=coerce_path(args.unit_dir) if args.unit_dir is not None else None,
            should_skip_start=args.no_start,
            command_observer=active_progress.command_args,
        )
    )
    active_progress.done("service", "Managed service installed")
    return 0


def cmd_service_uninstall(args: argparse.Namespace) -> int:
    config_path = coerce_path(args.config)
    SERVICE_MANAGER.uninstall(
        ServiceUninstallRequest(
            config_path=config_path,
            service_name=args.name,
            unit_dir=coerce_path(args.unit_dir) if args.unit_dir is not None else None,
            should_remove_env_file=args.remove_env_file,
        )
    )
    return 0


def cmd_service_status(args: argparse.Namespace) -> int:
    snapshot = SERVICE_MANAGER.status(args.name)
    if args.json:
        print_json(snapshot.to_payload())
    else:
        _print_service_status(snapshot)
    return 0


def cmd_service_start(args: argparse.Namespace) -> int:
    progress = CliProgress.from_args(args)
    return execute_service_lifecycle(args, "start", progress=progress)


def cmd_service_stop(args: argparse.Namespace) -> int:
    return execute_service_lifecycle(args, "stop", progress=CliProgress.from_args(args))


def cmd_service_restart(args: argparse.Namespace) -> int:
    progress = CliProgress.from_args(args)
    return execute_service_lifecycle(args, "restart", progress=progress)


def execute_service_lifecycle(
    args: argparse.Namespace,
    verb: str,
    *,
    progress: CliProgress,
) -> int:
    action = getattr(SERVICE_MANAGER, verb)
    progress.command_args(("systemctl", "--user", verb, build_service_unit_name(args.name)))
    snapshot = action(args.name)
    progress.done("service", f"Managed service {verb} complete")
    if args.json:
        print_json(snapshot.to_payload())
    else:
        _print_service_status(snapshot)
    return 0


def collect_service_status(name: str = DEFAULT_SERVICE_NAME) -> ManagedServiceStatus | None:
    try:
        return SERVICE_MANAGER.status(name)
    except RuntimeError:
        return None


def render_service_unit(
    *,
    python_bin: Path,
    config_path: Path,
) -> str:
    return render_systemd_service_unit(
        python_bin=python_bin,
        config_path=config_path,
    )


def _print_service_status(snapshot: ManagedServiceStatus) -> None:
    context = CliContext()
    if not context.rich_enabled():
        _print_plain_service_status(snapshot)
        return

    label, style, symbol = _service_state(snapshot)
    summary = Text.assemble((f"{symbol}  ", style), (label, f"bold {style}"))
    facts = Table.grid(padding=(0, 2))
    facts.add_column(style="muted", no_wrap=True)
    facts.add_column(overflow="fold")
    facts.add_row("Unit", snapshot.service_name)
    facts.add_row("Manager", snapshot.manager)
    facts.add_row("Installed", "Yes" if snapshot.is_installed else "No")
    facts.add_row("Enabled", "Yes" if snapshot.is_enabled else "No")
    facts.add_row("API health", "Not checked")
    if snapshot.active_state is not None:
        facts.add_row("systemd state", snapshot.active_state)
    if snapshot.sub_state is not None:
        facts.add_row("systemd detail", snapshot.sub_state)
    if snapshot.fragment_path:
        facts.add_row("Unit file", snapshot.fragment_path)

    context.console().print(
        Panel(
            Group(summary, Text(), facts),
            title="AutoClaw service",
            title_align="left",
            border_style=style,
            padding=(0, 1),
        )
    )
    next_action = _service_next_action(snapshot)
    if next_action is not None:
        context.console().print(Text.assemble(("Next  ", "muted"), (next_action, "accent")))


def _print_plain_service_status(snapshot: ManagedServiceStatus) -> None:
    label, _, _ = _service_state(snapshot)
    print("AutoClaw service")
    print(f"Status: {label.casefold()}")
    print(f"Manager: {snapshot.manager}")
    print(f"Unit: {snapshot.service_name}")
    print(f"Installed: {str(snapshot.is_installed).lower()}")
    print(f"Enabled: {str(snapshot.is_enabled).lower()}")
    print("API health: not checked")
    if snapshot.fragment_path:
        print(f"Unit file: {snapshot.fragment_path}")
    if snapshot.active_state is not None:
        print(f"systemd state: {snapshot.active_state}")
    if snapshot.sub_state is not None:
        print(f"systemd detail: {snapshot.sub_state}")
    next_action = _service_next_action(snapshot)
    if next_action is not None:
        print(f"Next: {next_action}")


def _service_state(snapshot: ManagedServiceStatus) -> tuple[str, str, str]:
    if snapshot.is_running:
        return "Running", "success", "✓"
    if not snapshot.is_installed:
        return "Not installed", "muted", "○"
    if snapshot.active_state == "activating":
        return "Starting or retrying", "warn", "!"
    if snapshot.active_state == "failed":
        return "Failed", "error", "!"
    return "Stopped", "warn", "○"


def _service_next_action(snapshot: ManagedServiceStatus) -> str | None:
    if not snapshot.is_installed:
        return "autoclaw service install"
    if not snapshot.is_running:
        return f"journalctl --user -u {snapshot.service_name} -n 50 --no-pager"
    return None


__all__ = [
    "DEFAULT_SERVICE_NAME",
    "cmd_service_install",
    "cmd_service_render",
    "cmd_service_restart",
    "cmd_service_start",
    "cmd_service_status",
    "cmd_service_stop",
    "cmd_service_uninstall",
    "collect_service_status",
    "render_service_unit",
]
