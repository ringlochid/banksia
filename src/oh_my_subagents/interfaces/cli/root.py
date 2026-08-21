from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from oh_my_subagents.config import DEFAULT_API_PORT, DEFAULT_LOG_LEVEL
from oh_my_subagents.interfaces.cli.commands.bootstrap import (
    cmd_db_reset,
    cmd_db_upgrade,
    cmd_init,
    cmd_serve,
)
from oh_my_subagents.interfaces.cli.commands.config_view import cmd_config_path, cmd_config_show
from oh_my_subagents.interfaces.cli.commands.initialization import (
    guide_local_initialization,
)
from oh_my_subagents.interfaces.cli.commands.operator import (
    cmd_operator_disable,
    cmd_operator_setup,
    cmd_operator_status,
    guide_operator_setup,
)
from oh_my_subagents.interfaces.cli.commands.provider_setup import (
    guide_provider_setup,
)
from oh_my_subagents.interfaces.cli.commands.providers import (
    cmd_providers_check,
    cmd_providers_configure,
    cmd_providers_identity,
    cmd_providers_list,
    cmd_providers_set_default,
    cmd_providers_status,
    cmd_setup,
)
from oh_my_subagents.interfaces.cli.commands.settings import (
    guide_settings,
    should_run_guided_flow,
)
from oh_my_subagents.interfaces.cli.commands.status import cmd_status
from oh_my_subagents.interfaces.cli.commands.task import cmd_task_start
from oh_my_subagents.interfaces.cli.commands.workflow import (
    cmd_workflow_export,
    cmd_workflow_import,
)
from oh_my_subagents.interfaces.cli.migration import cmd_migrate_from_banksia
from oh_my_subagents.interfaces.cli.providers.inspection import PROVIDER_ORDER
from oh_my_subagents.paths import default_config_path, legacy_default_config_path

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
from .service_commands import service_group

PROVIDER_CHOICE = click.Choice([provider.value for provider in PROVIDER_ORDER])
OPERATOR_PROVIDER_CHOICE = click.Choice(("codex", "claude"))


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog=ROOT_HELP_EPILOG,
    help="Oh My Subagents: durable supervision for accountable AI teams.",
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


cli.add_command(service_group)


@cli.command(
    "migrate-from-banksia",
    help="Copy legacy local state and replace the installed background service.",
)
@click.option(
    "--source-config",
    type=click.Path(file_okay=True, dir_okay=False, path_type=Path),
    default=legacy_default_config_path,
    show_default=True,
)
@click.option(
    "--config",
    type=click.Path(file_okay=True, dir_okay=False, path_type=Path),
    default=default_config_path,
    show_default=True,
    help="Target OMS config path.",
)
@click.option(
    "--no-service",
    is_flag=True,
    help="Copy state without inspecting or replacing a native service.",
)
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def migrate_from_banksia_command(
    source_config: Path,
    config: Path,
    no_service: bool,
    is_json_output: bool,
) -> int:
    return invoke_handler_result(
        cmd_migrate_from_banksia(
            build_argument_namespace(
                source_config=source_config,
                config=config,
                no_service=no_service,
                json=is_json_output,
            )
        )
    )


@cli.command(
    "init",
    help=(
        "Initialize local controller state and optionally configure a Task provider and Operator."
    ),
)
@config_option
@click.option("--data-dir")
@click.option("--database-url")
@click.option(
    "--workspace",
    type=click.Path(
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        path_type=Path,
    ),
    help="Existing default workspace for HTTP, Console, and Operator Task start.",
)
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
@click.option(
    "--service-log",
    type=click.Path(
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
        path_type=Path,
    ),
    hidden=True,
)
def serve_command(config: str, service_log: Path | None) -> int:
    return invoke_handler_result(
        cmd_serve(
            build_argument_namespace(
                config=config,
                service_log=service_log,
            )
        )
    )


@cli.command("status")
@config_option
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def status_command(config: str, is_json_output: bool) -> int:
    return invoke_handler_result(
        cmd_status(build_argument_namespace(config=config, json=is_json_output))
    )


@cli.command(
    "setup",
    help=("Open the interactive settings hub, or configure one Task provider noninteractively."),
)
@config_option
@click.option("--provider", type=PROVIDER_CHOICE)
@click.option("--model")
@click.option("--effort")
@click.option("--extension-mode", type=click.Choice(("inherit", "isolated")))
@click.option(
    "--non-interactive",
    "is_non_interactive",
    is_flag=True,
    help="Disable guided prompts for scripts and automation.",
)
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def setup_command(**kwargs: Any) -> int:
    args = build_argument_namespace(**kwargs, json=kwargs["is_json_output"])
    is_guided = should_run_guided_flow(
        is_non_interactive=kwargs["is_non_interactive"],
        is_json_output=kwargs["is_json_output"],
    )
    if is_guided:
        handler = guide_provider_setup if kwargs["provider"] is not None else guide_settings
    else:
        handler = cmd_setup
    return invoke_handler_result(handler(args))


