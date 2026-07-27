from __future__ import annotations

import argparse
import sys
from pathlib import Path

import click

from banksia.interfaces.cli.commands.operator import guide_operator_setup
from banksia.interfaces.cli.commands.presentation import (
    emit_key_value_panel,
    emit_wizard_header,
)
from banksia.interfaces.cli.commands.provider_setup import (
    clone_namespace,
    guide_provider_setup,
    load_config_settings,
    persisted_provider_kinds,
)
from banksia.interfaces.cli.commands.workspace_setup import (
    guide_default_workspace,
)
from banksia.interfaces.cli.providers import read_operator_selection
from banksia.interfaces.cli.support import coerce_path

_SETTINGS_CHOICES = click.Choice(
    ("Task providers", "Operator", "Default workspace", "Done"),
    case_sensitive=False,
)


def should_run_guided_flow(
    *,
    is_non_interactive: bool,
    is_json_output: bool,
) -> bool:
    """Return whether this invocation can safely prompt a human."""

    if is_non_interactive or is_json_output:
        return False
    return sys.stdin.isatty() and sys.stdout.isatty()


def guide_settings(args: argparse.Namespace) -> int:
    """Run the small rerunnable settings hub over focused configuration flows."""

    config_path = coerce_path(args.config)
    if not config_path.is_file():
        raise click.UsageError(
            f"Banksia is not initialized at {config_path}. Run 'banksia init' first."
        )

    result = 0
    while True:
        emit_wizard_header(
            "settings",
            "Configure Task providers, Operator, or the default workspace.",
        )
        _emit_settings_overview(config_path)
        _emit_settings_choices()
        selected = str(
            click.prompt(
                "Settings",
                type=_SETTINGS_CHOICES,
                default="Done",
            )
        ).casefold()
        if selected == "done":
            return result
        if selected == "task providers":
            next_result = guide_provider_setup(clone_namespace(args, provider=None))
        elif selected == "operator":
            next_result = guide_operator_setup(
                clone_namespace(
                    args,
                    provider=None,
                    model=None,
                    effort=None,
                )
            )
        else:
            next_result = guide_default_workspace(config_path)
        if next_result != 0:
            result = next_result


def _emit_settings_overview(config_path: Path) -> None:
    settings = load_config_settings(config_path)
    operator = read_operator_selection(config_path).effective
    providers = sorted(provider.value for provider in persisted_provider_kinds(config_path))
    emit_key_value_panel(
        "Current settings",
        (
            ("Task providers", ", ".join(providers) if providers else "none"),
            (
                "Default provider",
                (
                    settings.runtime.default_provider.value
                    if settings.runtime.default_provider is not None
                    else "none"
                ),
            ),
            (
                "Operator",
                operator.provider.value if operator.provider is not None else "not configured",
            ),
            (
                "Default workspace",
                (
                    str(settings.controller_workspace)
                    if settings.controller_workspace is not None
                    else "not configured"
                ),
            ),
        ),
    )


def _emit_settings_choices() -> None:
    click.echo("  Task providers    Configure routes and the Task default")
    click.echo("  Operator          Configure the separate Banksia Operator")
    click.echo("  Default workspace Change the default workspace")
    click.echo("  Done              Leave settings")


__all__ = [
    "guide_settings",
    "should_run_guided_flow",
]
