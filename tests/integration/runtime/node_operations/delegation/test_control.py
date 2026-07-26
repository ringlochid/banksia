from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AssignmentModel,
    AttemptModel,
    AttemptWaitModel,
    DelegationWaveMemberModel,
    DelegationWaveModel,
    TaskModel,
)
from banksia.runtime.clock import utc_now
from banksia.runtime.delegation import settle_delegation_wave
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import WaveMemberSettled
from banksia.runtime.post_commit.delegation_wave_startup import (
    read_wave_continuation_page,
    read_wave_settlement_page,
)
from banksia.runtime.task_control.control import cancel_task, pause_task
from tests.helpers.executor_harness import (
    SessionFactory,
    make_seed_child_terminal,
    seeded_executor,
)
from tests.helpers.lineage_seed import RuntimeIds


@dataclass(frozen=True, slots=True)
class _OpenedWave:
    wave_id: str
    child_dispatch_id: str


@dataclass(frozen=True, slots=True)
class _PausedWaveObservation:
    continuation_source_count: int
    task_status: str
    wave_status: str
    wave_successor_dispatch_id: str | None
    parent_dispatch_id: str | None
    parent_wait_id: str | None


async def test_pause_after_wave_settlement_defers_parent_continuation(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="wave-pause") as (
        executor,
        session_factory,
        ids,
        _activity,
    ):
        async_session_factory = cast(
            Callable[[], AbstractAsyncContextManager[AsyncSession]],
            session_factory,
        )
        opened = await _open_wave_before_pause(
            executor,
            session_factory,
            ids,
        )
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=opened.child_dispatch_id,
            ),
            operation_name="checkpoint",
            arguments={
                "summary": "The child completed before pause.",
                "outcome": "green",
            },
        )
        settlement_page = await read_wave_settlement_page(async_session_factory, None, 10)
        assert settlement_page.sources == (WaveMemberSettled(opened.wave_id),)
        observed = await _settle_pause_and_observe_wave(
            session_factory,
            async_session_factory,
            ids,
            opened.wave_id,
        )

        assert observed.continuation_source_count == 0
        assert observed.task_status == "paused"
        assert observed.wave_status == "settled"
        assert observed.wave_successor_dispatch_id is None
        assert observed.parent_dispatch_id is None
        assert observed.parent_wait_id is None


async def _open_wave_before_pause(
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    ids: RuntimeIds,
) -> _OpenedWave:
    async with session_factory() as session:
        await make_seed_child_terminal(session, ids)
    await executor.execute(
        scope=NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        ),
        operation_name="delegate",
        arguments={
            "assignments": [
                {
                    "child_id": "child",
                    "prompt": "Finish before the operator pause is observed.",
                }
            ]
        },
    )
    async with session_factory() as session:
        wave = await session.scalar(
            select(DelegationWaveModel).where(
                DelegationWaveModel.source_dispatch_id == ids.current_dispatch_id
            )
        )
        assert wave is not None
        member = await session.scalar(
            select(DelegationWaveMemberModel).where(
                DelegationWaveMemberModel.delegation_wave_id == wave.delegation_wave_id
            )
        )
        assert member is not None
        assignment = await session.get(AssignmentModel, member.child_assignment_id)
        assert assignment is not None and assignment.current_attempt_id is not None
        attempt = await session.get(AttemptModel, assignment.current_attempt_id)
    assert attempt is not None and attempt.current_dispatch_id is not None
    return _OpenedWave(wave.delegation_wave_id, attempt.current_dispatch_id)


async def _settle_pause_and_observe_wave(
    session_factory: SessionFactory,
    async_session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    ids: RuntimeIds,
    wave_id: str,
) -> _PausedWaveObservation:
    async with session_factory() as session:
        assert await settle_delegation_wave(
            cast(AsyncSession, session),
            delegation_wave_id=wave_id,
            settled_at=utc_now(),
        )
        task = await session.get(TaskModel, ids.task_id)
        assert task is not None and task.current_team_revision_id is not None
        await pause_task(
            cast(AsyncSession, session),
            ids.task_id,
            expected_team_revision_id=task.current_team_revision_id,
            expected_control_revision=task.control_revision,
        )
    page = await read_wave_continuation_page(
        async_session_factory,
        None,
        10,
    )
    async with session_factory() as session:
        task = await session.get(TaskModel, ids.task_id)
        wave = await session.get(DelegationWaveModel, wave_id)
        attempt = await session.get(AttemptModel, ids.root_attempt_id)
    assert task is not None and wave is not None and attempt is not None
    return _PausedWaveObservation(
        continuation_source_count=len(page.sources),
        task_status=task.status,
        wave_status=wave.status,
        wave_successor_dispatch_id=wave.successor_dispatch_id,
        parent_dispatch_id=attempt.current_dispatch_id,
        parent_wait_id=attempt.current_wait_id,
    )


async def test_task_cancellation_cancels_open_wave_and_prevents_parent_continuation(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="wave-cancel") as (
        executor,
        session_factory,
        ids,
        _activity,
    ):
        async_session_factory = cast(
            Callable[[], AbstractAsyncContextManager[AsyncSession]],
            session_factory,
        )
        async with session_factory() as session:
            await make_seed_child_terminal(session, ids)

        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="delegate",
            arguments={
                "assignments": [
                    {
                        "child_id": "child",
                        "prompt": "This contribution must not outlive task cancellation.",
                    }
                ]
            },
        )
        async with session_factory() as session:
            task = await session.get(TaskModel, ids.task_id)
            wave = await session.scalar(
                select(DelegationWaveModel).where(
                    DelegationWaveModel.source_dispatch_id == ids.current_dispatch_id
                )
            )
            assert task is not None
            assert wave is not None
            await cancel_task(
                cast(AsyncSession, session),
                ids.task_id,
                expected_team_revision_id=ids.team_revision_id,
                expected_control_revision=task.control_revision,
            )

        async with session_factory() as session:
            wave = await session.get(DelegationWaveModel, wave.delegation_wave_id)
            member = await session.scalar(
                select(DelegationWaveMemberModel).where(
                    DelegationWaveMemberModel.delegation_wave_id == wave.delegation_wave_id
                )
            )
            parent_wait = await session.scalar(
                select(AttemptWaitModel).where(
                    AttemptWaitModel.delegation_wave_id == wave.delegation_wave_id
                )
            )
            settlement_page = await read_wave_settlement_page(
                async_session_factory,
                None,
                10,
            )
            continuation_page = await read_wave_continuation_page(
                async_session_factory,
                None,
                10,
            )

        assert wave.status == "cancelled"
        assert wave.successor_dispatch_id is None
        assert member is not None and member.status == "cancelled"
        assert parent_wait is None
    assert settlement_page.sources == ()
    assert continuation_page.sources == ()
