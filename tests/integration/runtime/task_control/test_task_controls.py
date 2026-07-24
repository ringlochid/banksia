from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import AttemptModel, DispatchTurnModel, TaskEventModel, TaskModel
from banksia.providers import ProviderKind
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    DispatchCleanupRequested,
    DispatchStartDue,
)
from banksia.runtime.task_control.service import (
    cancel_runtime_task,
    continue_runtime_task,
    list_runtime_tasks,
    pause_runtime_task,
    runtime_task_read,
)
from tests.helpers.executor_harness import make_seed_child_terminal, seeded_executor


async def test_task_reads_do_not_manufacture_singular_lane_authority(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="task-read") as (
        _,
        session_factory,
        ids,
        _,
    ):
        async with session_factory() as session:
            task = await runtime_task_read(cast(AsyncSession, session), ids.task_id)
            page = await list_runtime_tasks(cast(AsyncSession, session))

    task_fields = set(task.model_dump(mode="json"))
    summary_fields = set(page.items[0].model_dump(mode="json"))
    lane_fields = {
        "active_assignment_id",
        "active_attempt_id",
        "current_dispatch",
        "current_member_id",
        "current_plan",
        "latest_dispatch_id",
        "waiting_cause",
        "watchdog_recovery_count",
    }
    assert task.status.value == "running"
    assert task.current_team_revision_id == ids.team_revision_id
    assert len(page.items) == 1 and page.items[0].task_id == ids.task_id
    assert lane_fields.isdisjoint(task_fields)
    assert lane_fields.isdisjoint(summary_fields)


async def test_pause_closes_every_current_dispatch_with_one_task_cas(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="task-pause-multi") as (
        _,
        session_factory,
        ids,
        _,
    ):
        async with session_factory() as session:
            child_attempt = await session.get(AttemptModel, ids.child_attempt_id)
            child_dispatch = await session.get(DispatchTurnModel, ids.child_dispatch_id)
            task = await session.get(TaskModel, ids.task_id)
            assert child_attempt is not None
            assert child_dispatch is not None
            assert task is not None
            child_attempt.current_dispatch_id = child_dispatch.dispatch_id
            child_dispatch.status = "open"
            child_dispatch.closed_at = None
            child_dispatch.closed_reason = None
            await session.commit()

        async with session_factory() as session:
            response = await pause_runtime_task(
                cast(AsyncSession, session),
                ids.task_id,
                expected_team_revision_id=ids.team_revision_id,
                expected_control_revision=task.control_revision,
                actor_ref="operator.test",
                runtime_effect_publisher=publisher,
            )
            dispatches = tuple(
                await session.scalars(
                    select(DispatchTurnModel).where(
                        DispatchTurnModel.dispatch_id.in_(
                            (ids.current_dispatch_id, ids.child_dispatch_id)
                        )
                    )
                )
            )
            event = await session.scalar(
                select(TaskEventModel).where(TaskEventModel.event_type == "task_paused")
            )

    assert response.task.status.value == "paused"
    assert response.task.control_revision == task.control_revision + 1
    assert {row.closed_reason for row in dispatches} == {"paused"}
    assert event is not None and event.actor_ref == "operator.test"
    assert set(publisher.signals) == {
        DispatchCleanupRequested(dispatch_id=ids.current_dispatch_id),
        DispatchCleanupRequested(dispatch_id=ids.child_dispatch_id),
    }


async def test_pause_rejects_a_stale_task_control_revision(tmp_path: Path) -> None:
    async with seeded_executor(tmp_path, suffix="task-pause-stale") as (
        _,
        session_factory,
        ids,
        _,
    ):
        async with session_factory() as session:
            task = await session.get(TaskModel, ids.task_id)
            assert task is not None
            await pause_runtime_task(
                cast(AsyncSession, session),
                ids.task_id,
                expected_team_revision_id=ids.team_revision_id,
                expected_control_revision=task.control_revision,
            )
            with pytest.raises(RuntimeOperationError) as stale:
                await pause_runtime_task(
                    cast(AsyncSession, session),
                    ids.task_id,
                    expected_team_revision_id=ids.team_revision_id,
                    expected_control_revision=task.control_revision,
                )

    assert stale.value.code == OperationFailureCode.CONFLICT


async def test_continue_opens_one_exact_successor_for_the_live_root_lane(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="task-continue") as (
        _,
        session_factory,
        ids,
        _,
    ):
        async with session_factory() as session:
            await make_seed_child_terminal(session, ids)
        async with session_factory() as session:
            task = await session.get(TaskModel, ids.task_id)
            assert task is not None
            paused = await pause_runtime_task(
                cast(AsyncSession, session),
                ids.task_id,
                expected_team_revision_id=ids.team_revision_id,
                expected_control_revision=task.control_revision,
                runtime_effect_publisher=publisher,
            )
            resumed = await continue_runtime_task(
                cast(AsyncSession, session),
                ids.task_id,
                expected_team_revision_id=ids.team_revision_id,
                expected_control_revision=paused.task.control_revision,
                dependencies=_opening_dependencies(publisher),
            )
            current_dispatch_id = await session.scalar(
                select(AttemptModel.current_dispatch_id).where(
                    AttemptModel.attempt_id == ids.root_attempt_id
                )
            )
            successor = await session.get(DispatchTurnModel, current_dispatch_id)

    assert resumed.status.value == "running"
    assert resumed.control_revision == paused.task.control_revision + 1
    assert successor is not None and successor.opened_reason == "operator_continue"
    assert successor.predecessor_dispatch_id == ids.current_dispatch_id
    assert isinstance(publisher.signals[-1], DispatchStartDue)


async def test_cancel_closes_task_authority_without_opening_a_successor(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="task-cancel") as (
        _,
        session_factory,
        ids,
        _,
    ):
        async with session_factory() as session:
            task = await session.get(TaskModel, ids.task_id)
            assert task is not None
            dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )
            response = await cancel_runtime_task(
                cast(AsyncSession, session),
                ids.task_id,
                expected_team_revision_id=ids.team_revision_id,
                expected_control_revision=task.control_revision,
                actor_ref="operator.test",
                runtime_effect_publisher=publisher,
            )
            active_attempts = await session.scalar(
                select(func.count())
                .select_from(AttemptModel)
                .where(AttemptModel.status.in_(("pending", "running")))
            )
            final_dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )

    assert response.status.value == "cancelled"
    assert active_attempts == 0
    assert final_dispatch_count == dispatch_count
    assert publisher.signals == (DispatchCleanupRequested(dispatch_id=ids.current_dispatch_id),)


def _opening_dependencies(
    publisher: CapturedRuntimeEffectPublisher,
) -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=publisher,
    )


__all__ = []
