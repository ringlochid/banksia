from __future__ import annotations

import copy
import json
import os
import stat
import tempfile
import time
import tomllib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

CONFIG_MUTATION_LOCK_TIMEOUT_SECONDS = 5.0
ConfigSections = dict[str, dict[str, Any]]
ConfigMutation = Callable[[ConfigSections], ConfigSections]


class ConfigMutationTimeoutError(TimeoutError):
    """Raised when another local configuration mutation owns the file lock."""


def settings_to_config_text(
    *,
    data_dir: Path,
    database_url: str,
    host: str,
    port: int,
    log_level: str,
) -> str:
    payload: ConfigSections = {
        "paths": {
            "data_dir": data_dir,
        },
        "database": {
            "url": database_url,
            "echo": False,
        },
        "server": {
            "host": host,
            "port": port,
            "console_origins": [
                "http://127.0.0.1:5173",
                "http://localhost:5173",
                "http://127.0.0.1:4173",
                "http://localhost:4173",
            ],
        },
        "logging": {
            "level": log_level,
        },
    }
    return config_sections_to_text(payload)


def update_config_sections(
    config_path: Path,
    *,
    section_updates: dict[str, dict[str, Any]],
) -> None:
    def apply_section_updates(payload: ConfigSections) -> ConfigSections:
        for section, values in section_updates.items():
            next_values = dict(payload.get(section, {}))
            for key, value in values.items():
                if value is None or value == "":
                    next_values.pop(key, None)
                else:
                    next_values[key] = value
            if next_values:
                payload[section] = next_values
            else:
                payload.pop(section, None)
        return payload

    persist_config_mutation(config_path, apply_section_updates)


def persist_config_mutation(
    config_path: Path,
    mutation: ConfigMutation,
    *,
    timeout_seconds: float = CONFIG_MUTATION_LOCK_TIMEOUT_SECONDS,
) -> ConfigSections:
    """Validate and atomically replace one AutoClaw configuration revision."""

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with acquire_config_mutation_lock(config_path, timeout_seconds=timeout_seconds):
        current_sections = read_config_sections(config_path)
        candidate_sections = mutation(copy.deepcopy(current_sections))
        rendered = config_sections_to_text(candidate_sections)
        write_config_text_atomically(config_path, rendered)
    return candidate_sections


def read_config_sections(config_path: Path) -> ConfigSections:
    if not config_path.is_file():
        return {}

    parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
    sections: ConfigSections = {}
    for section_name, section_values in parsed.items():
        if not isinstance(section_values, dict):
            raise ValueError(f"config section '{section_name}' must be a TOML table")
        sections[section_name] = dict(section_values)
    return sections


def config_sections_to_text(payload: ConfigSections) -> str:
    section_order = (
        "paths",
        "database",
        "server",
        "logging",
        "codex",
        "claude",
        "openclaw",
        "runtime",
    )
    ordered_sections = [section for section in section_order if section in payload]
    ordered_sections.extend(section for section in payload if section not in ordered_sections)

    lines: list[str] = []
    for section in ordered_sections:
        values = payload[section]
        rendered_values = [
            (key, value) for key, value in values.items() if value is not None and value != ""
        ]
        if not rendered_values:
            continue
        lines.append(f"[{section}]")
        for key, value in rendered_values:
            lines.append(f"{key} = {toml_value(value)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, Path):
        return json.dumps(str(value))
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    return json.dumps(str(value))


@contextmanager
def acquire_config_mutation_lock(
    config_path: Path,
    *,
    timeout_seconds: float,
) -> Iterator[None]:
    lock_path = config_path.with_name(f"{config_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            try:
                acquire_platform_file_lock(lock_descriptor)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise ConfigMutationTimeoutError(
                        f"timed out waiting to update AutoClaw config: {config_path}"
                    ) from exc
                time.sleep(0.05)
        yield
    finally:
        release_platform_file_lock(lock_descriptor)
        os.close(lock_descriptor)


def acquire_platform_file_lock(lock_descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(lock_descriptor, 0, os.SEEK_SET)
        if os.fstat(lock_descriptor).st_size == 0:
            os.write(lock_descriptor, b"0")
        os.lseek(lock_descriptor, 0, os.SEEK_SET)
        try:
            msvcrt_api: Any = msvcrt
            msvcrt_api.locking(lock_descriptor, msvcrt_api.LK_NBLCK, 1)
        except OSError as exc:
            raise BlockingIOError from exc
        return

    import fcntl

    fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def release_platform_file_lock(lock_descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        try:
            os.lseek(lock_descriptor, 0, os.SEEK_SET)
            msvcrt_api: Any = msvcrt
            msvcrt_api.locking(lock_descriptor, msvcrt_api.LK_UNLCK, 1)
        except OSError:
            return
        return

    import fcntl

    fcntl.flock(lock_descriptor, fcntl.LOCK_UN)


def write_config_text_atomically(config_path: Path, rendered: str) -> None:
    previous_mode = stat.S_IMODE(config_path.stat().st_mode) if config_path.exists() else 0o600
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{config_path.name}.",
        suffix=".tmp",
        dir=config_path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(file_descriptor, previous_mode)
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, config_path)
        sync_parent_directory(config_path.parent)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def sync_parent_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    directory_descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


__all__ = [
    "CONFIG_MUTATION_LOCK_TIMEOUT_SECONDS",
    "ConfigMutationTimeoutError",
    "ConfigSections",
    "acquire_config_mutation_lock",
    "config_sections_to_text",
    "persist_config_mutation",
    "read_config_sections",
    "settings_to_config_text",
    "toml_value",
    "update_config_sections",
    "write_config_text_atomically",
]
