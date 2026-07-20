from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from autoclaw.config import load_settings
from autoclaw.interfaces.cli.support import coerce_path, command_env, print_json
from autoclaw.interfaces.cli.terminal.theme import accent, rich_enabled

REDACTED_VALUE = "__AUTOCLAW_REDACTED__"


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
        "openclaw": settings.openclaw.model_dump(mode="json"),
        "runtime": settings.runtime.model_dump(mode="json"),
    }
    return _redact_config_payload(payload)


def redact_database_url(value: str) -> str:
    """Render a database URL without its password or unsafe malformed userinfo."""
    try:
        return make_url(value).render_as_string(hide_password=True)
    except (ArgumentError, ValueError):
        return REDACTED_VALUE if "@" in value else value


def _redact_config_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(payload)
    openclaw = redacted.get("openclaw")
    if isinstance(openclaw, dict):
        openclaw = dict(openclaw)
        gateway_url = openclaw.get("gateway_url")
        if isinstance(gateway_url, str) and _url_contains_userinfo(gateway_url):
            openclaw["gateway_url"] = REDACTED_VALUE
        redacted["openclaw"] = openclaw
    return redacted


def _url_contains_userinfo(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "@" in value
    return parsed.username is not None or parsed.password is not None


__all__ = [
    "build_settings_payload",
    "cmd_config_path",
    "cmd_config_show",
    "redact_database_url",
]
