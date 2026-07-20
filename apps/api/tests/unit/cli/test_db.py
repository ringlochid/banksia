from __future__ import annotations

import argparse
import asyncio
import sqlite3
from pathlib import Path

import autoclaw.interfaces.cli as cli
import pytest
from autoclaw.persistence.session import dispose_db_engine

from .cli_test_support import assert_seeded_registry_is_bootstrapped, build_cli_init_args


@pytest.mark.asyncio
async def test_db_reset_recreates_sqlite_database(tmp_path: Path) -> None:
    config_path = tmp_path / "autoclaw-config.toml"
    data_dir = tmp_path / "autoclaw-data"
    database_path = data_dir / "autoclaw.persistence"
    sidecar_paths = tuple(
        Path(f"{database_path}{suffix}") for suffix in ("-wal", "-shm", "-journal")
    )
    external_sidecar_target = tmp_path / "external-sidecar-target"

    try:
        await cli.cmd_init(build_cli_init_args(config_path, data_dir))
        database_path.write_bytes(b"stale")
        for sidecar_path in sidecar_paths[:-1]:
            sidecar_path.write_bytes(b"stale-sidecar")
        external_sidecar_target.write_bytes(b"user-owned")
        sidecar_paths[-1].symlink_to(external_sidecar_target)

        result = await cli.cmd_db_reset(
            argparse.Namespace(config=str(config_path), revision="head", json=False)
        )
    finally:
        await dispose_db_engine()

    assert result == 0
    assert database_path.exists()
    assert all(
        not sidecar_path.exists() or sidecar_path.read_bytes() != b"stale-sidecar"
        for sidecar_path in sidecar_paths
    )
    assert not sidecar_paths[-1].is_symlink()
    assert external_sidecar_target.read_bytes() == b"user-owned"
    assert_seeded_registry_is_bootstrapped(database_path)


@pytest.mark.asyncio
async def test_db_upgrade_rejects_stale_sqlite_schema_with_reset_guidance(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "autoclaw-config.toml"
    data_dir = tmp_path / "autoclaw-data"
    database_path = data_dir / "autoclaw.persistence"
    init_args = build_cli_init_args(config_path, data_dir)
    init_args.skip_db_upgrade = True

    try:
        await cli.cmd_init(init_args)
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                "CREATE TABLE flows (task_id TEXT PRIMARY KEY, status TEXT NOT NULL)"
            )
            connection.commit()

        with pytest.raises(RuntimeError, match=r"Run `autoclaw db reset`"):
            await asyncio.to_thread(
                cli.cmd_db_upgrade,
                argparse.Namespace(config=str(config_path)),
            )
    finally:
        await dispose_db_engine()

    with sqlite3.connect(database_path) as connection:
        columns = {row[1] for row in connection.execute('PRAGMA table_info("flows")').fetchall()}
    assert columns == {"task_id", "status"}


@pytest.mark.asyncio
async def test_db_upgrade_bootstraps_empty_sqlite_database(tmp_path: Path) -> None:
    config_path = tmp_path / "autoclaw-config.toml"
    data_dir = tmp_path / "autoclaw-data"
    database_path = data_dir / "autoclaw.persistence"
    init_args = build_cli_init_args(config_path, data_dir)
    init_args.skip_db_upgrade = True

    try:
        init_result = await cli.cmd_init(init_args)
        upgrade_result = await asyncio.to_thread(
            cli.cmd_db_upgrade,
            argparse.Namespace(config=str(config_path), revision="head"),
        )
    finally:
        await dispose_db_engine()

    assert init_result == 0
    assert upgrade_result == 0
    assert_seeded_registry_is_bootstrapped(database_path)


@pytest.mark.asyncio
async def test_db_reset_rejects_symlinked_sqlite_database_without_touching_target(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "autoclaw-config.toml"
    data_dir = tmp_path / "autoclaw-data"
    database_path = data_dir / "autoclaw.persistence"
    real_database_path = data_dir / "real.persistence"

    try:
        await cli.cmd_init(build_cli_init_args(config_path, data_dir))
        await dispose_db_engine()
        database_path.replace(real_database_path)
        database_path.symlink_to(real_database_path)

        with pytest.raises(ValueError, match="symlinked SQLite database path"):
            await cli.cmd_db_reset(
                argparse.Namespace(config=str(config_path), revision="head", json=False)
            )
    finally:
        await dispose_db_engine()

    assert database_path.is_symlink()
    assert real_database_path.is_file()
    with sqlite3.connect(real_database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM workflow_definitions").fetchone()[0] > 0
