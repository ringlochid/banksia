from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import click

from banksia.config import (
    DEFAULT_LOG_LEVEL,
    OperatorProvider,
    format_loopback_authority,
    load_settings,
)
from banksia.interfaces.cli.commands.bootstrap import cmd_init, ensure_database_ready
from banksia.interfaces.cli.commands.config_view import redact_database_url
from banksia.interfaces.cli.commands.operator import guide_optional_operator_setup
from banksia.interfaces.cli.commands.presentation import (
    emit_completion,
    emit_key_value_panel,
    emit_success,
    emit_warning,
    emit_wizard_header,
)
from banksia.interfaces.cli.commands.provider_setup import (
    clone_namespace,
    guide_provider_setup_with_result,
    persisted_default_provider,
    persisted_provider_kinds,
    provider_list_text,
)
from banksia.interfaces.cli.progress import CliProgress
from banksia.interfaces.cli.providers import (
    OperatorSelectionSnapshot,
    read_operator_selection,
)
from banksia.interfaces.cli.providers.contracts import ProviderCheckSnapshot
from banksia.interfaces.cli.support import coerce_path, command_env
from banksia.paths import default_data_dir, default_database_url
from banksia.providers import ProviderKind

_INIT_ACTIONS = click.Choice(
    ("keep", "reconfigure", "cancel"),
    case_sensitive=False,
)
_LOG_LEVELS = click.Choice(
    ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
    case_sensitive=False,
)
_LOOPBACK_HOSTS = click.Choice(
    ("127.0.0.1", "localhost", "::1"),
    case_sensitive=False,
)


@dataclass(frozen=True, slots=True)
class _LocalInitSelection:
    args: argparse.Namespace
    is_recommended_accepted: bool


def guide_local_initialization(args: argparse.Namespace) -> int:
    """Guide first-run local, Task-provider, and optional Operator setup."""

    config_path = coerce_path(args.config)
    should_confirm_reconfiguration = False
    emit_wizard_header(
        "initialization",
        "Create or verify the local controller configuration and database.",
    )

    if config_path.is_file() and not args.force:
        action = _prompt_existing_init_action(config_path)
        if action == "cancel":
            return _emit_cancelled()
        if action == "keep":
            asyncio.run(_verify_existing_local_state(args, config_path))
            return _finish_initialization(
                args,
                config_path=config_path,
                database_state="verified",
            )
        args = clone_namespace(args, force=True)
        should_confirm_reconfiguration = True
    elif config_path.is_file():
        emit_warning(
            "Existing local settings will be reconfigured while provider and "
            f"Operator settings are kept: {config_path}"
        )

    selection = _prompt_local_init_settings(args)
    if should_confirm_reconfiguration or not selection.is_recommended_accepted:
        prompt = (
            "Reconfigure local settings and keep provider and Operator settings?"
            if should_confirm_reconfiguration
            else "Initialize Banksia with these custom settings?"
        )
        if not click.confirm(prompt, default=not should_confirm_reconfiguration):
            return _emit_cancelled()

    result = asyncio.run(cmd_init(selection.args))
    if result != 0:
        return result
    return _finish_initialization(
        selection.args,
        config_path=config_path,
        database_state="ready",
    )


def _finish_initialization(
    args: argparse.Namespace,
    *,
    config_path: Path,
    database_state: str,
) -> int:
    retained_providers = persisted_provider_kinds(config_path)
    retained_operator = read_operator_selection(config_path).persisted.provider
    configured_providers = retained_providers
    provider_result = 0
    provider_checks: Mapping[ProviderKind, ProviderCheckSnapshot] = {}
    if not configured_providers:
        setup_result = guide_provider_setup_with_result(
            clone_namespace(args, provider=None),
            should_emit_summary=False,
        )
        provider_result = setup_result.exit_code
        provider_checks = setup_result.checks
    operator_result = guide_optional_operator_setup(
        clone_namespace(
            args,
            provider=None,
            model=None,
            effort=None,
        ),
        should_emit_summary=False,
        provider_checks=provider_checks,
    )
    configured_providers = persisted_provider_kinds(config_path)
    operator_selection = read_operator_selection(config_path)
    default_provider = persisted_default_provider(config_path)
    check_provider = default_provider or min(
        configured_providers,
        key=lambda item: item.value,
        default=None,
    )
    check_provider_name = check_provider.value if check_provider is not None else "codex"
    emit_completion(
        "Initialization complete",
        (
            ("Config", str(config_path)),
            ("Database", database_state),
            (
                "Task providers",
                _retained_provider_summary(
                    configured_providers,
                    retained_providers=retained_providers,
                ),
            ),
            (
                "Operator",
                _retained_operator_summary(
                    operator_selection,
                    retained_provider=retained_operator,
                ),
            ),
        ),
        next_action=(
            "banksia setup"
            if not configured_providers
            else (
                f"banksia providers check {check_provider_name}"
                if provider_result != 0 or operator_result != 0
                else "banksia serve"
            )
        ),
    )
    return 1 if provider_result != 0 or operator_result != 0 else 0


