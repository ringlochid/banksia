from __future__ import annotations

import os
import stat
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from oh_my_subagents.interfaces.cli.providers.configuration import (
    ProviderConfigurationRequest,
    configure_provider,
    set_default_provider,
)
from oh_my_subagents.providers import ManagedExtensionMode, ProviderKind


def test_first_configuration_sets_default_and_later_configuration_preserves_it(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"

    first = configure_provider(
        config_path,
        ProviderConfigurationRequest(
            provider=ProviderKind.CODEX,
            model="gpt-5",
            extension_mode=ManagedExtensionMode.ISOLATED,
        ),
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
    assert payload["codex"] == {
        "enabled": True,
        "model": "gpt-5",
        "extension_mode": "isolated",
    }
    assert payload["claude"] == {"enabled": True, "effort": "high"}
    assert payload["runtime"]["default_provider"] == "codex"


def test_active_configuration_replaces_a_stale_openclaw_default_and_section(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[openclaw]\nenabled = true\n\n[runtime]\ndefault_provider = "openclaw"\n',
        encoding="utf-8",
    )
    configured = configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CLAUDE),
    )

    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert configured.default_provider == ProviderKind.CLAUDE
    assert configured.is_default_changed is True
    assert payload["runtime"]["default_provider"] == "claude"
    assert "openclaw" not in payload


def test_retired_provider_configuration_is_rejected_without_rewrite(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CODEX),
    )
    previous_bytes = config_path.read_bytes()

    with pytest.raises(ValueError, match="retired"):
        configure_provider(
            config_path,
            ProviderConfigurationRequest(provider=ProviderKind.OPENCLAW),
        )

    with pytest.raises(ValueError, match="retired"):
        set_default_provider(config_path, ProviderKind.OPENCLAW)

    assert config_path.read_bytes() == previous_bytes
    assert tomllib.loads(previous_bytes.decode())["runtime"]["default_provider"] == "codex"


def test_provider_mutation_preserves_independent_operator_configuration(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[operator]\neffort = "high"\nmodel = "gpt-operator"\nprovider = "codex"\n',
        encoding="utf-8",
    )

    configure_provider(
        config_path,
        ProviderConfigurationRequest(provider=ProviderKind.CODEX, model="gpt-task"),
    )

    rendered = config_path.read_text(encoding="utf-8")
    payload = tomllib.loads(rendered)
    assert payload["operator"] == {
        "provider": "codex",
        "model": "gpt-operator",
        "effort": "high",
    }
    assert rendered.index("[codex]") < rendered.index("[operator]") < rendered.index("[runtime]")
    assert rendered.index('provider = "codex"') < rendered.index('model = "gpt-operator"')
    assert rendered.index('model = "gpt-operator"') < rendered.index('effort = "high"')


def test_provider_mutation_rejects_invalid_operator_config_without_rewrite(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('[operator]\nmodel = "dangling"\n', encoding="utf-8")
    previous_bytes = config_path.read_bytes()

    with pytest.raises(ValueError, match="Operator provider"):
        configure_provider(
            config_path,
            ProviderConfigurationRequest(provider=ProviderKind.CLAUDE),
        )

    assert config_path.read_bytes() == previous_bytes


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


@pytest.mark.skipif(os.name != "posix", reason="POSIX private-config proof")
def test_config_mutation_protects_parent_and_rejects_a_final_symlink(
    tmp_path: Path,
) -> None:
    config_directory = tmp_path / "private"
    config_directory.mkdir(mode=0o777)
    target = config_directory / "outside.toml"
    target.write_text('[runtime]\ndefault_provider = "codex"\n', encoding="utf-8")
    config_path = config_directory / "config.toml"
    config_path.symlink_to(target)

    with pytest.raises(OSError):
        configure_provider(
            config_path,
            ProviderConfigurationRequest(provider=ProviderKind.CLAUDE),
        )

    assert stat.S_IMODE(config_directory.stat().st_mode) == 0o700
    assert target.read_text(encoding="utf-8") == ('[runtime]\ndefault_provider = "codex"\n')
