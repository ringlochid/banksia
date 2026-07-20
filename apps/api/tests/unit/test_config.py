from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import ValidationError
from pytest import MonkeyPatch


def _reload_config_module() -> ModuleType:
    from autoclaw import config as config_module

    return importlib.reload(config_module)


def test_get_settings_reads_default_platform_config(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_home = tmp_path / "config-home"
    data_home = tmp_path / "data-home"
    state_home = tmp_path / "state-home"
    cache_home = tmp_path / "cache-home"
    config_path = config_home / "autoclaw" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        """
[database]
url = "sqlite+aiosqlite:////tmp/from-config.db"
echo = true
postgres_schema = "autoclaw_test"

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
gateway_url = "wss://gateway.example.test/autoclaw"
gateway_profile = "tested-local"

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

    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
    monkeypatch.delenv("AUTOCLAW_CONFIG", raising=False)
    monkeypatch.delenv("AUTOCLAW_DATABASE_URL", raising=False)

    config_module = _reload_config_module()
    config_module.get_settings.cache_clear()
    settings = config_module.get_settings()

    assert settings.database_url == "sqlite+aiosqlite:////tmp/from-config.db"
    assert settings.postgres_schema == "autoclaw_test"
    assert settings.database_echo is True
    assert settings.console_origins == ["http://127.0.0.1:4173"]
    assert not hasattr(settings, "api_key")
    assert settings.config_path == config_path
    assert settings.data_dir == data_home / "autoclaw"
    assert settings.codex.enabled is True
    assert settings.codex.model == "gpt-5"
    assert settings.codex.effort == "high"
    assert settings.claude.enabled is False
    assert settings.openclaw.enabled is True
    assert settings.openclaw.gateway_url == "wss://gateway.example.test/autoclaw"
    assert settings.openclaw.gateway_profile == "tested-local"
    assert settings.runtime.default_provider == "openclaw"
    assert settings.runtime.dispatch_launch_retry_initial_backoff_seconds == 0.25
    assert settings.runtime.dispatch_launch_retry_max_backoff_seconds == 3.5
    assert settings.runtime.watchdog_inactivity_timeout_seconds == 1200
    assert settings.runtime.watchdog_same_attempt_replacement_limit == 3


def test_env_overrides_config_file(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "autoclaw-config.toml"
    config_path.write_text(
        """
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

    monkeypatch.setenv("AUTOCLAW_CONFIG", str(config_path))
    monkeypatch.setenv("AUTOCLAW_DATABASE_URL", "sqlite+aiosqlite:////tmp/from-env.db")
    monkeypatch.setenv("AUTOCLAW_POSTGRES_SCHEMA", "environment_schema")
    monkeypatch.setenv("AUTOCLAW_DATABASE_ECHO", "true")
    monkeypatch.setenv("AUTOCLAW_API_HOST", "::1")
    monkeypatch.setenv("AUTOCLAW_API_PORT", "9001")
    monkeypatch.setenv("AUTOCLAW_OPENCLAW__GATEWAY_URL", "wss://gateway.example.test")
    monkeypatch.setenv("AUTOCLAW_OPENCLAW__GATEWAY_PROFILE", "environment-profile")
    monkeypatch.setenv("AUTOCLAW_RUNTIME__WATCHDOG_INACTIVITY_TIMEOUT_SECONDS", "99")
    monkeypatch.setenv("AUTOCLAW_RUNTIME__WATCHDOG_SAME_ATTEMPT_REPLACEMENT_LIMIT", "4")
    monkeypatch.setenv(
        "AUTOCLAW_RUNTIME__DISPATCH_LAUNCH_RETRY_INITIAL_BACKOFF_SECONDS",
        "0.3",
    )
    monkeypatch.setenv(
        "AUTOCLAW_RUNTIME__DISPATCH_LAUNCH_RETRY_MAX_BACKOFF_SECONDS",
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
    assert settings.openclaw.gateway_url == "wss://gateway.example.test"
    assert settings.openclaw.gateway_profile == "environment-profile"
    assert settings.runtime.dispatch_launch_retry_initial_backoff_seconds == 0.3
    assert settings.runtime.dispatch_launch_retry_max_backoff_seconds == 4.5
    assert settings.runtime.watchdog_inactivity_timeout_seconds == 99
    assert settings.runtime.watchdog_same_attempt_replacement_limit == 4


def test_get_settings_does_not_require_a_global_operator_key(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "autoclaw-config.toml"
    config_path.write_text('[server]\nhost = "127.0.0.1"\n', encoding="utf-8")
    monkeypatch.setenv("AUTOCLAW_CONFIG", str(config_path))
    monkeypatch.setenv("AUTOCLAW_ENV", "development")
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
    config_path = tmp_path / "autoclaw-config.toml"
    config_path.write_text(
        f"""
[database]
postgres_schema = "{postgres_schema}"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTOCLAW_CONFIG", str(config_path))
    monkeypatch.delenv("AUTOCLAW_POSTGRES_SCHEMA", raising=False)
    config_module = _reload_config_module()
    config_module.get_settings.cache_clear()

    with pytest.raises(Exception, match="postgres_schema"):
        config_module.get_settings()


@pytest.mark.parametrize(
    "field_name",
    [
        "is_watchdog_enabled",
        "should_watchdog_auto_recover",
        "watchdog_auto_recover",
        "watchdog_bootstrap_first_progress_timeout_seconds",
        "watchdog_enabled",
        "watchdog_execution_stale_after_seconds",
        "watchdog_interval_seconds",
        "watchdog_max_auto_recoveries_per_tick",
        "watchdog_max_flows_per_tick",
        "watchdog_same_attempt_redispatch_limit",
        "watchdog_stale_after_seconds",
    ],
)
def test_removed_watchdog_keys_fail_fast(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    field_name: str,
) -> None:
    config_path = tmp_path / "autoclaw-config.toml"
    config_path.write_text(
        f"""
[runtime]
{field_name} = 123
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("AUTOCLAW_CONFIG", str(config_path))
    config_module = _reload_config_module()
    config_module.get_settings.cache_clear()

    with pytest.raises(ValidationError, match=field_name):
        config_module.get_settings()


@pytest.mark.parametrize(
    "field_name",
    [
        "dispatch_drain_timeout_seconds",
        "dispatch_launch_retry_max_attempts",
        "openclaw_event_poll_timeout_seconds",
        "provider_wait_timeout_slice_ms",
        "post_commit_reconcile_interval_seconds",
        "terminal_truth_commit_grace_seconds",
        "terminal_truth_commit_poll_interval_seconds",
        "watchdog_bootstrap_ack_timeout_seconds",
    ],
)
def test_removed_provider_runtime_keys_fail_fast(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    field_name: str,
) -> None:
    config_path = tmp_path / "autoclaw-config.toml"
    config_path.write_text(
        f"""
[runtime]
{field_name} = 1
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("AUTOCLAW_CONFIG", str(config_path))
    config_module = _reload_config_module()
    config_module.get_settings.cache_clear()

    with pytest.raises(ValidationError, match=field_name):
        config_module.get_settings()


@pytest.mark.parametrize("section_name", ["codex", "claude", "openclaw", "runtime"])
def test_structured_config_sections_reject_non_table_values(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    section_name: str,
) -> None:
    config_path = tmp_path / "autoclaw-config.toml"
    config_path.write_text(
        f"""
{section_name} = "not-a-table"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("AUTOCLAW_CONFIG", str(config_path))
    config_module = _reload_config_module()
    config_module.get_settings.cache_clear()

    with pytest.raises(ValidationError, match=section_name):
        config_module.get_settings()


def test_runtime_deadline_defaults_match_target_contract() -> None:
    config_module = _reload_config_module()

    settings = config_module.RuntimeSettings()

    assert settings.watchdog_inactivity_timeout_seconds == 900
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
    config_path = tmp_path / "autoclaw-config.toml"
    config_path.write_text(
        f"""
[runtime]
{field_name} = {value}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("AUTOCLAW_CONFIG", str(config_path))
    config_module = _reload_config_module()
    config_module.get_settings.cache_clear()

    with pytest.raises(ValidationError, match=field_name):
        config_module.get_settings()
