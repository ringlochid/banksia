from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

import banksia.runtime.node_operations.executor as executor_module
import pytest
from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import TaskModel, WorkspaceBindingModel
from banksia.persistence.session import create_runtime_schema_tables
from banksia.providers import ProviderKind
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.node_operations import NodeOperationExecutor
from banksia.runtime.node_operations.activity import NodeActivitySignal
from banksia.runtime.post_commit import CapturedRuntimeEffectPublisher
from sqlalchemy import event, update
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.lineage_seed import RuntimeIds, seed_runtime_scope

type SessionFactory = async_sessionmaker[AsyncSession]
type ActivityPublisher = Callable[[NodeActivitySignal], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class PostgresRuntimeHarness:
    engine: AsyncEngine
    executor: NodeOperationExecutor
    session_factory: SessionFactory
    ids: RuntimeIds
    dependencies: DispatchOpeningDependencies


@dataclass(frozen=True, slots=True)
class FlowFirstEvents:
    owner_flow_acquired: threading.Event
    owner_local_update_started: threading.Event
    control_flow_update_started: threading.Event


@dataclass(frozen=True, slots=True)
class UpdateOrderEvents:
    first_update_started: threading.Event
    second_update_started: threading.Event


@asynccontextmanager
async def postgres_runtime_harness(
    *,
    suffix: str,
    publish_activity_signal: ActivityPublisher | None = None,
) -> AsyncIterator[PostgresRuntimeHarness]:
    exact_suffix = f"real-postgresql-{suffix}-{uuid4().hex[:8]}"
    engine, schema_name = _create_test_engine()
    temporary_directory = TemporaryDirectory(prefix=f"{exact_suffix}-")
    workspace = Path(temporary_directory.name) / "workspace"
    task_root = workspace / ".banksia" / f"task.{exact_suffix}"
    workspace.mkdir(parents=True)
    for path in (
        task_root / "notes",
        task_root / "artifacts",
        task_root / "command-runs",
    ):
        path.mkdir(parents=True)
    session_factory = async_sessionmaker(
        engine,
        autoflush=False,
        expire_on_commit=False,
    )
    schema_created = False
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(f'CREATE SCHEMA "{schema_name}"')
            schema_created = True
            await connection.run_sync(create_runtime_schema_tables)
            await connection.run_sync(seed_catalog)
            ids = await connection.run_sync(partial(seed_runtime_scope, suffix=exact_suffix))
        async with session_factory() as session:
            await session.execute(
                update(TaskModel)
                .where(TaskModel.task_id == ids.task_id)
                .values(task_root_path=str(task_root))
            )
            await session.execute(
                update(WorkspaceBindingModel)
                .where(WorkspaceBindingModel.task_id == ids.task_id)
                .values(normalized_root_path=str(workspace))
            )
            await session.commit()
        dependencies = DispatchOpeningDependencies.create(
            settings=Settings(
                runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
                codex=CodexSettings(enabled=True),
            ),
            available_adapter_kinds=(ProviderKind.CODEX,),
            post_commit_publisher=CapturedRuntimeEffectPublisher(),
        )
        with patch.object(
            executor_module,
            "get_session_factory",
            return_value=session_factory,
        ):
            yield PostgresRuntimeHarness(
                engine=engine,
                executor=NodeOperationExecutor(
                    publish_activity_signal=publish_activity_signal,
                    dispatch_opening_dependencies=dependencies,
                ),
                session_factory=session_factory,
                ids=ids,
                dependencies=dependencies,
            )
    finally:
        if schema_created:
            async with engine.begin() as connection:
                await connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        await engine.dispose()
        temporary_directory.cleanup()


@contextmanager
def observe_flow_first_order(
    engine: AsyncEngine,
    *,
    owner_local_table: str,
) -> Iterator[FlowFirstEvents]:
    owner_flow_acquired = threading.Event()
    owner_local_update_started = threading.Event()
    control_flow_update_started = threading.Event()
    flow_update_count = 0

    def before_cursor_execute(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del connection, cursor, parameters, context, executemany
        nonlocal flow_update_count
        normalized = _normalized_statement(statement)
        if _updates_table(normalized, "flows"):
            flow_update_count += 1
            if flow_update_count == 2:
                control_flow_update_started.set()
        if _updates_table(normalized, owner_local_table):
            owner_local_update_started.set()

    def after_cursor_execute(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del connection, cursor, parameters, context, executemany
        normalized = _normalized_statement(statement)
        if _updates_table(normalized, "flows") and flow_update_count == 1:
            owner_flow_acquired.set()

    event.listen(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
    event.listen(engine.sync_engine, "after_cursor_execute", after_cursor_execute)
    try:
        yield FlowFirstEvents(
            owner_flow_acquired=owner_flow_acquired,
            owner_local_update_started=owner_local_update_started,
            control_flow_update_started=control_flow_update_started,
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
        event.remove(engine.sync_engine, "after_cursor_execute", after_cursor_execute)


@contextmanager
def observe_update_started(
    engine: AsyncEngine,
    *,
    table_name: str,
) -> Iterator[threading.Event]:
    update_started = threading.Event()

    def before_cursor_execute(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del connection, cursor, parameters, context, executemany
        if _updates_table(_normalized_statement(statement), table_name):
            update_started.set()

    event.listen(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield update_started
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before_cursor_execute)


@contextmanager
def observe_update_order(
    engine: AsyncEngine,
    *,
    table_name: str,
) -> Iterator[UpdateOrderEvents]:
    first_update_started = threading.Event()
    second_update_started = threading.Event()
    update_count = 0

    def before_cursor_execute(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del connection, cursor, parameters, context, executemany
        nonlocal update_count
        if not _updates_table(_normalized_statement(statement), table_name):
            return
        update_count += 1
        if update_count == 1:
            first_update_started.set()
        elif update_count == 2:
            second_update_started.set()

    event.listen(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield UpdateOrderEvents(
            first_update_started=first_update_started,
            second_update_started=second_update_started,
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before_cursor_execute)


async def wait_for_thread_event(signal: threading.Event) -> None:
    observed = await asyncio.to_thread(signal.wait, 10)
    assert observed


def _normalized_statement(statement: str) -> str:
    return statement.casefold().replace('"', "")


def _updates_table(statement: str, table_name: str) -> bool:
    return statement.lstrip().startswith("update ") and f"{table_name} set" in statement


def _create_test_engine() -> tuple[AsyncEngine, str]:
    database_url = _disposable_postgres_url()
    if database_url is None:
        pytest.skip("a disposable PostgreSQL test database is not configured")
    schema_name = f"banksia_runtime_race_{uuid4().hex}"
    return (
        create_async_engine(
            database_url,
            execution_options={"schema_translate_map": {None: schema_name}},
        ),
        schema_name,
    )


def _disposable_postgres_url() -> URL | None:
    raw_url = os.environ.get("BANKSIA_TEST_POSTGRES_URL") or os.environ.get("BANKSIA_DATABASE_URL")
    if raw_url is None:
        return None
    database_url = make_url(raw_url)
    database_name = database_url.database or ""
    if database_url.get_backend_name() != "postgresql" or "test" not in database_name.casefold():
        return None
    return database_url.set(drivername="postgresql+asyncpg")


__all__ = [
    "FlowFirstEvents",
    "PostgresRuntimeHarness",
    "UpdateOrderEvents",
    "observe_flow_first_order",
    "observe_update_order",
    "observe_update_started",
    "postgres_runtime_harness",
    "wait_for_thread_event",
]