@cli.group("operator", help="Configure and inspect the separate Oh My Subagents Operator.")
def operator_group() -> None:
    return None


@operator_group.command(
    "setup",
    help="Configure Operator while preserving saved choices unless you change them.",
)
@config_option
@click.option("--provider", type=OPERATOR_PROVIDER_CHOICE)
@click.option("--model", help="Optional Operator-specific provider model.")
@click.option("--effort", help="Optional Operator-specific reasoning effort.")
@click.option(
    "--non-interactive",
    "is_non_interactive",
    is_flag=True,
    help="Disable guided prompts for scripts and automation.",
)
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def operator_setup_command(**kwargs: Any) -> int:
    args = build_argument_namespace(**kwargs, json=kwargs["is_json_output"])
    handler = (
        guide_operator_setup
        if should_run_guided_flow(
            is_non_interactive=kwargs["is_non_interactive"],
            is_json_output=kwargs["is_json_output"],
        )
        else cmd_operator_setup
    )
    return invoke_handler_result(handler(args))


@operator_group.command(
    "status",
    help="Show saved and effective Operator configuration without a provider call.",
)
@config_option
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def operator_status_command(config: str, is_json_output: bool) -> int:
    return invoke_handler_result(
        cmd_operator_status(
            build_argument_namespace(
                config=config,
                json=is_json_output,
            )
        )
    )


@operator_group.command(
    "disable",
    help="Remove only the saved Operator selection; keep provider routes enabled.",
)
@config_option
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON output only.")
def operator_disable_command(config: str, is_json_output: bool) -> int:
    return invoke_handler_result(
        cmd_operator_disable(
            build_argument_namespace(
                config=config,
                json=is_json_output,
            )
        )
    )


@cli.group("providers", help="Configure Task provider routes and inspect readiness.")
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
@click.option("--extension-mode", type=click.Choice(("inherit", "isolated")))
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
    type=click.Choice(("subscription", "api-key")),
    help="Use a provider subscription login or API key.",
)
@click.option(
    "--secret-stdin",
    is_flag=True,
    help="Read an API key from standard input.",
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


@cli.group("workflow")
def workflow_group() -> None:
    return None


@workflow_group.command("import")
@config_option
@click.option("--file", "file_path", required=True, help="Workflow file path or '-' for stdin.")
@click.option("--format", "file_format", type=click.Choice(("json", "yaml")))
@click.option(
    "--etag",
    "expected_etag",
    help="Current opaque draft ETag; required when replacing an existing draft.",
)
@click.option("--json", "is_json_output", is_flag=True, help="Emit JSON status output only.")
def workflow_import_command(
    config: str,
    file_path: str,
    file_format: str | None,
    expected_etag: str | None,
    is_json_output: bool,
) -> int:
    return invoke_handler_result(
        cmd_workflow_import(
            build_argument_namespace(
                config=config,
                file=file_path,
                format=file_format,
                expected_etag=expected_etag,
                json=is_json_output,
            )
        )
    )


@workflow_group.command("export")
@config_option
@click.argument("workflow_id")
@click.option("--revision", type=click.IntRange(min=1))
@click.option("--format", "file_format", type=click.Choice(("json", "yaml")))
@click.option("--output", help="Output file path or '-' for stdout.")
@click.option(
    "--force",
    "should_force",
    is_flag=True,
    help="Overwrite an existing output file.",
)
def workflow_export_command(
    config: str,
    workflow_id: str,
    revision: int | None,
    file_format: str | None,
    output: str | None,
    should_force: bool,
) -> int:
    return invoke_handler_result(
        cmd_workflow_export(
            build_argument_namespace(
                config=config,
                workflow_id=workflow_id,
                revision=revision,
                format=file_format,
                output=output,
                should_force=should_force,
            )
        )
    )


@cli.group("task")
def task_group() -> None:
    return None


@task_group.command("start")
@config_option
@click.option(
    "--json",
    "json_sources",
    multiple=True,
    metavar="SOURCE",
    help="Strict inline JSON, @file, or '-' for stdin.",
)
def task_start_command(config: str, json_sources: tuple[str, ...]) -> int:
    return invoke_handler_result(
        cmd_task_start(build_argument_namespace(config=config, json_sources=json_sources))
    )
