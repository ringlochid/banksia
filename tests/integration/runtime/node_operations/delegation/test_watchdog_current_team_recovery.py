from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.config import CodexSettings, RuntimeSettings, Settings
from oh_my_subagents.persistence.models import AttemptModel, DispatchTurnModel, TaskModel
from oh_my_subagents.providers import ProviderKind
from oh_my_subagents.runtime.dispatch.preparation import DispatchOpeningDependencies
from oh_my_subagents.runtime.errors import RuntimeOperationError
from oh_my_subagents.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    DispatchCleanupRequested,
    DispatchStartDue,
    WatchdogDeadlineChanged,
    WatchdogDue,
)
from oh_my_subagents.runtime.post_commit.dispatch_startup import read_watchdog_deadline_page
from oh_my_subagents.runtime.task_control.control import continue_task
from oh_my_subagents.runtime.watchdog import (
    calculate_watchdog_due_at,
    recover_stale_dispatch,
)
from tests.helpers.disjoint_team_runtime import (
    RuntimeLane,
    create_runtime_opening_dependencies,
    open_disjoint_child_lanes,
)
from tests.helpers.executor_harness import SessionFactory, seeded_executor
from tests.helpers.lineage_seed import RuntimeIds


async def test_watchdog_replaces_retained_lane_on_the_current_team(
    tmp_path: Path,
) -> None:
    observed_at = datetime(2026, 7, 24, 12, 15, 1, tzinfo=UTC)
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="watchdog-retained-team") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        branch_lane, retained_lane, current_team_revision_id = await open_disjoint_child_lanes(
            executor,
            session_factory,
            ids,
            dependencies=create_runtime_opening_dependencies(),
        )
        signal = await _make_stale_watchdog_signal(
            session_factory,
            retained_lane.dispatch_id,
            anchor=observed_at - timedelta(minutes=15, seconds=1),
        )
        await _assert_watchdog_startup_discovery(
            session_factory,
            retained_lane.dispatch_id,
        )
        async with session_factory() as session:
            result = await recover_stale_dispatch(
                cast(AsyncSession, session),
                signal=signal,
                dependencies=_watchdog_dependencies(
                    observed_at=observed_at,
                    publisher=publisher,
                ),
            )
        assert result.outcome == "opened"
        assert result.dispatch_id is not None
        await _assert_retained_lane_replacement(
            session_factory,
            branch_lane=branch_lane,
            retained_lane=retained_lane,
            successor_dispatch_id=result.dispatch_id,
            current_team_revision_id=current_team_revision_id,
        )

    assert publisher.signals[0] == DispatchCleanupRequested(retained_lane.dispatch_id)
    assert isinstance(publisher.signals[1], DispatchStartDue)
    assert publisher.signals[1].dispatch_id == result.dispatch_id


async def test_watchdog_failure_pauses_all_lanes_and_resume_reopens_each_once(
    tmp_path: Path,
) -> None:
    observed_at = datetime(2026, 7, 24, 13, 15, 1, tzinfo=UTC)
    pause_publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="watchdog-task-wide-pause") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        branch_lane, retained_lane, current_team_revision_id = await open_disjoint_child_lanes(
            executor,
            session_factory,
            ids,
            dependencies=create_runtime_opening_dependencies(),
        )
        signal = await _make_stale_watchdog_signal(
            session_factory,
            retained_lane.dispatch_id,
            anchor=observed_at - timedelta(minutes=15, seconds=1),
        )
        paused_control_revision = await _pause_all_runnable_lanes(
            session_factory,
            ids=ids,
            branch_lane=branch_lane,
            retained_lane=retained_lane,
            current_team_revision_id=current_team_revision_id,
            signal=signal,
            observed_at=observed_at,
            publisher=pause_publisher,
        )
        await _resume_all_lanes_exactly_once(
            session_factory,
            ids=ids,
            branch_lane=branch_lane,
            retained_lane=retained_lane,
            current_team_revision_id=current_team_revision_id,
            paused_control_revision=paused_control_revision,
            observed_at=observed_at + timedelta(seconds=1),
        )


async def _assert_watchdog_startup_discovery(
    session_factory: SessionFactory,
    dispatch_id: str,
) -> None:
    async_factory = cast(
        Callable[[], AbstractAsyncContextManager[AsyncSession]],
        session_factory,
    )
    audit_page = await read_watchdog_deadline_page(
        async_factory,
        cursor=None,
        page_size=10,
        inactivity_timeout_seconds=900,
    )
    assert any(
        isinstance(signal, WatchdogDeadlineChanged) and signal.dispatch_id == dispatch_id
        for signal in audit_page.sources
    )


async def _assert_retained_lane_replacement(
    session_factory: SessionFactory,
    *,
    branch_lane: RuntimeLane,
    retained_lane: RuntimeLane,
    successor_dispatch_id: str,
    current_team_revision_id: str,
) -> None:
    async with session_factory() as session:
        source = await session.get(DispatchTurnModel, retained_lane.dispatch_id)
        successor = await session.get(DispatchTurnModel, successor_dispatch_id)
        branch_attempt = await session.get(AttemptModel, branch_lane.attempt_id)
        retained_attempt = await session.get(AttemptModel, retained_lane.attempt_id)
    assert source is not None and source.closed_reason == "watchdog_superseded"
    assert successor is not None
    assert successor.team_revision_id == current_team_revision_id
    assert successor.predecessor_dispatch_id == retained_lane.dispatch_id
    assert branch_attempt is not None
    assert branch_attempt.current_dispatch_id == branch_lane.dispatch_id
    assert retained_attempt is not None
    assert retained_attempt.current_dispatch_id == successor_dispatch_id


