from __future__ import annotations

import tomllib
from pathlib import Path

import autoclaw.interfaces.cli as cli
import pytest
from autoclaw.config import DEFAULT_LOG_LEVEL
from autoclaw.definitions.seeds import get_packaged_seed_definitions_root
from autoclaw.persistence.session import dispose_db_engine

from .cli_test_support import assert_seeded_registry_is_bootstrapped, build_cli_init_args


@pytest.mark.asyncio
async def test_init_writes_canonical_config_and_db_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "autoclaw-config.toml"
    data_dir = tmp_path / "autoclaw-data"

    try:
        result = await cli.cmd_init(build_cli_init_args(config_path, data_dir))
    finally:
        await dispose_db_engine()

    assert result == 0
    assert config_path.exists()
    assert data_dir.joinpath("autoclaw.persistence").exists()

    config_text = config_path.read_text(encoding="utf-8")
    config_payload = tomllib.loads(config_text)
    assert f'level = "{DEFAULT_LOG_LEVEL}"' in config_text
    assert "security" not in config_payload
    assert "definitions_root" not in config_text
    assert "[app]" not in config_text
    assert config_payload["database"]["echo"] is False
    assert "codex" not in config_payload
    assert "claude" not in config_payload
    assert "openclaw" not in config_payload
    assert "runtime" not in config_payload
    assert_seeded_registry_is_bootstrapped(data_dir / "autoclaw.persistence")
    assert '"ok": true' in capsys.readouterr().out


@pytest.mark.asyncio
async def test_init_keeps_sql_echo_quiet_when_legacy_debug_env_is_set(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "autoclaw-config.toml"
    data_dir = tmp_path / "autoclaw-data"
    monkeypatch.setenv("AUTOCLAW_DEBUG", "true")

    try:
        result = await cli.cmd_init(build_cli_init_args(config_path, data_dir))
    finally:
        await dispose_db_engine()

    assert result == 0
    assert "sqlalchemy.engine.Engine" not in capsys.readouterr().out


def test_packaged_seed_definitions_are_available() -> None:
    definitions_root = get_packaged_seed_definitions_root()

    assert definitions_root.joinpath("roles").joinpath("planning_lead.yaml").is_file()
    assert definitions_root.joinpath("policies").joinpath("standard_worker.yaml").is_file()
    assert definitions_root.joinpath("workflows").joinpath("reviewed_change_release.yaml").is_file()
