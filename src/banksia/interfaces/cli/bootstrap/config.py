from __future__ import annotations

import copy
import json
import tomllib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from banksia.platform.workspace_files import (
    PrivateMutationTimeoutError,
    acquire_private_mutation_lock,
    read_private_text,
    replace_private_text,
)

CONFIG_MUTATION_LOCK_TIMEOUT_SECONDS = 5.0
ConfigSections = dict[str, dict[str, Any]]
ConfigMutation = Callable[[ConfigSections], ConfigSections]


class ConfigMutationTimeoutError(TimeoutError):
    """Raised when another local configuration mutation owns the file lock."""


def build_initial_config_sections(
    *,
    data_dir: Path,
    database_url: str,
    host: str,
    port: int,
    log_level: str,
    workspace: Path | None = None,
) -> ConfigSections:
    """Build one fresh local-controller configuration candidate."""

    return {
        "paths": {
            "data_dir": data_dir,
            "workspace": workspace,
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
    """Validate and atomically replace one Banksia configuration revision."""

    with acquire_config_mutation_lock(config_path, timeout_seconds=timeout_seconds):
        current_sections = read_config_sections(config_path)
        candidate_sections = mutation(copy.deepcopy(current_sections))
        if candidate_sections != current_sections:
            rendered = config_sections_to_text(candidate_sections)
            write_config_text_atomically(config_path, rendered)
    return candidate_sections


def read_config_sections(config_path: Path) -> ConfigSections:
    text = read_private_config_text(config_path)
    if text is None:
        return {}

    parsed = tomllib.loads(text)
    sections: ConfigSections = {}
    for section_name, section_values in parsed.items():
        if not isinstance(section_values, dict):
            raise ValueError(f"config section '{section_name}' must be a TOML table")
        sections[section_name] = dict(section_values)
    return sections


def read_private_config_text(config_path: Path) -> str | None:
    """Read one real owner-only config file without following a final symlink."""

    return read_private_text(config_path)


def config_sections_to_text(payload: ConfigSections) -> str:
    section_order = (
        "paths",
        "database",
        "server",
        "logging",
        "codex",
        "claude",
        "openclaw",
        "operator",
        "runtime",
    )
    ordered_sections = [section for section in section_order if section in payload]
    ordered_sections.extend(section for section in payload if section not in ordered_sections)

    lines: list[str] = []
    for section in ordered_sections:
        values = payload[section]
        ordered_keys = list(values)
        if section == "operator":
            ordered_keys = [
                *(key for key in ("provider", "model", "effort") if key in values),
                *(key for key in values if key not in {"provider", "model", "effort"}),
            ]
        rendered_values = [
            (key, values[key])
            for key in ordered_keys
            if values[key] is not None and values[key] != ""
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
    try:
        with acquire_private_mutation_lock(
            lock_path,
            timeout_seconds=timeout_seconds,
        ):
            yield
    except PrivateMutationTimeoutError as exc:
        raise ConfigMutationTimeoutError(
            f"timed out waiting to update Banksia config: {config_path}"
        ) from exc


def write_config_text_atomically(config_path: Path, rendered: str) -> None:
    replace_private_text(config_path, rendered)


__all__ = [
    "CONFIG_MUTATION_LOCK_TIMEOUT_SECONDS",
    "ConfigMutationTimeoutError",
    "ConfigSections",
    "acquire_config_mutation_lock",
    "build_initial_config_sections",
    "config_sections_to_text",
    "persist_config_mutation",
    "read_config_sections",
    "read_private_config_text",
    "toml_value",
    "update_config_sections",
    "write_config_text_atomically",
]
