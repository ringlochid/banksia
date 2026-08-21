from __future__ import annotations

from typing import Any

import click

from oh_my_subagents.interfaces.cli.commands.service import (
    cmd_service_install,
    cmd_service_logs,
    cmd_service_render,
    cmd_service_restart,
    cmd_service_start,
    cmd_service_status,
    cmd_service_stop,
    cmd_service_uninstall,
)

from .root_support import (
    build_argument_namespace,
    config_option,
    invoke_handler_result,
)


@click.group("service", help="Manage the per-user Oh My Subagents background service.")
def service_group() -> None:
    return None


@service_group.command("render", help="Print this host's native service definition.")
@config_option
def service_render_command(config: str) -> int:
    return invoke_handler_result(cmd_service_render(build_argument_namespace(config=config)))


@service_group.command("install", help="Install and optionally start the background service.")
@config_option
@click.option("--no-start", is_flag=True)
@click.option("--verbose", is_flag=True, help="Show nested command output when available.")
@click.option("--no-color", is_flag=True, help="Disable ANSI color output.")
@click.option("--plain", is_flag=True, help="Disable rich styling.")
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def service_install_command(**kwargs: Any) -> int:
    return invoke_handler_result(
        cmd_service_install(build_argument_namespace(**kwargs, json=kwargs["is_json_output"]))
    )


@service_group.command("uninstall", help="Remove the background service definition.")
@config_option
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def service_uninstall_command(config: str, is_json_output: bool) -> int:
    return invoke_handler_result(
        cmd_service_uninstall(build_argument_namespace(config=config, json=is_json_output))
    )


@service_group.command("start", help="Start the installed background service.")
@config_option
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def service_start_command(config: str, is_json_output: bool) -> int:
    return invoke_handler_result(
        cmd_service_start(build_argument_namespace(config=config, json=is_json_output))
    )


@service_group.command("stop", help="Stop the background service without uninstalling it.")
@config_option
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def service_stop_command(config: str, is_json_output: bool) -> int:
    return invoke_handler_result(
        cmd_service_stop(build_argument_namespace(config=config, json=is_json_output))
    )


@service_group.command("restart", help="Restart the installed background service.")
@config_option
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def service_restart_command(config: str, is_json_output: bool) -> int:
    return invoke_handler_result(
        cmd_service_restart(build_argument_namespace(config=config, json=is_json_output))
    )


@service_group.command("status", help="Inspect installation and controller readiness.")
@config_option
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def service_status_command(config: str, is_json_output: bool) -> int:
    return invoke_handler_result(
        cmd_service_status(build_argument_namespace(config=config, json=is_json_output))
    )


@service_group.command("logs", help="Read the bounded background-service log.")
@click.option(
    "--lines",
    type=click.IntRange(1, 2000),
    default=200,
    show_default=True,
)
@click.option(
    "--follow",
    "should_follow",
    is_flag=True,
    help="Follow new log lines until interrupted.",
)
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def service_logs_command(
    lines: int,
    should_follow: bool,
    is_json_output: bool,
) -> int:
    if should_follow and is_json_output:
        raise click.UsageError("--follow cannot be combined with --json")
    return invoke_handler_result(
        cmd_service_logs(
            build_argument_namespace(
                lines=lines,
                follow=should_follow,
                json=is_json_output,
            )
        )
    )


__all__ = ["service_group"]