async def _pause_all_runnable_lanes(
    session_factory: SessionFactory,
    *,
    ids: RuntimeIds,
    branch_lane: RuntimeLane,
    retained_lane: RuntimeLane,
    current_team_revision_id: str,
    signal: WatchdogDue,
    observed_at: datetime,
    publisher: CapturedRuntimeEffectPublisher,
) -> int:
    invalid_dependencies = DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(
                default_provider=ProviderKind.CODEX,
                watchdog_inactivity_timeout_seconds=900,
            ),
        ),
        available_adapter_kinds=(ProviderKind.CODEX,),
        post_commit_publisher=publisher,
        clock=lambda: observed_at,
    )
    async with session_factory() as session:
        result = await recover_stale_dispatch(
            cast(AsyncSession, session),
            signal=signal,
            dependencies=invalid_dependencies,
        )
        task = await session.get(TaskModel, ids.task_id)
        branch_attempt = await session.get(AttemptModel, branch_lane.attempt_id)
        retained_attempt = await session.get(AttemptModel, retained_lane.attempt_id)
        branch_dispatch = await session.get(DispatchTurnModel, branch_lane.dispatch_id)
        retained_dispatch = await session.get(
            DispatchTurnModel,
            retained_lane.dispatch_id,
        )
    assert result.outcome == "paused"
    assert task is not None and task.status == "paused"
    assert task.current_team_revision_id == current_team_revision_id
    assert branch_attempt is not None and branch_attempt.current_dispatch_id is None
    assert retained_attempt is not None and retained_attempt.current_dispatch_id is None
    assert branch_dispatch is not None and branch_dispatch.closed_reason == "paused"
    assert retained_dispatch is not None
    assert retained_dispatch.closed_reason == "control_failed"
    cleanup_ids = {
        cleanup.dispatch_id
        for cleanup in publisher.signals
        if isinstance(cleanup, DispatchCleanupRequested)
    }
    assert cleanup_ids == {branch_lane.dispatch_id, retained_lane.dispatch_id}
    return cast(int, task.control_revision)


async def _resume_all_lanes_exactly_once(
    session_factory: SessionFactory,
    *,
    ids: RuntimeIds,
    branch_lane: RuntimeLane,
    retained_lane: RuntimeLane,
    current_team_revision_id: str,
    paused_control_revision: int,
    observed_at: datetime,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    dependencies = _watchdog_dependencies(
        observed_at=observed_at,
        publisher=publisher,
    )
    async with session_factory() as session:
        await continue_task(
            cast(AsyncSession, session),
            ids.task_id,
            expected_team_revision_id=current_team_revision_id,
            expected_control_revision=paused_control_revision,
            dependencies=dependencies,
        )
    async with session_factory() as session:
        with pytest.raises(RuntimeOperationError):
            await continue_task(
                cast(AsyncSession, session),
                ids.task_id,
                expected_team_revision_id=current_team_revision_id,
                expected_control_revision=paused_control_revision,
                dependencies=dependencies,
            )
        await session.rollback()
        task = await session.get(TaskModel, ids.task_id)
        branch_attempt = await session.get(AttemptModel, branch_lane.attempt_id)
        retained_attempt = await session.get(AttemptModel, retained_lane.attempt_id)
        successor_counts = (
            await _successor_count(session, branch_lane.dispatch_id),
            await _successor_count(session, retained_lane.dispatch_id),
        )
    assert task is not None and task.status == "running"
    assert branch_attempt is not None and branch_attempt.current_dispatch_id is not None
    assert retained_attempt is not None and retained_attempt.current_dispatch_id is not None
    assert successor_counts == (1, 1)
    assert sum(isinstance(signal, DispatchStartDue) for signal in publisher.signals) == 2


async def _successor_count(session: Any, dispatch_id: str) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(DispatchTurnModel)
            .where(DispatchTurnModel.predecessor_dispatch_id == dispatch_id)
        )
        or 0
    )


async def _make_stale_watchdog_signal(
    session_factory: SessionFactory,
    dispatch_id: str,
    *,
    anchor: datetime,
) -> WatchdogDue:
    async with session_factory() as session:
        dispatch = await session.get(DispatchTurnModel, dispatch_id)
        assert dispatch is not None
        dispatch.status = "open"
        dispatch.adapter_started_at = anchor
        dispatch.last_node_activity_at = anchor
        dispatch.node_activity_revision = 1
        dispatch.next_provider_start_at = None
        dispatch.provider_start_retry_kind = None
        dispatch.provider_start_last_error_code = None
        dispatch.closed_at = None
        dispatch.closed_reason = None
        await session.commit()
    return WatchdogDue(
        dispatch_id=dispatch_id,
        activity_revision=1,
        due_at=calculate_watchdog_due_at(
            adapter_started_at=anchor,
            last_node_activity_at=anchor,
            inactivity_timeout_seconds=900,
        ),
    )


def _watchdog_dependencies(
    *,
    observed_at: datetime,
    publisher: CapturedRuntimeEffectPublisher,
) -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(
                default_provider=ProviderKind.CODEX,
                watchdog_inactivity_timeout_seconds=900,
                watchdog_same_attempt_replacement_limit=2,
            ),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds=(ProviderKind.CODEX,),
        post_commit_publisher=publisher,
        clock=lambda: observed_at,
    )
