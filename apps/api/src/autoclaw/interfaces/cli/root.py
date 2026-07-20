from __future__ import annotations

from typing import Any

import click

from autoclaw.config import DEFAULT_API_PORT, DEFAULT_LOG_LEVEL
from autoclaw.interfaces.cli.commands.bootstrap import (
    cmd_db_reset,
    cmd_db_upgrade,
    cmd_init,
    cmd_serve,
)
from autoclaw.interfaces.cli.commands.config_view import cmd_config_path, cmd_config_show
from autoclaw.interfaces.cli.commands.definitions import cmd_definitions_import
from autoclaw.interfaces.cli.commands.guided_setup import (
    guide_local_initialization,
    guide_provider_setup,
    should_run_guided_flow,
)
from autoclaw.interfaces.cli.commands.providers import (
    cmd_providers_check,
    cmd_providers_configure,
    cmd_providers_identity,
    cmd_providers_list,
    cmd_providers_set_default,
    cmd_providers_status,
    cmd_setup,
)
from autoclaw.interfaces.cli.commands.service import (
    DEFAULT_SERVICE_NAME,
    cmd_service_install,
    cmd_service_render,
    cmd_service_restart,
    cmd_service_start,
    cmd_service_status,
    cmd_service_stop,
    cmd_service_uninstall,
)
from autoclaw.interfaces.cli.commands.status import cmd_status
from autoclaw.interfaces.cli.commands.task_compose import cmd_task_compose_start
from autoclaw.interfaces.cli.providers.inspection import PROVIDER_ORDER

from .context import CliContext
from .help import ROOT_HELP_EPILOG
from .root_support import (
    build_argument_namespace,
    config_option,
    default_config_text,
    invoke_handler_result,
    output_options,
    package_version,
)

PROVIDER_CHOICE = click.Choice([provider.value for provider in PROVIDER_ORDER])


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog=ROOT_HELP_EPILOG,
    help="AutoClaw local-first workflow control plane.",
    invoke_without_command=True,
    no_args_is_help=False,
)
@click.option(
    "--debug",
    "is_debug",
    is_flag=True,
    help="Include a traceback when a command fails.",
)
@click.version_option(package_version(), "--version", "-V")
@click.pass_context
def cli(ctx: click.Context, is_debug: bool) -> int | None:
    runtime = ctx.obj if isinstance(ctx.obj, CliContext) else CliContext()
    ctx.obj = runtime.overlay(is_debug=runtime.is_debug or is_debug)
    if ctx.invoked_subcommand is None:
        return cmd_status(build_argument_namespace(config=default_config_text(), json=False))
    return None


@cli.command("init")
@config_option
@click.option("--data-dir")
@click.option("--database-url")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=DEFAULT_API_PORT, type=int, show_default=True)
@click.option("--log-level", default=DEFAULT_LOG_LEVEL, show_default=True)
@click.option("--force", is_flag=True)
@click.option("--skip-db-upgrade", is_flag=True)
@click.option(
    "--non-interactive",
    "is_non_interactive",
    is_flag=True,
    help="Disable guided prompts for scripts and automation.",
)
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def init_command(**kwargs: Any) -> int:
    args = build_argument_namespace(**kwargs, json=kwargs["is_json_output"])
    handler = (
        guide_local_initialization
        if should_run_guided_flow(
            is_non_interactive=kwargs["is_non_interactive"],
            is_json_output=kwargs["is_json_output"],
        )
        else cmd_init
    )
    return invoke_handler_result(handler(args))


@cli.command("serve")
@config_option
def serve_command(config: str) -> int:
    return invoke_handler_result(cmd_serve(build_argument_namespace(config=config)))


@cli.command("status")
@config_option
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def status_command(config: str, is_json_output: bool) -> int:
    return invoke_handler_result(
        cmd_status(build_argument_namespace(config=config, json=is_json_output))
    )


