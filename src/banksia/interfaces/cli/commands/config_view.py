from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from banksia.config import load_settings
from banksia.interfaces.cli.support import coerce_path, command_env, print_json
from banksia.interfaces.cli.terminal.theme import accent, rich_enabled

REDACTED_VALUE = "__OMS_REDACTED__"


def cmd_config_path(args: argparse.Namespace) -> int:
    config_path = coerce_path(args.config)
    payload = {"ok": True, "config_path": str(config_path)}
    if args.json:
        print_json(payload)
    else:
        print(accent(str(config_path), is_rich=rich_enabled(args)))
    return 0


def cmd_config_show(args: argparse.Namespace) -> int:
    config_path = coerce_path(args.config)
    with command_env(config_path=config_path):
        settings = load_settings()
    payload = build_settings_payload(settings, config_path)
    print_json(payload)
    return 0


def build_settings_payload(settings: Any, config_path: Path) -> dict[str, Any]:
    payload = {
        "config_path": str(config_path),
        "paths": {
            "data_dir": str(settings.data_dir),
            "workspace": (
                str(settings.controller_workspace)
                if settings.controller_workspace is not None
                else None
            ),
        },
        "database": {
            "url": redact_database_url(settings.database_url),
            "postgres_schema": settings.postgres_schema,
            "echo": settings.database_echo,
        },
        "server": {
            "host": settings.api_host,
            "port": settings.api_port,
            "console_origins": settings.console_origins,
        },
        "logging": {
            "level": settings.log_level,
        },
        "codex": settings.codex.model_dump(mode="json"),
        "claude": settings.claude.model_dump(mode="json"),
        "operator": settings.operator.model_dump(mode="json"),
        "runtime": settings.runtime.model_dump(mode="json"),
    }
    return payload


def redact_database_url(value: str) -> str:
    """Render a database URL without its password or unsafe malformed userinfo."""
    try:
        return make_url(value).render_as_string(hide_password=True)
    except (ArgumentError, ValueError):
        return REDACTED_VALUE if "@" in value else value


__all__ = [
    "build_settings_payload",
    "cmd_config_path",
    "cmd_config_show",
    "redact_database_url",
]
