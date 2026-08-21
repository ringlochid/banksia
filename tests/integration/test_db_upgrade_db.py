from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import Connection, Table, text

from oh_my_subagents.interfaces.cli.bootstrap.database import upgrade_database
from oh_my_subagents.interfaces.cli.support import command_env, temporary_env
from oh_my_subagents.persistence.models import CommandRunModel
from oh_my_subagents.persistence.models.runtime.common import TASK_EVENT_TYPE_VALUES
from oh_my_subagents.persistence.session import (
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
    schema_name = f"oms_upgrade_{uuid4().hex}"
    data_dir = tmp_path / "data"

    with (
        temporary_env({"OMS_POSTGRES_SCHEMA": schema_name}),
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


@pytest.mark.asyncio
async def test_postgres_upgrade_adds_member_steering_event_type(tmp_path: Path) -> None:
    database_url = read_disposable_postgres_url()
    if database_url is None:
        pytest.skip("PostgreSQL upgrade proof requires an explicitly disposable test database")
    schema_name = f"oms_upgrade_{uuid4().hex}"
    data_dir = tmp_path / "data"
    predecessor_values = tuple(
        value for value in TASK_EVENT_TYPE_VALUES if value != "member_steered"
    )
    allowed_sql = ", ".join(f"'{value}'" for value in predecessor_values)

    with (
        temporary_env({"OMS_POSTGRES_SCHEMA": schema_name}),
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
                await connection.exec_driver_sql(
                    "ALTER TABLE task_events DROP CONSTRAINT ck_task_events_event_type"
                )
                await connection.exec_driver_sql(
                    "ALTER TABLE task_events ADD CONSTRAINT "
                    f"ck_task_events_event_type CHECK (event_type IN ({allowed_sql}))"
                )

            result = await upgrade_database()
            engine = get_async_engine()
            async with engine.connect() as connection:
                dispatch_count = await connection.scalar(
                    text("SELECT COUNT(*) FROM dispatch_turns WHERE task_id = :task_id"),
                    {"task_id": ids.task_id},
                )
        finally:
            await _drop_schema(schema_name)
            await dispose_db_engine()

    assert result.database_backend == "postgresql"
    assert result.applied_upgrade == "member-steering-events"
    assert result.backup_path is not None and result.backup_path.is_file()
    assert dispatch_count == 3


@pytest.mark.asyncio
async def test_postgres_upgrade_widens_command_exit_code_without_losing_rows(
    tmp_path: Path,
) -> None:
    database_url = read_disposable_postgres_url()
    if database_url is None:
        pytest.skip("PostgreSQL upgrade proof requires an explicitly disposable test database")
    schema_name = f"oms_upgrade_{uuid4().hex}"
    data_dir = tmp_path / "data"

    with (
        temporary_env({"OMS_POSTGRES_SCHEMA": schema_name}),
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
                await connection.run_sync(_seed_terminal_command_run, ids)
            async with engine.begin() as connection:
                await connection.exec_driver_sql(
                    "ALTER TABLE command_runs ALTER COLUMN terminal_exit_code "
                    "TYPE INTEGER USING terminal_exit_code::INTEGER"
                )

            result = await upgrade_database()
            engine = get_async_engine()
            async with engine.connect() as connection:
                exit_code = await connection.scalar(
                    text("SELECT terminal_exit_code FROM command_runs WHERE run_id = 'c_upgrade'")
                )
                declared_type = await connection.scalar(
                    text(
                        "SELECT data_type FROM information_schema.columns "
                        "WHERE table_schema = :schema_name "
                        "AND table_name = 'command_runs' "
                        "AND column_name = 'terminal_exit_code'"
                    ),
                    {"schema_name": schema_name},
                )
        finally:
            await _drop_schema(schema_name)
            await dispose_db_engine()

    assert result.database_backend == "postgresql"
    assert result.applied_upgrade == "command-exit-code-width"
    assert result.backup_path is not None and result.backup_path.is_file()
    assert exit_code == 42
    assert declared_type == "bigint"


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


def _seed_terminal_command_run(connection: Connection, ids: RuntimeIds) -> None:
    timestamp = datetime(2026, 8, 11, tzinfo=UTC)
    connection.execute(
        cast(Table, CommandRunModel.__table__).insert(),
        {
            "run_id": "c_upgrade",
            "task_id": ids.task_id,
            "assignment_id": ids.root_assignment_id,
            "attempt_id": ids.root_attempt_id,
            "source_dispatch_id": ids.current_dispatch_id,
            "command_spec_json": {"kind": "argv", "argv": ["python", "--version"]},
            "cwd": None,
            "summary": "Preserved upgrade command",
            "timeout_seconds": None,
            "output_path": ".oms/t_upgrade/command-runs/c_upgrade/output.log",
            "output_observed_bytes": 0,
            "output_written_bytes": 0,
            "output_complete": True,
            "state": "failed",
            "ownership_revision": 0,
            "terminal_summary": "Exited with code 42",
            "terminal_exit_code": 42,
            "terminal_failure_code": "command_failed",
            "terminal_event_source": "process_owner",
            "terminal_actor_ref": "controller",
            "created_at": timestamp,
            "started_at": timestamp,
            "ended_at": timestamp,
        },
    )
