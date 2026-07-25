from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from banksia.operator import (
    OperatorConversationService,
    OperatorRunnerStatus,
    OperatorTurnOutcome,
    OperatorTurnRequest,
    OperatorTurnRunner,
)
from banksia.persistence import RuntimeBase
from banksia.persistence.session import RuntimeAsyncSession, install_sqlite_transaction_control


class RecordingTurnRunner:
    def __init__(self, outcomes: tuple[OperatorTurnOutcome | Exception, ...]) -> None:
        self.status = OperatorRunnerStatus(
            availability="available",
            configured_provider="claude",
            model="claude-test",
            effort="high",
            explanation="Operator is available.",
        )
        self.requests: list[OperatorTurnRequest] = []
        self._outcomes = deque(outcomes)

    async def execute_turn(self, request: OperatorTurnRequest) -> OperatorTurnOutcome:
        self.requests.append(request)
        outcome = self._outcomes.popleft()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class BlockingTurnRunner(RecordingTurnRunner):
    def __init__(self, outcome: OperatorTurnOutcome) -> None:
        super().__init__((outcome,))
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def execute_turn(self, request: OperatorTurnRequest) -> OperatorTurnOutcome:
        self.started.set()
        await self.release.wait()
        return await super().execute_turn(request)


@asynccontextmanager
async def operator_service(
    tmp_path: Path,
    *,
    runner: OperatorTurnRunner,
) -> AsyncIterator[
    tuple[
        OperatorConversationService,
        async_sessionmaker[RuntimeAsyncSession],
    ]
]:
    engine = await create_operator_engine(tmp_path)
    session_factory = async_sessionmaker(
        engine,
        class_=RuntimeAsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    try:
        yield (
            OperatorConversationService(
                session_factory=session_factory,
                runner=runner,
            ),
            session_factory,
        )
    finally:
        await engine.dispose()


async def create_operator_engine(tmp_path: Path) -> AsyncEngine:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'operator.sqlite'}",
        connect_args={"timeout": 5},
    )
    install_sqlite_transaction_control(engine.sync_engine)

    @event.listens_for(engine.sync_engine, "connect")
    def configure_sqlite(dbapi_connection: Any, connection_record: object) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(RuntimeBase.metadata.create_all)
    return engine


__all__ = [
    "BlockingTurnRunner",
    "RecordingTurnRunner",
    "create_operator_engine",
    "operator_service",
]
