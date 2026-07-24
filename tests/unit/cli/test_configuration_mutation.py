from __future__ import annotations

import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from banksia.interfaces.cli.providers.configuration import (
    ProviderConfigurationRequest,
    configure_provider,
    set_default_provider,
)
from banksia.providers import ProviderKind


def test_first_configuration_sets_default_and_later_configuration_preserves_it(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"

    first = configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CODEX, model="gpt-5"),
    )
    second = configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CLAUDE, effort="high"),
    )

    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert first.default_provider == ProviderKind.CODEX
    assert first.is_default_changed is True
    assert first.model_dump(mode="json")["default_changed"] is True
    assert second.default_provider == ProviderKind.CODEX
    assert second.is_default_changed is False
    assert payload["codex"] == {"enabled": True, "model": "gpt-5"}
    assert payload["claude"] == {"enabled": True, "effort": "high"}
    assert payload["runtime"]["default_provider"] == "codex"


def test_openclaw_is_configurable_and_default_eligible(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CODEX),
    )
    configured = configure_provider(
        config_path,
        ProviderConfigurationRequest(
            provider=ProviderKind.OPENCLAW,
            cli_path="/opt/openclaw/bin/openclaw",
            gateway_url="ws://127.0.0.1:18789",
            gateway_profile="user-maintained",
        ),
    )

    changed = set_default_provider(config_path, ProviderKind.OPENCLAW)

    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert configured.product_status.value == "experimental"
    assert configured.default_provider == ProviderKind.CODEX
    assert changed.default_provider == ProviderKind.OPENCLAW
    assert changed.is_default_changed is True
    assert payload["runtime"]["default_provider"] == "openclaw"
    assert payload["openclaw"] == {
        "enabled": True,
        "cli_path": "/opt/openclaw/bin/openclaw",
        "gateway_url": "ws://127.0.0.1:18789",
        "gateway_profile": "user-maintained",
        "gateway_auth_mode": "token",
    }


def test_openclaw_configuration_records_the_discovered_cli_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    executable = tmp_path / "openclaw"
    monkeypatch.setattr(
        "banksia.interfaces.cli.providers.configuration.shutil.which",
        lambda _command: str(executable),
    )

    configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.OPENCLAW),
    )

    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert payload["openclaw"]["cli_path"] == str(executable)


def test_failed_configuration_preserves_previous_bytes_and_default(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CODEX),
    )
    previous_bytes = config_path.read_bytes()

    with pytest.raises(ValueError, match="gateway_url"):
        configure_provider(
            config_path,
            ProviderConfigurationRequest(
                provider=ProviderKind.OPENCLAW,
                gateway_url="ws://user:secret@127.0.0.1:18789",
            ),
        )

    assert config_path.read_bytes() == previous_bytes
    assert tomllib.loads(previous_bytes.decode())["runtime"]["default_provider"] == "codex"


def test_concurrent_first_configuration_has_one_stable_default(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    barrier_calls = (
        ProviderConfigurationRequest(provider=ProviderKind.CODEX),
        ProviderConfigurationRequest(provider=ProviderKind.CLAUDE),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(lambda request: configure_provider(config_path, request), barrier_calls)
        )

    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    defaults = {result.default_provider for result in results}
    assert len(defaults) == 1
    assert sum(result.is_default_changed for result in results) == 1
    assert payload["runtime"]["default_provider"] in {"codex", "claude"}
    assert payload["codex"]["enabled"] is True
    assert payload["claude"]["enabled"] is True
