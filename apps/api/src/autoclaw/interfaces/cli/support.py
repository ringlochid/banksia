from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any

from autoclaw.config import CONFIG_ENV_VAR, get_settings
from autoclaw.platform.provider_environment import (
    provider_environment_file_path,
    provider_secret_environment,
    provider_service_environment,
    provider_service_identity_environment,
)


def coerce_path(value: str | os.PathLike[str] | Path) -> Path:
    return Path(value).expanduser().resolve()


@contextmanager
def service_provider_check_env(*, config_path: Path) -> Iterator[None]:
    """Run a provider check with the exact secrets available to the user service."""

    with command_env(config_path=config_path):
        with provider_service_identity_environment():
            with provider_service_environment(provider_environment_file_path(config_path)):
                yield


@contextmanager
def service_provider_identity_env() -> Iterator[None]:
    """Use the provider-native homes owned by the managed user service."""

    with provider_service_identity_environment():
        yield


@contextmanager
def command_env(
    *,
    config_path: Path,
    data_dir: Path | None = None,
    database_url: str | None = None,
    api_host: str | None = None,
    api_port: int | None = None,
    log_level: str | None = None,
    env: str | None = None,
    should_load_provider_secrets: bool = False,
) -> Iterator[None]:
    overrides = {
        CONFIG_ENV_VAR: str(config_path),
        "AUTOCLAW_DATA_DIR": str(data_dir) if data_dir is not None else None,
        "AUTOCLAW_DATABASE_URL": database_url,
        "AUTOCLAW_API_HOST": api_host,
        "AUTOCLAW_API_PORT": str(api_port) if api_port is not None else None,
        "AUTOCLAW_LOG_LEVEL": log_level,
        "AUTOCLAW_ENV": env,
    }
    with temporary_env(overrides):
        provider_identity = (
            provider_service_identity_environment()
            if should_load_provider_secrets
            else nullcontext()
        )
        provider_environment = (
            provider_secret_environment(provider_environment_file_path(config_path))
            if should_load_provider_secrets
            else nullcontext()
        )
        with provider_identity:
            with provider_environment:
                yield


def print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


@contextmanager
def temporary_env(overrides: dict[str, str | None]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            if value is None:
                if key == "AUTOCLAW_ENV":
                    continue
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


__all__ = [
    "coerce_path",
    "command_env",
    "print_json",
    "service_provider_check_env",
    "service_provider_identity_env",
    "temporary_env",
]
