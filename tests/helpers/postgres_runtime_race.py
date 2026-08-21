from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, TypeVar
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import oh_my_subagents.runtime.node_operations.executor as executor_module
from oh_my_subagents.config import CodexSettings, RuntimeSettings, Settings
from oh_my_subagents.persistence.models import TaskModel, WorkspaceBindingModel
from oh_my_subagents.persistence.session import create_runtime_schema_tables
from oh_my_subagents.providers import ProviderKind
from oh_my_subagents.runtime.dispatch.preparation import DispatchOpeningDependencies
from oh_my_subagents.runtime.node_operations import NodeOperationExecutor
from oh_my_subagents.runtime.node_operations.activity import NodeActivitySignal
from oh_my_subagents.runtime.post_commit import CapturedRuntimeEffectPublisher
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.disposable_postgres import read_disposable_postgres_url
from tests.helpers.lineage_seed import RuntimeIds, seed_runtime_scope

type SessionFactory = async_sessionmaker[AsyncSession]
type ActivityPublisher = Callable[[NodeActivitySignal], Awaitable[None]]

_ContenderResult = TypeVar("_ContenderResult")


@dataclass(frozen=True, slots=True)
class PostgresRuntimeHarness:
    engine: AsyncEngine
    executor: NodeOperationExecutor
    session_factory: SessionFactory
    ids: RuntimeIds
    dependencies: DispatchOpeningDependencies


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


async def run_two_contenders_at_task_update_barrier(
    harness: PostgresRuntimeHarness,
    *,
    task_id: str,
    contender: Callable[[], Coroutine[Any, Any, _ContenderResult]],
) -> tuple[_ContenderResult, _ContenderResult]:
    """Release two contenders only after both attempt the same Task UPDATE."""

    async with harness.session_factory() as blocker:
        locked_task_id = await blocker.scalar(
            select(TaskModel.task_id).where(TaskModel.task_id == task_id).with_for_update()
        )
        assert locked_task_id == task_id
        with observe_update_order(harness.engine, table_name="tasks") as task_updates:
            contenders: tuple[
                asyncio.Task[_ContenderResult],
                asyncio.Task[_ContenderResult],
            ] = (
                asyncio.create_task(contender()),
                asyncio.create_task(contender()),
            )
            try:
                await wait_for_thread_event(task_updates.first_update_started)
                await wait_for_thread_event(task_updates.second_update_started)
                await blocker.rollback()
                first, second = await asyncio.wait_for(
                    asyncio.gather(*contenders),
                    timeout=20,
                )
            except BaseException:
                await blocker.rollback()
                for pending_contender in contenders:
                    pending_contender.cancel()
                await asyncio.gather(*contenders, return_exceptions=True)
                raise
    return first, second


def _normalized_statement(statement: str) -> str:
    return statement.casefold().replace('"', "")


def _updates_table(statement: str, table_name: str) -> bool:
    return statement.lstrip().startswith("update ") and f"{table_name} set" in statement


def _create_test_engine() -> tuple[AsyncEngine, str]:
    database_url = read_disposable_postgres_url()
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


__all__ = [
    "PostgresRuntimeHarness",
    "UpdateOrderEvents",
    "observe_update_order",
    "observe_update_started",
    "postgres_runtime_harness",
    "run_two_contenders_at_task_update_barrier",
    "wait_for_thread_event",
]