@cli.command("setup")
@config_option
@click.option("--provider", type=PROVIDER_CHOICE)
@click.option("--model")
@click.option("--effort")
@click.option("--cli-path", help="OpenClaw CLI command or absolute executable path.")
@click.option("--gateway-url")
@click.option("--gateway-profile")
@click.option("--gateway-auth-mode", type=click.Choice(("token", "password")))
@click.option(
    "--non-interactive",
    "is_non_interactive",
    is_flag=True,
    help="Disable guided prompts for scripts and automation.",
)
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def setup_command(**kwargs: Any) -> int:
    args = build_argument_namespace(**kwargs, json=kwargs["is_json_output"])
    handler = (
        guide_provider_setup
        if should_run_guided_flow(
            is_non_interactive=kwargs["is_non_interactive"],
            is_json_output=kwargs["is_json_output"],
        )
        else cmd_setup
    )
    return invoke_handler_result(handler(args))


@cli.group("providers")
def providers_group() -> None:
    return None


@providers_group.command("list")
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def providers_list_command(is_json_output: bool) -> int:
    return invoke_handler_result(cmd_providers_list(build_argument_namespace(json=is_json_output)))


@providers_group.command("status")
@config_option
@click.argument("provider", required=False, type=PROVIDER_CHOICE)
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def providers_status_command(
    config: str,
    provider: str | None,
    is_json_output: bool,
) -> int:
    return invoke_handler_result(
        cmd_providers_status(
            build_argument_namespace(
                config=config,
                provider=provider,
                json=is_json_output,
            )
        )
    )


@providers_group.command("check")
@config_option
@click.argument("provider", type=PROVIDER_CHOICE)
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def providers_check_command(config: str, provider: str, is_json_output: bool) -> int:
    return invoke_handler_result(
        cmd_providers_check(
            build_argument_namespace(
                config=config,
                provider=provider,
                json=is_json_output,
            )
        )
    )


@providers_group.command("configure")
@config_option
@click.argument("provider", type=PROVIDER_CHOICE)
@click.option("--model")
@click.option("--effort")
@click.option("--cli-path", help="OpenClaw CLI command or absolute executable path.")
@click.option("--gateway-url")
@click.option("--gateway-profile")
@click.option("--gateway-auth-mode", type=click.Choice(("token", "password")))
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def providers_configure_command(**kwargs: Any) -> int:
    return invoke_handler_result(
        cmd_providers_configure(build_argument_namespace(**kwargs, json=kwargs["is_json_output"]))
    )


@providers_group.command("set-default")
@config_option
@click.argument("provider", type=PROVIDER_CHOICE)
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def providers_set_default_command(
    config: str,
    provider: str,
    is_json_output: bool,
) -> int:
    return invoke_handler_result(
        cmd_providers_set_default(
            build_argument_namespace(
                config=config,
                provider=provider,
                json=is_json_output,
            )
        )
    )


@providers_group.command("login")
@config_option
@click.argument("provider", type=PROVIDER_CHOICE)
@click.option(
    "--method",
    type=click.Choice(("subscription", "api-key", "token", "password")),
    help="Codex/Claude: subscription or api-key. OpenClaw: token or password.",
)
@click.option(
    "--secret-stdin",
    is_flag=True,
    help="Read an API key, Gateway token, or Gateway password from standard input.",
)
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def providers_login_command(**kwargs: Any) -> int:
    return invoke_handler_result(
        cmd_providers_identity(
            build_argument_namespace(**kwargs, json=kwargs["is_json_output"]),
            "login",
        )
    )


@providers_group.command("logout")
@config_option
@click.argument("provider", type=PROVIDER_CHOICE)
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def providers_logout_command(config: str, provider: str, is_json_output: bool) -> int:
    return invoke_handler_result(
        cmd_providers_identity(
            build_argument_namespace(config=config, provider=provider, json=is_json_output),
            "logout",
        )
    )


@cli.group("config")
def config_group() -> None:
    return None


@config_group.command("path")
@config_option
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def config_path_command(config: str, is_json_output: bool) -> int:
    return invoke_handler_result(
        cmd_config_path(build_argument_namespace(config=config, json=is_json_output))
    )


@config_group.command("show")
@config_option
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def config_show_command(config: str, is_json_output: bool) -> int:
    return invoke_handler_result(
        cmd_config_show(build_argument_namespace(config=config, json=is_json_output))
    )


@cli.group("db")
def db_group() -> None:
    return None