def _prompt_existing_init_action(config_path: Path) -> str:
    click.echo(f"Existing config found: {config_path}")
    click.echo("  keep    Keep and verify current config (recommended)")
    click.echo("  reconfigure Change local settings; keep providers and Operator")
    click.echo("  cancel  Leave everything unchanged")
    return str(click.prompt("Action", type=_INIT_ACTIONS, default="keep")).casefold()


def _retained_provider_summary(
    providers: set[ProviderKind],
    *,
    retained_providers: set[ProviderKind],
) -> str:
    if not providers:
        return "none"
    summary = provider_list_text(providers)
    return f"{summary} (kept)" if retained_providers else summary


def _retained_operator_summary(
    selection: OperatorSelectionSnapshot,
    *,
    retained_provider: OperatorProvider | None,
) -> str:
    provider = selection.effective.provider
    if provider is None:
        return "not configured"
    if selection.is_environment_override:
        return f"{provider.value} (environment override)"
    if retained_provider == provider:
        return f"{provider.value} (kept)"
    return provider.value


def _prompt_local_init_settings(
    args: argparse.Namespace,
) -> _LocalInitSelection:
    prepared = clone_namespace(args)
    data_dir = coerce_path(prepared.data_dir or default_data_dir())
    database_url = prepared.database_url or default_database_url(data_dir)
    workspace = click.prompt(
        "Default workspace",
        default=str(coerce_path(prepared.workspace or Path.cwd())),
        type=click.Path(
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            resolve_path=True,
            path_type=Path,
        ),
    )
    prepared.data_dir = str(data_dir)
    prepared.database_url = database_url
    prepared.workspace = str(workspace)
    _emit_local_init_summary(prepared)
    if click.confirm("Use these recommended local settings?", default=True):
        return _LocalInitSelection(
            args=prepared,
            is_recommended_accepted=True,
        )

    data_dir = click.prompt(
        "Data directory",
        default=str(data_dir),
        type=click.Path(
            path_type=Path,
            file_okay=False,
            resolve_path=True,
        ),
    )
    prepared.data_dir = str(data_dir)
    if args.database_url is None:
        prepared.database_url = click.prompt(
            "Database URL",
            default=default_database_url(data_dir),
        )
    prepared.host = click.prompt(
        "Loopback API host",
        default=prepared.host,
        type=_LOOPBACK_HOSTS,
    )
    prepared.port = click.prompt(
        "API port",
        default=prepared.port,
        type=click.IntRange(1, 65535),
    )
    prepared.log_level = click.prompt(
        "Log level",
        default=prepared.log_level or DEFAULT_LOG_LEVEL,
        type=_LOG_LEVELS,
    )
    _emit_local_init_summary(prepared)
    return _LocalInitSelection(
        args=prepared,
        is_recommended_accepted=False,
    )


def _emit_local_init_summary(args: argparse.Namespace) -> None:
    database_url = args.database_url or default_database_url(
        coerce_path(args.data_dir or default_data_dir())
    )
    emit_key_value_panel(
        "Local settings",
        (
            ("Config", str(coerce_path(args.config))),
            ("Data", str(coerce_path(args.data_dir or default_data_dir()))),
            ("Default workspace", str(coerce_path(args.workspace))),
            ("Database", redact_database_url(database_url)),
            (
                "API",
                f"http://{format_loopback_authority(args.host, args.port)}",
            ),
        ),
    )


async def _verify_existing_local_state(
    args: argparse.Namespace,
    config_path: Path,
) -> None:
    progress = CliProgress.from_args(args)
    with command_env(config_path=config_path):
        settings = load_settings()
        if not args.skip_db_upgrade:
            await ensure_database_ready(progress=progress)
    emit_success(f"Verified config at {config_path}")
    emit_success(f"Data directory ready at {settings.data_dir}")


def _emit_cancelled() -> int:
    emit_warning("Cancelled. No further changes were made.")
    return 0


__all__ = ["guide_local_initialization"]
