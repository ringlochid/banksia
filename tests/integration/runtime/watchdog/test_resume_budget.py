from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.config import CodexSettings, RuntimeSettings, Settings
from oh_my_subagents.persistence.models import AttemptModel, DispatchTurnModel, TaskModel
from oh_my_subagents.providers import ProviderKind
from oh_my_subagents.runtime.dispatch.preparation import DispatchOpeningDependencies
from oh_my_subagents.runtime.post_commit import CapturedRuntimeEffectPublisher, WatchdogDue
from oh_my_subagents.runtime.task_control.service import continue_runtime_task
from oh_my_subagents.runtime.watchdog import calculate_watchdog_due_at, recover_stale_dispatch
from tests.helpers.executor_harness import (
    SessionFactory,
    make_seed_child_terminal,
    seeded_executor,
)
from tests.helpers.lineage_seed import RuntimeIds
from tests.helpers.sqlite_runtime import SyncSessionAdapter

_BASE_TIME = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


@dataclass
class _ManualClock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current


async def test_resume_refills_watchdog_budget_without_erasing_dispatch_history(
    tmp_path: Path,
) -> None:
    clock = _ManualClock(_BASE_TIME + timedelta(minutes=15, seconds=1))
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="watchdog-resume-budget") as (
        _,
        session_factory,
        ids,
        _,
    ):
        async with session_factory() as session:
            await make_seed_child_terminal(session, ids)
        dependencies = _opening_dependencies(clock=clock, publisher=publisher)
        current_dispatch_id = await _consume_watchdog_replacements(
            session_factory,
            ids,
            dependencies=dependencies,
            clock=clock,
        )
        exhausted_signal = await _stale_signal(
            session_factory,
            current_dispatch_id,
            activity_revision=3,
            anchor=_BASE_TIME + timedelta(hours=2),
        )
        clock.current = exhausted_signal.due_at + timedelta(seconds=1)
        async with session_factory() as session:
            exhausted = await recover_stale_dispatch(
                cast(AsyncSession, session),
                signal=exhausted_signal,
                dependencies=dependencies,
            )
            task = await session.get(TaskModel, ids.task_id)
            assert task is not None
            resumed = await continue_runtime_task(
                cast(AsyncSession, session),
                ids.task_id,
                expected_team_revision_id=ids.team_revision_id,
                expected_control_revision=task.control_revision,
                dependencies=dependencies,
            )
            resumed_attempt = await session.get(
                AttemptModel,
                ids.root_attempt_id,
                populate_existing=True,
            )
            historical_count_after_resume = await _watchdog_dispatch_count(session)

        assert exhausted.outcome == "paused"
        assert resumed.status.value == "running"
        assert resumed_attempt is not None
        assert resumed_attempt.watchdog_replacement_count == 0
        assert resumed_attempt.current_dispatch_id is not None
        assert historical_count_after_resume == 2

        resumed_dispatch_id = resumed_attempt.current_dispatch_id
        fresh_signal = await _stale_signal(
            session_factory,
            resumed_dispatch_id,
            activity_revision=4,
            anchor=_BASE_TIME + timedelta(hours=3),
        )
        clock.current = fresh_signal.due_at + timedelta(seconds=1)
        async with session_factory() as session:
            fresh_recovery = await recover_stale_dispatch(
                cast(AsyncSession, session),
                signal=fresh_signal,
                dependencies=dependencies,
            )
            recovered_attempt = await session.get(AttemptModel, ids.root_attempt_id)
            historical_count_after_recovery = await _watchdog_dispatch_count(session)

    assert fresh_recovery.outcome == "opened"
    assert recovered_attempt is not None
    assert recovered_attempt.watchdog_replacement_count == 1
    assert historical_count_after_recovery == 3


async def _consume_watchdog_replacements(
    session_factory: SessionFactory,
    ids: RuntimeIds,
    *,
    dependencies: DispatchOpeningDependencies,
    clock: _ManualClock,
) -> str:
    current_dispatch_id = ids.current_dispatch_id
    for replacement_index in range(2):
        signal = await _stale_signal(
            session_factory,
            current_dispatch_id,
            activity_revision=replacement_index + 1,
            anchor=_BASE_TIME + timedelta(hours=replacement_index),
        )
        clock.current = signal.due_at + timedelta(seconds=1)
        async with session_factory() as session:
            result = await recover_stale_dispatch(
                cast(AsyncSession, session),
                signal=signal,
                dependencies=dependencies,
            )
        assert result.outcome == "opened" and result.dispatch_id is not None
        current_dispatch_id = result.dispatch_id
    return current_dispatch_id


async def _stale_signal(
    session_factory: SessionFactory,
    dispatch_id: str,
    *,
    activity_revision: int,
    anchor: datetime,
) -> WatchdogDue:
    async with session_factory() as session:
        dispatch = await session.get(DispatchTurnModel, dispatch_id)
        assert dispatch is not None
        dispatch.status = "open"
        dispatch.adapter_started_at = anchor
        dispatch.last_node_activity_at = anchor
        dispatch.node_activity_revision = activity_revision
        dispatch.next_provider_start_at = None
        dispatch.provider_start_retry_kind = None
        dispatch.provider_start_last_error_code = None
        dispatch.closed_at = None
        dispatch.closed_reason = None
        await session.commit()
    return WatchdogDue(
        dispatch_id=dispatch_id,
        activity_revision=activity_revision,
        due_at=calculate_watchdog_due_at(
            adapter_started_at=anchor,
            last_node_activity_at=anchor,
            inactivity_timeout_seconds=900,
        ),
    )


async def _watchdog_dispatch_count(
    session: AsyncSession | SyncSessionAdapter,
) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(DispatchTurnModel)
        .where(DispatchTurnModel.opened_reason == "watchdog_recovery")
    )
    return int(count or 0)


def _opening_dependencies(
    *,
    clock: _ManualClock,
    publisher: CapturedRuntimeEffectPublisher,
) -> DispatchOpeningDependencies:
    settings = Settings(
        runtime=RuntimeSettings(
            default_provider=ProviderKind.CODEX,
            watchdog_inactivity_timeout_seconds=900,
            watchdog_same_attempt_replacement_limit=2,
        ),
        codex=CodexSettings(enabled=True),
    )
    return DispatchOpeningDependencies.create(
        settings=settings,
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=publisher,
        clock=clock,
    )