@db_group.command("upgrade")
@config_option
@click.option("--revision", default="head", show_default=True)
@output_options
def db_upgrade_command(**kwargs: Any) -> int:
    return invoke_handler_result(
        cmd_db_upgrade(build_argument_namespace(**kwargs, json=kwargs["json_output"]))
    )


@db_group.command("reset")
@config_option
@click.option("--revision", default="head", show_default=True)
@output_options
def db_reset_command(**kwargs: Any) -> int:
    return invoke_handler_result(
        cmd_db_reset(build_argument_namespace(**kwargs, json=kwargs["json_output"]))
    )


@cli.group("definitions")
def definitions_group() -> None:
    return None


@definitions_group.command("import")
@config_option
@click.option("--file", "file_path")
@click.option(
    "--overwrite",
    type=click.Choice(["reject", "allow_new_revision"]),
    default="reject",
    show_default=True,
)
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def definitions_import_command(
    config: str,
    file_path: str | None,
    overwrite: str,
    is_json_output: bool,
) -> int:
    return invoke_handler_result(
        cmd_definitions_import(
            build_argument_namespace(
                config=config,
                file=file_path,
                overwrite=overwrite,
                json=is_json_output,
            )
        )
    )


@cli.group("task-compose")
def task_compose_group() -> None:
    return None


@task_compose_group.command("start")
@config_option
@click.option("--file", "file_path", required=True)
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def task_compose_start_command(config: str, file_path: str, is_json_output: bool) -> int:
    return invoke_handler_result(
        cmd_task_compose_start(
            build_argument_namespace(config=config, file=file_path, json=is_json_output)
        )
    )


@cli.group("service")
def service_group() -> None:
    return None


@service_group.command("render")
@config_option
@click.option("--name", default=DEFAULT_SERVICE_NAME, show_default=True)
def service_render_command(**kwargs: Any) -> int:
    return invoke_handler_result(cmd_service_render(build_argument_namespace(**kwargs)))


@service_group.command("install")
@config_option
@click.option("--name", default=DEFAULT_SERVICE_NAME, show_default=True)
@click.option("--unit-dir")
@click.option("--port", type=int)
@click.option("--no-start", is_flag=True)
@click.option("--verbose", is_flag=True, help="Show nested command output when available.")
@click.option("--no-color", is_flag=True, help="Disable ANSI color output.")
@click.option("--plain", is_flag=True, help="Disable rich styling.")
def service_install_command(**kwargs: Any) -> int:
    return invoke_handler_result(cmd_service_install(build_argument_namespace(**kwargs)))


@service_group.command("uninstall")
@config_option
@click.option("--name", default=DEFAULT_SERVICE_NAME, show_default=True)
@click.option("--unit-dir")
@click.option("--remove-env-file", is_flag=True)
def service_uninstall_command(**kwargs: Any) -> int:
    return invoke_handler_result(cmd_service_uninstall(build_argument_namespace(**kwargs)))


@service_group.command("start")
@click.option("--name", default=DEFAULT_SERVICE_NAME, show_default=True)
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def service_start_command(name: str, is_json_output: bool) -> int:
    return invoke_handler_result(
        cmd_service_start(build_argument_namespace(name=name, json=is_json_output))
    )


@service_group.command("stop")
@click.option("--name", default=DEFAULT_SERVICE_NAME, show_default=True)
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def service_stop_command(name: str, is_json_output: bool) -> int:
    return invoke_handler_result(
        cmd_service_stop(build_argument_namespace(name=name, json=is_json_output))
    )


@service_group.command("restart")
@click.option("--name", default=DEFAULT_SERVICE_NAME, show_default=True)
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def service_restart_command(name: str, is_json_output: bool) -> int:
    return invoke_handler_result(
        cmd_service_restart(build_argument_namespace(name=name, json=is_json_output))
    )


@service_group.command("status")
@click.option("--name", default=DEFAULT_SERVICE_NAME, show_default=True)
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def service_status_command(name: str, is_json_output: bool) -> int:
    return invoke_handler_result(
        cmd_service_status(build_argument_namespace(name=name, json=is_json_output))
    )
