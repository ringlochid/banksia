from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from autoclaw.persistence import RuntimeBase
from autoclaw.persistence.models import DispatchTurnModel
from autoclaw.runtime.post_commit import (
    RuntimeEffectSignal,
    WatchdogDeadlineChanged,
    WatchdogDue,
)
from autoclaw.runtime.post_commit.deadlines import DeadlineScheduler
from autoclaw.runtime.watchdog import create_watchdog_deadline_changed_handler
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.executor_harness import seeded_executor
from tests.helpers.lineage_seed import RuntimeIds, seed_runtime_scope

_BASE_TIME = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


@dataclass
class _FakeTimer:
    is_cancelled: bool = False

    def cancel(self) -> None:
        self.is_cancelled = True


async def test_first_open_deadline_uses_later_adapter_acceptance_anchor(
    tmp_path: Path,
) -> None:
    adapter_started_at = _BASE_TIME + timedelta(minutes=10)
    expected_due_at = adapter_started_at + timedelta(minutes=15)
    published: list[object] = []
    scheduled: list[tuple[float, Callable[[], None], _FakeTimer]] = []

    def schedule_later(delay: float, callback: Callable[[], None]) -> _FakeTimer:
        timer = _FakeTimer()
        scheduled.append((delay, callback, timer))
        return timer

    def capture_due(signal: RuntimeEffectSignal) -> bool:
        published.append(signal)
        return True

    async with seeded_executor(tmp_path, suffix="watchdog-first-open") as (
        _,
        session_factory,
        ids,
        _,
    ):
        async with session_factory() as session:
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            assert dispatch is not None
            dispatch.status = "open"
            dispatch.adapter_started_at = adapter_started_at
            dispatch.last_node_activity_at = _BASE_TIME + timedelta(minutes=5)
            dispatch.node_activity_revision = 3
            dispatch.next_provider_start_at = None
            dispatch.provider_start_retry_kind = None
            await session.commit()

        scheduler = DeadlineScheduler(
            publish=capture_due,
            now=lambda: adapter_started_at,
            schedule_later=schedule_later,
        )
        async with scheduler:
            handler = create_watchdog_deadline_changed_handler(
                scheduler,
                inactivity_timeout_seconds=900,
            )
            async with session_factory() as session:
                await handler(
                    cast(AsyncSession, session),
                    WatchdogDeadlineChanged(
                        dispatch_id=ids.current_dispatch_id,
                        activity_revision=3,
                        due_at=expected_due_at,
                    ),
                )
            assert len(scheduled) == 1
            assert scheduled[0][0] == 900

            scheduled[0][1]()

    assert published == [
        WatchdogDue(
            dispatch_id=ids.current_dispatch_id,
            activity_revision=3,
            due_at=expected_due_at,
        )
    ]


async def test_deadline_registration_survives_real_async_session_rollback(
    tmp_path: Path,
) -> None:
    """Keep the deadline snapshot usable after ending the read transaction."""

    database_path = tmp_path / "watchdog-deadline.sqlite"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    adapter_started_at = _BASE_TIME + timedelta(minutes=10)
    expected_due_at = adapter_started_at + timedelta(minutes=15)
    scheduled: list[tuple[float, Callable[[], None], _FakeTimer]] = []

    def seed(connection: Connection) -> RuntimeIds:
        seed_catalog(connection)
        return seed_runtime_scope(connection, suffix="watchdog-real-async")

    def schedule_later(delay: float, callback: Callable[[], None]) -> _FakeTimer:
        timer = _FakeTimer()
        scheduled.append((delay, callback, timer))
        return timer

    try:
        async with engine.begin() as connection:
            await connection.run_sync(RuntimeBase.metadata.create_all)
            ids = await connection.run_sync(seed)

        session_factory = async_sessionmaker(
            engine,
            autoflush=False,
            expire_on_commit=False,
        )
        async with session_factory() as session:
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            assert dispatch is not None
            dispatch.status = "open"
            dispatch.adapter_started_at = adapter_started_at
            dispatch.last_node_activity_at = None
            dispatch.node_activity_revision = 3
            dispatch.next_provider_start_at = None
            dispatch.provider_start_retry_kind = None
            await session.commit()

        scheduler = DeadlineScheduler(
            publish=lambda signal: True,
            now=lambda: adapter_started_at,
            schedule_later=schedule_later,
        )
        async with scheduler:
            handler = create_watchdog_deadline_changed_handler(
                scheduler,
                inactivity_timeout_seconds=900,
            )
            async with session_factory() as session:
                await handler(
                    session,
                    WatchdogDeadlineChanged(
                        dispatch_id=ids.current_dispatch_id,
                        activity_revision=3,
                        due_at=expected_due_at,
                    ),
                )

        assert len(scheduled) == 1
        assert scheduled[0][0] == 900
    finally:
        await engine.dispose()


__all__ = []
