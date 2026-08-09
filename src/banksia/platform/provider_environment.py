from __future__ import annotations

import os
import re
import shlex
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from banksia.platform.workspace_files import (
    acquire_private_mutation_lock,
    read_private_text,
    replace_private_text,
)

ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"
PROVIDER_SECRET_MUTATION_LOCK_TIMEOUT_SECONDS = 5.0
PROVIDER_SECRET_ENVIRONMENT_KEYS = frozenset(
    {
        ANTHROPIC_API_KEY,
    }
)
_RETIRED_PROVIDER_SECRET_ENVIRONMENT_KEYS = frozenset(
    {"OPENCLAW_GATEWAY_PASSWORD", "OPENCLAW_GATEWAY_TOKEN"}
)
PROVIDER_NATIVE_HOME_ENVIRONMENT_KEYS = frozenset(
    {
        "CLAUDE_CONFIG_DIR",
        "CODEX_HOME",
    }
)
_ASSIGNMENT_PATTERN = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


class ProviderEnvironmentError(ValueError):
    """Report an invalid private provider environment without exposing values."""


def provider_environment_file_path(config_path: Path) -> Path:
    """Return the private environment file shared by CLI and user service."""

    return config_path.parent / "banksia.env"


@contextmanager
def provider_service_identity_environment() -> Iterator[None]:
    """Use the provider-native homes owned by the Banksia service account."""

    previous = {key: os.environ.get(key) for key in PROVIDER_NATIVE_HOME_ENVIRONMENT_KEYS}
    try:
        for key in PROVIDER_NATIVE_HOME_ENVIRONMENT_KEYS:
            os.environ.pop(key, None)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def provider_secret_environment(path: Path) -> Iterator[None]:
    """Fill missing provider-native variables from the private service environment."""

    from_file = read_provider_secret_environment(path)
    overrides = {key: value for key, value in from_file.items() if not os.environ.get(key)}
    previous = {key: os.environ.get(key) for key in overrides}
    try:
        os.environ.update(overrides)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def provider_service_environment(path: Path) -> Iterator[None]:
    """Mirror the managed service's provider-secret environment for a bounded check."""

    from_file = read_provider_secret_environment(path)
    previous = {key: os.environ.get(key) for key in PROVIDER_SECRET_ENVIRONMENT_KEYS}
    try:
        for key in PROVIDER_SECRET_ENVIRONMENT_KEYS:
            value = from_file.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def read_provider_secret_environment(path: Path) -> dict[str, str]:
    """Read only supported provider secret assignments from one environment file."""

    text = _read_private_environment_text(path)
    if text is None:
        return {}
    return _parse_provider_secret_environment(text)


def persist_provider_secret(
    path: Path,
    *,
    key: str,
    value: str,
    remove: frozenset[str] = frozenset(),
) -> None:
    """Atomically store one provider secret and remove mutually exclusive sources."""

    if key not in PROVIDER_SECRET_ENVIRONMENT_KEYS:
        raise ValueError(f"unsupported provider secret environment key: {key}")
    normalized = _validate_secret_value(value, key=key)
    with _acquire_provider_environment_mutation_lock(path):
        retained = _retained_environment_lines(path, remove=remove | {key})
        retained.append(f"{key}={_quote_environment_value(normalized)}")
        _write_private_environment(path, retained)


def remove_provider_secrets(path: Path, *, keys: frozenset[str]) -> None:
    """Remove supported provider secrets while preserving comments and other provider secrets."""

    unsupported = keys - PROVIDER_SECRET_ENVIRONMENT_KEYS
    if unsupported:
        raise ValueError(f"unsupported provider secret environment key: {sorted(unsupported)[0]}")
    with _acquire_provider_environment_mutation_lock(path):
        if _read_private_environment_text(path) is None:
            return
        _write_private_environment(path, _retained_environment_lines(path, remove=keys))


def provider_subprocess_environment_overrides(
    *,
    allowed_keys: frozenset[str] = frozenset(),
) -> dict[str, str]:
    """Blank Banksia-managed credentials that do not belong to one provider child."""

    unsupported = allowed_keys - PROVIDER_SECRET_ENVIRONMENT_KEYS
    if unsupported:
        raise ValueError(f"unsupported provider secret environment key: {sorted(unsupported)[0]}")
    return {
        key: ""
        for key in PROVIDER_SECRET_ENVIRONMENT_KEYS
        if key not in allowed_keys and key in os.environ
    }


