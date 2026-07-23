from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch
from uuid import uuid4

import banksia.runtime.node_operations.executor as executor_module
import pytest
from banksia.interfaces.mcp.mcp_operation_failures import runtime_operation_failure
from banksia.persistence.models import (
    FlowModel,
    FlowRevisionModel,
    MemberModel,
    ReplanTransitionModel,
    TeamRevisionModel,
)
from banksia.persistence.session import (
    create_runtime_schema_tables,
    install_sqlite_transaction_control,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.flow.service import cancel_runtime_flow, pause_runtime_flow
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.node_operations.activity import NodeActivitySignal
from sqlalchemy import event, func, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.executor_harness import synchronized_transition_claims
from tests.helpers.lineage_seed import RuntimeIds, seed_runtime_scope

type SessionFactory = async_sessionmaker[AsyncSession]


@dataclass(frozen=True, slots=True)
class AsyncRuntimeHarness:
    executor: NodeOperationExecutor
    session_factory: SessionFactory
    ids: RuntimeIds


@pytest.mark.parametrize("backend", ("sqlite", "postgresql"))
async def test_real_replan_race_has_one_retryable_loser(
    tmp_path: Path,
    backend: str,
) -> None:
    async with _async_runtime_harness(tmp_path, backend=backend, suffix="replan-race") as harness:
        scope = NodeOperationScope(
            task_id=harness.ids.task_id,
            dispatch_id=harness.ids.current_dispatch_id,
        )
        async with _synchronized_replan_admissions_and_claims(harness.executor) as first_admitted:
            first = asyncio.create_task(
                harness.executor.execute(
                    scope=scope,
                    operation_name="add_child",
                    arguments={"child": {"title": "Reviewer"}},
                )
            )
            await asyncio.wait_for(first_admitted.wait(), timeout=10)
            second = asyncio.create_task(
                harness.executor.execute(
                    scope=scope,
                    operation_name="add_child",
                    arguments={"child": {"title": "Verifier"}},
                )
            )
            results = await asyncio.wait_for(
                asyncio.gather(
                    first,
                    second,
                    return_exceptions=True,
                ),
                timeout=20,
            )

        loser = _one_retryable_conflict(results)
        failure = runtime_operation_failure(loser)
        assert failure.retryable is True
        assert failure.suggested_next_step is not None
        async with harness.session_factory() as session:
            counts = await _replan_counts(session)
            flow = await session.get(FlowModel, harness.ids.flow_id)

    assert counts == (2, 2, 3, 1)
    assert flow is not None
    assert flow.status == "running"
    assert flow.current_dispatch_id is None
    assert flow.active_flow_revision_id != harness.ids.flow_revision_id


@pytest.mark.parametrize("backend", ("sqlite", "postgresql"))
@pytest.mark.parametrize("control_operation", ("pause", "cancel"))
async def test_real_flow_control_race_prevents_partial_replan(
    tmp_path: Path,
    backend: str,
    control_operation: str,
) -> None:
    async with _async_runtime_harness(
        tmp_path,
        backend=backend,
        suffix=f"replan-{control_operation}-race",
    ) as harness:
        async with _held_replan_claim() as (replan_ready, release_replan):
            replan_task = asyncio.create_task(
                harness.executor.execute(
                    scope=NodeOperationScope(
                        task_id=harness.ids.task_id,
                        dispatch_id=harness.ids.current_dispatch_id,
                    ),
                    operation_name="add_child",
                    arguments={"child": {"title": "Reviewer"}},
                )
            )
            await asyncio.wait_for(replan_ready.wait(), timeout=10)
            try:
                control_result = await asyncio.wait_for(
                    _apply_flow_control(
                        harness,
                        control_operation=control_operation,
                    ),
                    timeout=10,
                )
            finally:
                release_replan.set()
            replan_results = await asyncio.wait_for(
                asyncio.gather(
                    replan_task,
                    return_exceptions=True,
                ),
                timeout=20,
            )
            results = (*replan_results, control_result)

        loser = _one_retryable_conflict(results)
        assert runtime_operation_failure(loser).retryable is True
        async with harness.session_factory() as session:
            counts = await _replan_counts(session)
            flow = await session.get(FlowModel, harness.ids.flow_id)

    assert counts == (1, 1, 2, 0)
    assert flow is not None
    assert flow.status == ("paused" if control_operation == "pause" else "cancelled")
    assert flow.active_flow_revision_id == harness.ids.flow_revision_id
    assert flow.current_dispatch_id is None


async def _apply_flow_control(
    harness: AsyncRuntimeHarness,
    *,
    control_operation: str,
) -> object:
    control = pause_runtime_flow if control_operation == "pause" else cancel_runtime_flow
    async with harness.session_factory() as session:
        flow = await session.get(FlowModel, harness.ids.flow_id)
        assert flow is not None
        return await control(
            session,
            harness.ids.task_id,
            expected_active_flow_revision_id=harness.ids.flow_revision_id,
            expected_control_revision=flow.control_revision,
        )


@asynccontextmanager
async def _synchronized_replan_admissions_and_claims(
    executor: NodeOperationExecutor,
) -> AsyncIterator[asyncio.Event]:
    original_publish = executor._publish_activity
    admission_arrivals = 0
    first_admitted = asyncio.Event()
    admissions_complete = asyncio.Event()

    async def synchronized_publish(signal: NodeActivitySignal) -> None:
        nonlocal admission_arrivals
        admission_arrivals += 1
        if admission_arrivals == 1:
            first_admitted.set()
        if admission_arrivals == 2:
            admissions_complete.set()
        await admissions_complete.wait()
        await original_publish(signal)

    with patch.object(executor, "_publish_activity", synchronized_publish):
        async with synchronized_transition_claims():
            yield first_admitted


@asynccontextmanager
async def _held_replan_claim() -> AsyncIterator[tuple[asyncio.Event, asyncio.Event]]:
    original_claim = executor_module.claim_exact_node_operation_transition
    replan_ready = asyncio.Event()
    release_replan = asyncio.Event()

    async def held_replan_claim(
        session: AsyncSession,
        authority: NodeOperationAuthority,
    ) -> None:
        replan_ready.set()
        await release_replan.wait()
        await original_claim(session, authority)

    with patch.object(
        executor_module,
        "claim_exact_node_operation_transition",
        held_replan_claim,
    ):
        yield replan_ready, release_replan


async def _replan_counts(session: AsyncSession) -> tuple[int, int, int, int]:
    values = []
    for model in (
        TeamRevisionModel,
        FlowRevisionModel,
        MemberModel,
        ReplanTransitionModel,
    ):
        count = await session.scalar(select(func.count()).select_from(model))
        assert count is not None
        values.append(count)
    return cast(tuple[int, int, int, int], tuple(values))


def _one_retryable_conflict(results: Sequence[object]) -> RuntimeOperationError:
    errors = [result for result in results if isinstance(result, BaseException)]
    assert len(errors) == 1, results
    assert sum(not isinstance(result, BaseException) for result in results) == 1
    error = errors[0]
    assert isinstance(error, RuntimeOperationError)
    assert error.code == OperationFailureCode.CONFLICT
    assert error.is_retryable is True
    assert error.suggested_next_step is not None
    return error


@asynccontextmanager
async def _async_runtime_harness(
    tmp_path: Path,
    *,
    backend: str,
    suffix: str,
) -> AsyncIterator[AsyncRuntimeHarness]:
    exact_suffix = f"real-{backend}-{suffix}-{uuid4().hex[:8]}"
    engine, schema_name = _create_test_engine(
        tmp_path,
        backend=backend,
        suffix=exact_suffix,
    )
    session_factory = async_sessionmaker(
        engine,
        autoflush=False,
        expire_on_commit=False,
    )
    schema_created = False
    try:
        async with engine.begin() as connection:
            if schema_name is not None:
                await connection.exec_driver_sql(f'CREATE SCHEMA "{schema_name}"')
                schema_created = True
            await connection.run_sync(create_runtime_schema_tables)
            await connection.run_sync(seed_catalog)
            ids = await connection.run_sync(partial(seed_runtime_scope, suffix=exact_suffix))
        with patch.object(
            executor_module,
            "get_session_factory",
            return_value=session_factory,
        ):
            yield AsyncRuntimeHarness(
                executor=NodeOperationExecutor(),
                session_factory=session_factory,
                ids=ids,
            )
    finally:
        if schema_created:
            async with engine.begin() as connection:
                await connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        await engine.dispose()


def _create_test_engine(
    tmp_path: Path,
    *,
    backend: str,
    suffix: str,
) -> tuple[AsyncEngine, str | None]:
    if backend == "postgresql":
        database_url = _disposable_postgres_url()
        if database_url is None:
            pytest.skip("a disposable PostgreSQL test database is not configured")
        schema_name = f"banksia_replan_race_{uuid4().hex}"
        return (
            create_async_engine(
                database_url,
                execution_options={"schema_translate_map": {None: schema_name}},
            ),
            schema_name,
        )
    database_path = tmp_path / f"{suffix}.sqlite"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
        poolclass=NullPool,
    )
    install_sqlite_transaction_control(engine.sync_engine)

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_runtime_pragmas(
        dbapi_connection: Any,
        connection_record: object,
    ) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine, None


def _disposable_postgres_url() -> URL | None:
    raw_url = os.environ.get("BANKSIA_TEST_POSTGRES_URL") or os.environ.get("BANKSIA_DATABASE_URL")
    if raw_url is None:
        return None
    database_url = make_url(raw_url)
    database_name = database_url.database or ""
    if database_url.get_backend_name() != "postgresql" or "test" not in database_name.casefold():
        return None
    return database_url.set(drivername="postgresql+asyncpg")
