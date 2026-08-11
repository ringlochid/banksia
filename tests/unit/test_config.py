from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import ValidationError
from pytest import MonkeyPatch

from banksia import paths
from banksia.config import CONTROLLER_WORKSPACE_ENV_VAR


def _reload_config_module() -> ModuleType:
    from banksia import config as config_module

    return importlib.reload(config_module)


def _configure_platform_directories(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path]:
    if os.name == "nt":
        platform_home = tmp_path / "platform-home"
        monkeypatch.setenv("LOCALAPPDATA", str(platform_home))
        monkeypatch.setenv("APPDATA", str(platform_home))
        return (platform_home,) * 4
    directories = (
        tmp_path / "config",
        tmp_path / "data",
        tmp_path / "state",
        tmp_path / "cache",
    )
    for environment_name, directory in zip(
        ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"),
        directories,
        strict=True,
    ):
        monkeypatch.setenv(environment_name, str(directory))
    return directories


def _toml_string(value: Path) -> str:
    return json.dumps(str(value))


def test_platform_paths_use_only_banksia_namespace(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_home, data_home, state_home, cache_home = _configure_platform_directories(
        monkeypatch,
        tmp_path,
    )

    assert paths.default_config_path() == config_home / "banksia" / "config.toml"
    assert paths.default_data_dir() == data_home / "banksia"
    assert paths.default_state_dir() == state_home / "banksia"
    expected_cache = cache_home / "banksia"
    if os.name == "nt":
        expected_cache /= "Cache"
    assert paths.default_cache_dir() == expected_cache
    assert paths.default_database_path() == data_home / "banksia" / "banksia.persistence"


def test_get_settings_reads_default_platform_config(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_home, data_home, _state_home, _cache_home = _configure_platform_directories(
        monkeypatch,
        tmp_path,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config_path = config_home / "banksia" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        f"""
[paths]
workspace = {_toml_string(workspace)}

[database]
url = "sqlite+aiosqlite:////tmp/from-config.db"
echo = true
postgres_schema = "banksia_test"

[server]
console_origins = ["http://127.0.0.1:4173"]

[codex]
enabled = true
model = "gpt-5"
effort = "high"

[claude]
enabled = false

[openclaw]
enabled = true
gateway_url = "wss://gateway.example.test/banksia"
gateway_profile = "tested-local"

[operator]
provider = "claude"
model = "claude-operator"

[runtime]
default_provider = "openclaw"
dispatch_launch_retry_initial_backoff_seconds = 0.25
dispatch_launch_retry_max_backoff_seconds = 3.5
watchdog_inactivity_timeout_seconds = 1200
watchdog_same_attempt_replacement_limit = 3
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("BANKSIA_CONFIG", raising=False)
    monkeypatch.delenv("BANKSIA_DATABASE_URL", raising=False)

    config_module = _reload_config_module()
    config_module.get_settings.cache_clear()
    settings = config_module.get_settings()

    assert settings.database_url == "sqlite+aiosqlite:////tmp/from-config.db"
    assert settings.postgres_schema == "banksia_test"
    assert settings.database_echo is True
    assert settings.console_origins == ["http://127.0.0.1:4173"]
    assert not hasattr(settings, "api_key")
    assert settings.config_path == config_path
    assert settings.data_dir == data_home / "banksia"
    assert settings.controller_workspace == workspace.resolve()
    assert settings.codex.enabled is True
    assert settings.codex.model == "gpt-5"
    assert settings.codex.effort == "high"
    assert settings.claude.enabled is False
    assert not hasattr(settings, "openclaw")
    assert settings.operator.provider == "claude"
    assert settings.operator.model == "claude-operator"
    assert settings.operator.effort is None
    assert settings.runtime.default_provider == "openclaw"
    assert settings.runtime.dispatch_launch_retry_initial_backoff_seconds == 0.25
    assert settings.runtime.dispatch_launch_retry_max_backoff_seconds == 3.5
    assert settings.runtime.watchdog_inactivity_timeout_seconds == 1200
    assert settings.runtime.watchdog_same_attempt_replacement_limit == 3


def test_settings_ignore_autoclaw_environment_and_leave_old_state_untouched(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_home, data_home, _state_home, _cache_home = _configure_platform_directories(
        monkeypatch,
        tmp_path,
    )
    old_config_path = config_home / "autoclaw" / "config.toml"
    old_config_path.parent.mkdir(parents=True)
    old_config_text = '[database]\nurl = "sqlite+aiosqlite:////tmp/from-autoclaw.db"\n'
    old_config_path.write_text(old_config_text, encoding="utf-8")

    monkeypatch.delenv("BANKSIA_CONFIG", raising=False)
    monkeypatch.delenv("BANKSIA_DATABASE_URL", raising=False)
    monkeypatch.setenv("AUTOCLAW_CONFIG", str(old_config_path))
    monkeypatch.setenv("AUTOCLAW_DATABASE_URL", "sqlite+aiosqlite:////tmp/from-old-env.db")

    config_module = _reload_config_module()
    config_module.get_settings.cache_clear()
    settings = config_module.get_settings()

    assert settings.config_path == config_home / "banksia" / "config.toml"
    assert settings.data_dir == data_home / "banksia"
    assert settings.database_url.endswith("/banksia/banksia.persistence")
    assert old_config_path.read_text(encoding="utf-8") == old_config_text


def test_env_overrides_config_file(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "banksia-config.toml"
    config_workspace = tmp_path / "config-workspace"
    environment_workspace = tmp_path / "environment-workspace"
    config_workspace.mkdir()
    environment_workspace.mkdir()
    config_path.write_text(
        f"""
[paths]
workspace = {_toml_string(config_workspace)}

[database]
url = "sqlite+aiosqlite:////tmp/from-config.db"
postgres_schema = "config_schema"

[server]
port = 18125

[openclaw]
enabled = true
gateway_url = "ws://127.0.0.1:18789"
gateway_profile = "config-profile"

[runtime]
watchdog_inactivity_timeout_seconds = 1200
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("BANKSIA_CONFIG", str(config_path))
    monkeypatch.setenv(CONTROLLER_WORKSPACE_ENV_VAR, str(environment_workspace))
    monkeypatch.setenv("BANKSIA_DATABASE_URL", "sqlite+aiosqlite:////tmp/from-env.db")
    monkeypatch.setenv("BANKSIA_POSTGRES_SCHEMA", "environment_schema")
    monkeypatch.setenv("BANKSIA_DATABASE_ECHO", "true")
    monkeypatch.setenv("BANKSIA_API_HOST", "::1")
    monkeypatch.setenv("BANKSIA_API_PORT", "9001")
    monkeypatch.setenv("BANKSIA_OPERATOR__PROVIDER", "codex")
    monkeypatch.setenv("BANKSIA_OPERATOR__MODEL", "gpt-operator")
    monkeypatch.setenv("BANKSIA_OPERATOR__EFFORT", "medium")
    monkeypatch.setenv("BANKSIA_RUNTIME__WATCHDOG_INACTIVITY_TIMEOUT_SECONDS", "99")
    monkeypatch.setenv("BANKSIA_RUNTIME__WATCHDOG_SAME_ATTEMPT_REPLACEMENT_LIMIT", "4")
    monkeypatch.setenv(
        "BANKSIA_RUNTIME__DISPATCH_LAUNCH_RETRY_INITIAL_BACKOFF_SECONDS",
        "0.3",
    )
    monkeypatch.setenv(
        "BANKSIA_RUNTIME__DISPATCH_LAUNCH_RETRY_MAX_BACKOFF_SECONDS",
        "4.5",
    )
    config_module = _reload_config_module()
    config_module.get_settings.cache_clear()
    settings = config_module.get_settings()

    assert settings.database_url == "sqlite+aiosqlite:////tmp/from-env.db"
    assert settings.postgres_schema == "environment_schema"
    assert settings.database_echo is True
    assert settings.api_host == "::1"
    assert settings.api_port == 9001
    assert settings.config_path == config_path
    assert settings.controller_workspace == environment_workspace.resolve()
    assert not hasattr(settings, "openclaw")
    assert settings.operator.provider == "codex"
    assert settings.operator.model == "gpt-operator"
    assert settings.operator.effort == "medium"
    assert settings.runtime.dispatch_launch_retry_initial_backoff_seconds == 0.3
    assert settings.runtime.dispatch_launch_retry_max_backoff_seconds == 4.5
    assert settings.runtime.watchdog_inactivity_timeout_seconds == 99
    assert settings.runtime.watchdog_same_attempt_replacement_limit == 4


def test_controller_workspace_validator_rejects_invalid_paths(
    tmp_path: Path,
) -> None:
    missing_path = tmp_path / "missing"
    file_path = tmp_path / "file"
    file_path.write_text("not a directory", encoding="utf-8")
    invalid_workspaces = (
        "",
        ".",
        "relative/workspace",
        "~banksia-user-that-does-not-exist/workspace",
        missing_path,
        file_path,
    )
    config_module = _reload_config_module()

    for raw_workspace in invalid_workspaces:
        with pytest.raises(
            ValueError,
            match="absolute path to an existing directory",
        ):
            config_module.normalize_controller_workspace(raw_workspace)
        with pytest.raises(
            ValidationError,
            match="absolute path to an existing directory",
        ):
            config_module.Settings.model_validate(
                {"controller_workspace": raw_workspace},
            )


def test_get_settings_does_not_require_a_global_operator_key(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "banksia-config.toml"
    config_path.write_text('[server]\nhost = "127.0.0.1"\n', encoding="utf-8")
    monkeypatch.setenv("BANKSIA_CONFIG", str(config_path))
    monkeypatch.setenv("BANKSIA_ENV", "development")
    config_module = _reload_config_module()
    config_module.get_settings.cache_clear()
    settings = config_module.get_settings()

    assert settings.api_host == "127.0.0.1"
    assert not hasattr(settings, "api_key")


@pytest.mark.parametrize(
    ("raw_host", "normalized_host"),
    [
        ("127.0.0.1", "127.0.0.1"),
        ("127.0.0.2", "127.0.0.2"),
        ("localhost", "localhost"),
        ("[::1]", "::1"),
    ],
)
def test_api_host_accepts_only_canonical_loopback_values(
    raw_host: str,
    normalized_host: str,
) -> None:
    config_module = _reload_config_module()

    settings = config_module.Settings(api_host=raw_host)

    assert settings.api_host == normalized_host


@pytest.mark.parametrize(
    "api_host",
    [
        "",
        "0.0.0.0",
        "::",
        "192.0.2.10",
        "api.example.test",
        "[::1",
        "::1]",
        "[::1]]",
        "[fe80::1%lo0]",
    ],
)
def test_api_host_rejects_wildcard_and_non_loopback_values(api_host: str) -> None:
    config_module = _reload_config_module()

    with pytest.raises(ValidationError, match="api_host"):
        config_module.Settings(api_host=api_host)


@pytest.mark.parametrize("api_port", [0, 65536])
def test_api_port_rejects_values_outside_the_listener_range(api_port: int) -> None:
    config_module = _reload_config_module()

    with pytest.raises(ValidationError, match="api_port"):
        config_module.Settings(api_port=api_port)


def test_console_origins_are_loopback_only_normalized_and_deduplicated() -> None:
    config_module = _reload_config_module()

    settings = config_module.Settings(
        console_origins=[
            "HTTP://LOCALHOST:5173/",
            "http://localhost:5173",
            "https://[::1]:4173",
        ]
    )

    assert settings.console_origins == [
        "http://localhost:5173",
        "https://[::1]:4173",
    ]


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "ftp://127.0.0.1:5173",
        "http://192.0.2.10:5173",
        "http://user@127.0.0.1:5173",
        "http://127.0.0.1:5173/path",
        "http://127.0.0.1:5173?query=yes",
        "http://localhost:*",
    ],
)
def test_console_origins_reject_nonexact_or_nonloopback_values(origin: str) -> None:
    config_module = _reload_config_module()

    with pytest.raises(ValidationError, match="console_origins"):
        config_module.Settings(console_origins=[origin])


@pytest.mark.parametrize(
    "postgres_schema",
    [
        "public",
        "information_schema",
        "pg_catalog",
        "HasUppercase",
        "contains-dash",
        "1starts_with_digit",
        "x" * 64,
    ],
)
def test_postgres_schema_rejects_public_system_or_unsafe_names(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    postgres_schema: str,
) -> None:
    config_path = tmp_path / "banksia-config.toml"
    config_path.write_text(
        f"""
[database]
postgres_schema = "{postgres_schema}"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BANKSIA_CONFIG", str(config_path))
    monkeypatch.delenv("BANKSIA_POSTGRES_SCHEMA", raising=False)
    config_module = _reload_config_module()
    config_module.get_settings.cache_clear()

    with pytest.raises(Exception, match="postgres_schema"):
        config_module.get_settings()


def test_removed_runtime_key_fails_fast(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    field_name = "watchdog_enabled"
    config_path = tmp_path / "banksia-config.toml"
    config_path.write_text(
        f"""
[runtime]
{field_name} = 123
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("BANKSIA_CONFIG", str(config_path))
    config_module = _reload_config_module()
    config_module.get_settings.cache_clear()

    with pytest.raises(ValidationError, match=field_name):
        config_module.get_settings()


@pytest.mark.parametrize("section_name", ["codex", "claude", "operator", "runtime"])
def test_structured_config_sections_reject_non_table_values(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    section_name: str,
) -> None:
    config_path = tmp_path / "banksia-config.toml"
    config_path.write_text(
        f"""
{section_name} = "not-a-table"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("BANKSIA_CONFIG", str(config_path))
    config_module = _reload_config_module()
    config_module.get_settings.cache_clear()

    with pytest.raises(ValidationError, match=section_name):
        config_module.get_settings()


@pytest.mark.parametrize(
    "operator",
    (
        {"provider": "openclaw"},
        {"provider": "claude", "model": " "},
        {"provider": "codex", "effort": ""},
        {"provider": "codex", "model": "x" * 256},
        {"model": "gpt-operator"},
        {"effort": "high"},
        {"provider": "claude", "unknown": True},
    ),
)
def test_operator_settings_reject_invalid_or_dangling_values(
    operator: dict[str, object],
) -> None:
    config_module = _reload_config_module()

    with pytest.raises(ValidationError):
        config_module.Settings.model_validate({"operator": operator})


def test_runtime_deadline_defaults_match_target_contract() -> None:
    config_module = _reload_config_module()

    settings = config_module.RuntimeSettings()

    assert settings.watchdog_inactivity_timeout_seconds == 2700
    assert settings.watchdog_same_attempt_replacement_limit == 2
    assert settings.dispatch_launch_retry_initial_backoff_seconds == 1.0
    assert settings.dispatch_launch_retry_max_backoff_seconds == 30.0


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("watchdog_inactivity_timeout_seconds", 0),
        ("watchdog_same_attempt_replacement_limit", -1),
    ],
)
def test_watchdog_settings_reject_invalid_values(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    field_name: str,
    value: int,
) -> None:
    config_path = tmp_path / "banksia-config.toml"
    config_path.write_text(
        f"""
[runtime]
{field_name} = {value}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("BANKSIA_CONFIG", str(config_path))
    config_module = _reload_config_module()
    config_module.get_settings.cache_clear()

    with pytest.raises(ValidationError, match=field_name):
        config_module.get_settings()