def provider_subprocess_environment(
    *,
    allowed_keys: frozenset[str] = frozenset(),
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Copy a process environment without credentials owned by other providers."""

    unsupported = allowed_keys - PROVIDER_SECRET_ENVIRONMENT_KEYS
    if unsupported:
        raise ValueError(f"unsupported provider secret environment key: {sorted(unsupported)[0]}")
    child_environment = dict(os.environ if environment is None else environment)
    for key in PROVIDER_SECRET_ENVIRONMENT_KEYS - allowed_keys:
        child_environment.pop(key, None)
    return child_environment


def ensure_private_environment_file(path: Path, *, initial_text: str) -> None:
    """Create a missing service environment and enforce owner-only permissions."""

    with _acquire_provider_environment_mutation_lock(path):
        if _read_private_environment_text(path) is not None:
            return
        lines = initial_text.rstrip("\n").splitlines()
        _write_private_environment(path, lines)


def _parse_provider_secret_environment(text: str) -> dict[str, str]:
    secrets: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ASSIGNMENT_PATTERN.fullmatch(stripped)
        if match is None:
            raise ProviderEnvironmentError(
                "private provider environment contains an invalid assignment"
            )
        if match.group(1) in _RETIRED_PROVIDER_SECRET_ENVIRONMENT_KEYS:
            continue
        if match.group(1) not in PROVIDER_SECRET_ENVIRONMENT_KEYS:
            raise ProviderEnvironmentError(
                f"private provider environment does not support {match.group(1)}"
            )
        key = match.group(1)
        try:
            parsed = shlex.split(stripped, comments=False, posix=True)
        except ValueError as exc:
            raise ProviderEnvironmentError(
                f"private provider environment contains an invalid {key} assignment"
            ) from exc
        if len(parsed) != 1 or "=" not in parsed[0]:
            raise ProviderEnvironmentError(
                f"private provider environment contains an invalid {key} assignment"
            )
        _, value = parsed[0].split("=", 1)
        if not value:
            raise ProviderEnvironmentError(
                f"private provider environment contains an empty {key} assignment"
            )
        secrets[key] = value
    return secrets


def _retained_environment_lines(path: Path, *, remove: frozenset[str]) -> list[str]:
    text = _read_private_environment_text(path)
    if text is None:
        return []
    _parse_provider_secret_environment(text)
    retained: list[str] = []
    for line in text.splitlines():
        match = _ASSIGNMENT_PATTERN.fullmatch(line.strip())
        if match is not None and match.group(1) in remove:
            continue
        retained.append(line)
    while retained and not retained[-1].strip():
        retained.pop()
    if retained:
        retained.append("")
    return retained


def _validate_secret_value(value: str, *, key: str) -> str:
    if not value or value.strip() != value:
        raise ProviderEnvironmentError(f"{key} must be non-empty and trimmed")
    if any(character in value for character in ("\x00", "\n", "\r")):
        raise ProviderEnvironmentError(f"{key} must fit on one line")
    return value


def _quote_environment_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    escaped = escaped.replace('"', '\\"')
    return f'"{escaped}"'


def _write_private_environment(path: Path, lines: list[str]) -> None:
    rendered = "\n".join(lines).rstrip("\n") + "\n"
    replace_private_text(path, rendered)


def _read_private_environment_text(path: Path) -> str | None:
    return read_private_text(path)


def _provider_environment_mutation_lock_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.lock")


@contextmanager
def _acquire_provider_environment_mutation_lock(path: Path) -> Iterator[None]:
    with acquire_private_mutation_lock(
        _provider_environment_mutation_lock_path(path),
        timeout_seconds=PROVIDER_SECRET_MUTATION_LOCK_TIMEOUT_SECONDS,
    ):
        yield


__all__ = [
    "ANTHROPIC_API_KEY",
    "PROVIDER_NATIVE_HOME_ENVIRONMENT_KEYS",
    "PROVIDER_SECRET_ENVIRONMENT_KEYS",
    "ProviderEnvironmentError",
    "ensure_private_environment_file",
    "persist_provider_secret",
    "provider_environment_file_path",
    "provider_secret_environment",
    "provider_service_environment",
    "provider_service_identity_environment",
    "provider_subprocess_environment",
    "provider_subprocess_environment_overrides",
    "read_provider_secret_environment",
    "remove_provider_secrets",
]
