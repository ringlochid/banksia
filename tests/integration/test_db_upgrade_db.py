from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Connection, text

from banksia.interfaces.cli.bootstrap.database import upgrade_database
from banksia.interfaces.cli.support import command_env, temporary_env
from banksia.persistence.session import (
    create_empty_database_schema,
    dispose_db_engine,
    get_async_engine,
)
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.database_backup import render_postgres_backup_sql
from tests.helpers.disposable_postgres import read_disposable_postgres_url
from tests.helpers.lineage_seed import RuntimeIds, seed_runtime_scope


@pytest.mark.asyncio
async def test_postgres_upgrade_preserves_runtime_rows(tmp_path: Path) -> None:
    database_url = read_disposable_postgres_url()
    if database_url is None:
        pytest.skip("PostgreSQL upgrade proof requires an explicitly disposable test database")
    schema_name = f"banksia_upgrade_{uuid4().hex}"
    data_dir = tmp_path / "data"

    with (
        temporary_env({"BANKSIA_POSTGRES_SCHEMA": schema_name}),
        command_env(
            config_path=tmp_path / "config.toml",
            data_dir=data_dir,
            database_url=database_url.render_as_string(hide_password=False),
            env="test",
        ),
    ):
        try:
            await create_empty_database_schema()
            engine = get_async_engine()
            async with engine.begin() as connection:
                ids = await connection.run_sync(_seed_postgres_upgrade_scope)
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "ALTER TABLE attempts DROP CONSTRAINT "
                        "ck_attempts_watchdog_replacement_count"
                    )
                )
                await connection.execute(
                    text("ALTER TABLE attempts DROP COLUMN watchdog_replacement_count")
                )

            result = await upgrade_database()
            assert result.backup_path is not None
            backup_sql = render_postgres_backup_sql(result.backup_path)
            engine = get_async_engine()
            async with engine.connect() as connection:
                watchdog_count = await connection.scalar(
                    text(
                        "SELECT watchdog_replacement_count FROM attempts "
                        "WHERE attempt_id = :attempt_id"
                    ),
                    {"attempt_id": ids.root_attempt_id},
                )
                dispatch_count = await connection.scalar(
                    text("SELECT COUNT(*) FROM dispatch_turns WHERE task_id = :task_id"),
                    {"task_id": ids.task_id},
                )
        finally:
            await _drop_schema(schema_name)
            await dispose_db_engine()

    assert result.database_backend == "postgresql"
    assert result.applied_upgrade == "attempt-watchdog-replacement-budget"
    assert result.backup_path is not None
    assert result.backup_path.is_file()
    assert ids.task_id in backup_sql
    assert watchdog_count == 0
    assert dispatch_count == 3


async def _drop_schema(schema_name: str) -> None:
    try:
        engine = get_async_engine()
        async with engine.begin() as connection:
            await connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
    except Exception:
        return


def _seed_postgres_upgrade_scope(connection: Connection) -> RuntimeIds:
    seed_catalog(connection)
    return seed_runtime_scope(
        connection,
        suffix="postgres-upgrade",
    )
