from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from banksia.persistence.session import create_runtime_schema_tables
from banksia.workflows.bootstrap import seed_starter_workflows
from tests.helpers.workflow_runtime import (
    AsyncSessionFactory,
    initialized_workflow_database,
)

type DatabaseBackend = Literal["sqlite", "postgresql"]
type StatementGateTiming = Literal["before", "after"]


class TwoPartyBarrier:
    def __init__(self) -> None:
        self._arrivals = 0
        self._release = asyncio.Event()

    async def wait(self) -> None:
        self._arrivals += 1
        if self._arrivals == 2:
            self._release.set()
        await self._release.wait()


class ControlledGate:
    def __init__(self, *, arrived: asyncio.Event, release: asyncio.Event) -> None:
        self._arrived = arrived
        self._release = release

    async def wait(self) -> None:
        self._arrived.set()
        await self._release.wait()


def install_statement_gate_interceptor(monkeypatch: pytest.MonkeyPatch) -> None:
    original_execute = AsyncSession.execute
    original_scalar = AsyncSession.scalar

    async def execute_after_gate(
        session: AsyncSession,
        statement: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        gate = _take_statement_gate(session, statement=statement)
        await _wait_before_statement(gate)
        result = await original_execute(session, statement, *args, **kwargs)
        await _wait_after_statement(gate)
        return result

    async def scalar_after_gate(
        session: AsyncSession,
        statement: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        gate = _take_statement_gate(session, statement=statement)
        await _wait_before_statement(gate)
        if gate is not None and gate.should_return_none:
            await _wait_after_statement(gate)
            return None
        result = await original_scalar(session, statement, *args, **kwargs)
        await _wait_after_statement(gate)
        return result

    monkeypatch.setattr(AsyncSession, "execute", execute_after_gate)
    monkeypatch.setattr(AsyncSession, "scalar", scalar_after_gate)


def arm_statement_gate(
    session: AsyncSession,
    *,
    table_name: str,
    waiter: TwoPartyBarrier | ControlledGate | None = None,
    should_return_none: bool = False,
    timing: StatementGateTiming = "before",
) -> None:
    session.info["workflow_concurrency_statement_gate"] = _StatementGate(
        table_name=table_name,
        waiter=waiter,
        should_return_none=should_return_none,
        timing=timing,
    )


@asynccontextmanager
async def workflow_database(
    tmp_path: Path,
    *,
    backend: DatabaseBackend,
) -> AsyncIterator[AsyncSessionFactory]:
    if backend == "sqlite":
        async with initialized_workflow_database(tmp_path) as session_factory:
            yield session_factory
        return

    database_url = os.environ.get("OMS_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("OMS_TEST_POSTGRES_URL not set")
    url = make_url(database_url)
    if "test" not in (url.database or "").casefold():
        pytest.skip("Workflow concurrency requires an explicitly disposable test database")
    postgres_schema = f"banksia_workflow_concurrency_{uuid4().hex}"
    engine = create_async_engine(
        url.set(drivername="postgresql+asyncpg"),
        pool_pre_ping=True,
        execution_options={"schema_translate_map": {None: postgres_schema}},
    )
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
    )
    schema_created = False
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(f'CREATE SCHEMA "{postgres_schema}"')
            await connection.run_sync(create_runtime_schema_tables)
        schema_created = True
        async with session_factory() as session:
            await seed_starter_workflows(session)
            await session.commit()
        yield session_factory
    finally:
        if schema_created:
            async with engine.begin() as connection:
                await connection.exec_driver_sql(f'DROP SCHEMA "{postgres_schema}" CASCADE')
        await engine.dispose()


def _take_statement_gate(
    session: AsyncSession,
    *,
    statement: Any,
) -> _StatementGate | None:
    gate = session.info.get("workflow_concurrency_statement_gate")
    if not isinstance(gate, _StatementGate) or gate.table_name not in str(statement):
        return None
    session.info.pop("workflow_concurrency_statement_gate")
    return gate


async def _wait_before_statement(gate: _StatementGate | None) -> None:
    if gate is not None and gate.timing == "before" and gate.waiter is not None:
        await gate.waiter.wait()


async def _wait_after_statement(gate: _StatementGate | None) -> None:
    if gate is not None and gate.timing == "after" and gate.waiter is not None:
        await gate.waiter.wait()


class _StatementGate:
    def __init__(
        self,
        *,
        table_name: str,
        waiter: TwoPartyBarrier | ControlledGate | None,
        should_return_none: bool,
        timing: StatementGateTiming,
    ) -> None:
        self.table_name = table_name
        self.waiter = waiter
        self.should_return_none = should_return_none
        self.timing = timing


__all__ = [
    "ControlledGate",
    "DatabaseBackend",
    "TwoPartyBarrier",
    "arm_statement_gate",
    "install_statement_gate_interceptor",
    "workflow_database",
]
