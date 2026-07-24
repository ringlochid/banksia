from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

import click
import uvicorn

from banksia.config import (
    CONTROLLER_WORKSPACE_ENV_VAR,
    load_settings,
    normalize_controller_workspace,
)
from banksia.interfaces.cli.bootstrap.config import (
    ConfigSections,
    build_initial_config_sections,
    persist_config_mutation,
    update_config_sections,
)
from banksia.interfaces.cli.bootstrap.database import (
    ensure_database_ready,
    reset_database,
    sqlite_database_path,
)
from banksia.interfaces.cli.progress import CliProgress
from banksia.interfaces.cli.support import coerce_path, command_env, print_json
from banksia.paths import default_data_dir, default_database_url, ensure_runtime_dirs


async def cmd_init(args: argparse.Namespace) -> int:
    progress = CliProgress.from_args(args)
    config_path = coerce_path(args.config)
    data_dir = coerce_path(args.data_dir or default_data_dir())
    database_url = args.database_url or default_database_url(data_dir)
    _preflight_controller_workspace_environment()
    if config_path.exists() and not args.force:
        raise FileExistsError(
            f"Refusing to overwrite existing config without --force: {config_path}"
        )
    explicit_workspace = _normalize_explicit_init_workspace(args)

    progress.step("config", f"Writing config to {config_path}")
    ensure_runtime_dirs(config_dir=config_path.parent, data_dir=data_dir)
    persisted_sections = persist_config_mutation(
        config_path,
        lambda current_sections: _build_initial_config_candidate(
            current_sections,
            config_path=config_path,
            should_force=args.force,
            data_dir=data_dir,
            database_url=database_url,
            host=args.host,
            port=args.port,
            log_level=args.log_level,
            explicit_workspace=explicit_workspace,
        ),
    )
    workspace = persisted_sections["paths"].get("workspace")

    with command_env(
        config_path=config_path,
        data_dir=data_dir,
        database_url=database_url,
        api_host=args.host,
        api_port=args.port,
        log_level=args.log_level,
    ):
        if not args.skip_db_upgrade:
            await ensure_database_ready(progress=progress)

    payload = {
        "ok": True,
        "config_path": str(config_path),
        "data_dir": str(data_dir),
        "database_url": database_url,
        "workspace": str(workspace) if workspace is not None else None,
    }
    if args.json:
        print_json(payload)
    else:
        progress.done("config", "Local config initialized")
        print(f"Initialized config at {config_path}")
    return 0


def cmd_db_upgrade(args: argparse.Namespace) -> int:
    progress = CliProgress.from_args(args)
    config_path = coerce_path(args.config)
    with command_env(config_path=config_path):
        settings = load_settings()
        progress.step("database", "Creating or verifying the exact database schema")
        asyncio.run(
            ensure_database_ready(
                progress=progress,
            )
        )
    payload = {
        "ok": True,
        "database_url": settings.database_url,
    }
    if getattr(args, "json", False):
        print_json(payload)
    else:
        progress.done("database", "Database schema is current")
    return 0


async def cmd_db_reset(args: argparse.Namespace) -> int:
    progress = CliProgress.from_args(args)
    config_path = coerce_path(args.config)
    with command_env(config_path=config_path):
        settings = load_settings()
        progress.step("database", "Destructively resetting the database")
        reset_result = await reset_database(
            data_boundary=settings.data_dir,
            progress=progress,
        )

    payload = {
        "ok": True,
        "database_url": settings.database_url,
        "database_backend": reset_result.database_backend,
        "deleted_task_root_count": reset_result.deleted_task_root_count,
    }
    if args.json:
        print_json(payload)
    else:
        progress.done("database", "Database reset complete")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    config_path = coerce_path(args.config)
    with command_env(config_path=config_path, should_load_provider_secrets=True):
        settings = load_settings()
        uvicorn.run(
            "banksia.main:app",
            host=settings.api_host,
            port=settings.api_port,
            log_level=settings.log_level.lower(),
            reload=False,
        )
    return 0


def _preflight_controller_workspace_environment() -> None:
    raw_workspace = os.environ.get(CONTROLLER_WORKSPACE_ENV_VAR)
    if raw_workspace is None:
        return
    try:
        normalize_controller_workspace(raw_workspace)
    except ValueError as exc:
        raise click.UsageError(f"Invalid {CONTROLLER_WORKSPACE_ENV_VAR}: {exc}") from exc


def _normalize_explicit_init_workspace(
    args: argparse.Namespace,
) -> Path | None:
    explicit_workspace = getattr(args, "workspace", None)
    if explicit_workspace is None:
        return None
    try:
        return normalize_controller_workspace(explicit_workspace)
    except ValueError as exc:
        raise click.UsageError(f"Invalid --workspace: {exc}") from exc


def _build_initial_config_candidate(
    current_sections: ConfigSections,
    *,
    config_path: Path,
    should_force: bool,
    data_dir: Path,
    database_url: str,
    host: str,
    port: int,
    log_level: str,
    explicit_workspace: Path | None,
) -> ConfigSections:
    if config_path.exists() and not should_force:
        raise FileExistsError(
            f"Refusing to overwrite existing config without --force: {config_path}"
        )
    workspace = explicit_workspace
    configured_paths = current_sections.get("paths", {})
    if (
        workspace is None
        and should_force
        and config_path.is_file()
        and "workspace" in configured_paths
    ):
        preserved_workspace = configured_paths["workspace"]
        try:
            workspace = normalize_controller_workspace(preserved_workspace)
        except ValueError as exc:
            raise click.UsageError(
                f"Cannot preserve invalid [paths].workspace from {config_path}: {exc}"
            ) from exc

    return build_initial_config_sections(
        data_dir=data_dir,
        database_url=database_url,
        host=host,
        port=port,
        log_level=log_level,
        workspace=workspace,
    )


__all__ = [
    "cmd_db_reset",
    "cmd_db_upgrade",
    "cmd_init",
    "cmd_serve",
    "ensure_database_ready",
    "reset_database",
    "sqlite_database_path",
    "update_config_sections",
]
