from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
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
from banksia.runtime.node_operations import NodeOperationScope
from banksia.runtime.post_commit import WaveMemberSettled
from banksia.runtime.post_commit.delegation_wave_startup import (
    read_wave_continuation_page,
    read_wave_settlement_page,
)
from banksia.runtime.task_control.control import cancel_task, pause_task
from tests.helpers.executor_harness import make_seed_child_terminal, seeded_executor


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
            child_dispatch_id = attempt.current_dispatch_id

        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=child_dispatch_id,
            ),
            operation_name="checkpoint",
            arguments={
                "summary": "The child completed before pause.",
                "outcome": "green",
            },
        )
        settlement_page = await read_wave_settlement_page(async_session_factory, None, 10)
        assert settlement_page.sources == (WaveMemberSettled(wave.delegation_wave_id),)
        async with session_factory() as session:
            assert await settle_delegation_wave(
                cast(AsyncSession, session),
                delegation_wave_id=wave.delegation_wave_id,
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
        continuation_page = await read_wave_continuation_page(
            async_session_factory,
            None,
            10,
        )
        async with session_factory() as session:
            task = await session.get(TaskModel, ids.task_id)
            persisted_wave = await session.get(
                DelegationWaveModel,
                wave.delegation_wave_id,
            )
            parent_attempt = await session.get(AttemptModel, ids.root_attempt_id)

        assert continuation_page.sources == ()
        assert task is not None and task.status == "paused"
        assert persisted_wave is not None and persisted_wave.status == "settled"
        assert persisted_wave.successor_dispatch_id is None
        assert parent_attempt is not None
        assert parent_attempt.current_dispatch_id is None
        assert parent_attempt.current_wait_id is None


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
