from __future__ import annotations

from pathlib import Path

import click

from banksia.config import load_settings, normalize_controller_workspace
from banksia.interfaces.cli.bootstrap.config import update_config_sections
from banksia.interfaces.cli.commands.presentation import (
    emit_completion,
    emit_warning,
)
from banksia.interfaces.cli.support import command_env


def guide_default_workspace(config_path: Path) -> int:
    """Prompt for and persist the default HTTP, Console, and Operator workspace."""

    with command_env(config_path=config_path):
        settings = load_settings()
    current_workspace = settings.controller_workspace or Path.cwd()
    workspace = click.prompt(
        "Default workspace",
        default=str(current_workspace),
        type=click.Path(
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            resolve_path=True,
            path_type=Path,
        ),
    )
    normalized_workspace = normalize_controller_workspace(workspace)
    update_config_sections(
        config_path,
        section_updates={"paths": {"workspace": normalized_workspace}},
    )

    with command_env(config_path=config_path):
        effective_workspace = load_settings().controller_workspace
    emit_completion(
        "Default workspace updated",
        (
            ("Saved workspace", str(normalized_workspace)),
            (
                "Effective workspace",
                str(effective_workspace) if effective_workspace is not None else "none",
            ),
        ),
        next_action="oms setup",
    )
    if effective_workspace != normalized_workspace:
        emit_warning("OMS_CONTROLLER_WORKSPACE overrides the saved default workspace.")
    return 0


def read_default_workspace(config_path: Path) -> Path | None:
    """Read the effective controller workspace without mutating configuration."""

    with command_env(config_path=config_path):
        return load_settings().controller_workspace


__all__ = [
    "guide_default_workspace",
    "read_default_workspace",
]
