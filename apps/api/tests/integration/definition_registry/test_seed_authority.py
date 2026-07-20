from __future__ import annotations

import argparse
from contextlib import nullcontext
from pathlib import Path

import autoclaw.definitions.registry.seeds as registry_seeds
import autoclaw.interfaces.cli as cli
import pytest
from autoclaw.persistence.session import dispose_db_engine


@pytest.mark.asyncio
async def test_init_fails_when_packaged_seed_definitions_are_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "autoclaw-config.toml"
    data_dir = tmp_path / "autoclaw-data"
    empty_seed_root = tmp_path / "missing-packaged-definitions"
    empty_seed_root.mkdir()

    monkeypatch.setattr(
        registry_seeds,
        "resolve_packaged_seed_definitions_root",
        lambda: nullcontext(empty_seed_root),
    )

    try:
        with pytest.raises(FileNotFoundError, match="missing seed definitions for 'roles'"):
            await cli.cmd_init(
                argparse.Namespace(
                    config=str(config_path),
                    data_dir=str(data_dir),
                    database_url=None,
                    host="127.0.0.1",
                    port=8123,
                    log_level="INFO",
                    force=True,
                    skip_db_upgrade=False,
                    json=False,
                )
            )
    finally:
        await dispose_db_engine()
