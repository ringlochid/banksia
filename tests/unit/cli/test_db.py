from __future__ import annotations

import argparse
import asyncio
import sqlite3
from pathlib import Path

import pytest

import banksia.interfaces.cli as cli
from banksia.persistence.forward_upgrade import DatabaseSchemaUpgradeUnavailableError
from banksia.persistence.session import dispose_db_engine
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.lineage_seed import seed_runtime_scope
from tests.helpers.sqlite_runtime import (
    create_runtime_schema_engine,
    rewrite_sqlite_table_preserving_rows,
)

from .cli_test_support import assert_seeded_registry_is_bootstrapped, build_cli_init_args


@pytest.mark.asyncio
async def test_db_reset_recreates_sqlite_database(tmp_path: Path) -> None:
    config_path = tmp_path / "banksia-config.toml"
    data_dir = tmp_path / "banksia-data"
    database_path = data_dir / "banksia.persistence"
    try:
        await cli.cmd_init(build_cli_init_args(config_path, data_dir))
        with sqlite3.connect(database_path) as connection:
            connection.execute("CREATE TABLE reset_backup_marker (value TEXT NOT NULL)")
            connection.execute("INSERT INTO reset_backup_marker VALUES ('preserved')")
            connection.commit()

        result = await cli.cmd_db_reset(
            argparse.Namespace(config=str(config_path), revision="head", json=False)
        )
    finally:
        await dispose_db_engine()

    assert result == 0
    assert database_path.exists()
    assert_seeded_registry_is_bootstrapped(database_path)
    backup_paths = tuple(data_dir.glob("banksia.persistence.before-reset-*.backup"))
    assert len(backup_paths) == 1
    with sqlite3.connect(backup_paths[0]) as connection:
        assert connection.execute("SELECT value FROM reset_backup_marker").fetchone() == (
            "preserved",
        )


@pytest.mark.asyncio
async def test_db_reset_aborts_when_sqlite_backup_cannot_be_created(tmp_path: Path) -> None:
    config_path = tmp_path / "banksia-config.toml"
    data_dir = tmp_path / "banksia-data"
    database_path = data_dir / "banksia.persistence"

    try:
        await cli.cmd_init(build_cli_init_args(config_path, data_dir))
        await dispose_db_engine()
        database_path.write_bytes(b"not a valid SQLite database")

        with pytest.raises(RuntimeError, match="SQLite backup failed before any database change"):
            await cli.cmd_db_reset(
                argparse.Namespace(config=str(config_path), revision="head", json=False)
            )
    finally:
        await dispose_db_engine()

    assert database_path.read_bytes() == b"not a valid SQLite database"
    assert not tuple(data_dir.glob("banksia.persistence.before-reset-*.backup"))


@pytest.mark.asyncio
async def test_db_upgrade_rejects_unknown_sqlite_schema_without_mutation(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "banksia-config.toml"
    data_dir = tmp_path / "banksia-data"
    database_path = data_dir / "banksia.persistence"
    init_args = build_cli_init_args(config_path, data_dir)
    init_args.skip_db_upgrade = True

    try:
        await cli.cmd_init(init_args)
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                "CREATE TABLE flows (task_id TEXT PRIMARY KEY, status TEXT NOT NULL)"
            )
            connection.commit()

        with pytest.raises(DatabaseSchemaUpgradeUnavailableError, match="no supported"):
            await asyncio.to_thread(
                cli.cmd_db_upgrade,
                argparse.Namespace(config=str(config_path), revision="head", json=False),
            )
    finally:
        await dispose_db_engine()

    with sqlite3.connect(database_path) as connection:
        columns = {row[1] for row in connection.execute('PRAGMA table_info("flows")').fetchall()}
    assert columns == {"task_id", "status"}


@pytest.mark.asyncio
async def test_db_upgrade_preserves_sqlite_runtime_rows_and_creates_backup(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    data_dir = tmp_path / "data"
    database_path = data_dir / "banksia.persistence"
    data_dir.mkdir()
    engine = create_runtime_schema_engine(data_dir, name=database_path.name)
    with engine.begin() as connection:
        seed_catalog(connection)
        ids = seed_runtime_scope(connection, suffix="upgrade")
    engine.dispose()
    rewrite_sqlite_table_preserving_rows(
        database_path,
        table_name="attempts",
        transform=_remove_watchdog_replacement_contract,
    )
    config_path.write_text(
        "\n".join(
            (
                "[paths]",
                f'data_dir = "{data_dir}"',
                "",
                "[database]",
                f'url = "sqlite+aiosqlite:///{database_path}"',
                "",
            )
        ),
        encoding="utf-8",
    )

    try:
        result = await asyncio.to_thread(
            cli.cmd_db_upgrade,
            argparse.Namespace(config=str(config_path), revision="head", json=False),
        )
    finally:
        await dispose_db_engine()

    assert result == 0
    backup_paths = tuple(data_dir.glob("banksia.persistence.before-*.backup"))
    assert len(backup_paths) == 1
    with sqlite3.connect(database_path) as connection:
        attempt_columns = {
            str(row[1]) for row in connection.execute('PRAGMA table_info("attempts")')
        }
        assert "watchdog_replacement_count" in attempt_columns
        assert connection.execute(
            "SELECT watchdog_replacement_count FROM attempts WHERE attempt_id = ?",
            (ids.root_attempt_id,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM dispatch_turns WHERE task_id = ?",
            (ids.task_id,),
        ).fetchone() == (3,)
    with sqlite3.connect(backup_paths[0]) as connection:
        backup_columns = {
            str(row[1]) for row in connection.execute('PRAGMA table_info("attempts")')
        }
        assert "watchdog_replacement_count" not in backup_columns
        assert connection.execute(
            "SELECT COUNT(*) FROM dispatch_turns WHERE task_id = ?",
            (ids.task_id,),
        ).fetchone() == (3,)


@pytest.mark.asyncio
async def test_db_upgrade_bootstraps_empty_sqlite_database(tmp_path: Path) -> None:
    config_path = tmp_path / "banksia-config.toml"
    data_dir = tmp_path / "banksia-data"
    database_path = data_dir / "banksia.persistence"
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
    assert not tuple(data_dir.glob("*.backup"))


def _remove_watchdog_replacement_contract(ddl: str) -> str:
    return ddl.replace(
        "\n\twatchdog_replacement_count INTEGER DEFAULT '0' NOT NULL, ",
        "",
    ).replace(
        ", \n\tCONSTRAINT ck_attempts_watchdog_replacement_count "
        "CHECK (watchdog_replacement_count >= 0)",
        "",
    )


@pytest.mark.asyncio
async def test_db_reset_rejects_symlinked_sqlite_database_without_touching_target(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "banksia-config.toml"
    data_dir = tmp_path / "banksia-data"
    database_path = data_dir / "banksia.persistence"
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
