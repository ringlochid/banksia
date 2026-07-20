from __future__ import annotations

import argparse
import asyncio

import uvicorn

from autoclaw.config import load_settings
from autoclaw.interfaces.cli.bootstrap.config import (
    settings_to_config_text,
    update_config_sections,
)
from autoclaw.interfaces.cli.bootstrap.database import (
    ensure_database_ready,
    reset_database,
    sqlite_database_path,
)
from autoclaw.interfaces.cli.progress import CliProgress
from autoclaw.interfaces.cli.support import coerce_path, command_env, print_json
from autoclaw.paths import default_data_dir, default_database_url, ensure_runtime_dirs


async def cmd_init(args: argparse.Namespace) -> int:
    progress = CliProgress.from_args(args)
    config_path = coerce_path(args.config)
    data_dir = coerce_path(args.data_dir or default_data_dir())
    database_url = args.database_url or default_database_url(data_dir)
    if config_path.exists() and not args.force:
        raise FileExistsError(
            f"Refusing to overwrite existing config without --force: {config_path}"
        )

    progress.step("config", f"Writing config to {config_path}")
    ensure_runtime_dirs(config_dir=config_path.parent, data_dir=data_dir)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        settings_to_config_text(
            data_dir=data_dir,
            database_url=database_url,
            host=args.host,
            port=args.port,
            log_level=args.log_level,
        ),
        encoding="utf-8",
    )

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
            "autoclaw.main:app",
            host=settings.api_host,
            port=settings.api_port,
            log_level=settings.log_level.lower(),
            reload=False,
        )
    return 0


__all__ = [
    "cmd_db_reset",
    "cmd_db_upgrade",
    "cmd_init",
    "cmd_serve",
    "ensure_database_ready",
    "reset_database",
    "settings_to_config_text",
    "sqlite_database_path",
    "update_config_sections",
]
