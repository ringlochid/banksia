from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    AttemptModel,
    DispatchTurnModel,
    TaskEventModel,
    TaskModel,
    TaskStartSourceModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.clock import utc_now
from banksia.runtime.contracts import RuntimeBootstrapInput
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.launch.persistence.runtime import persist_bootstrap_runtime_from_precomputed
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
from tests.helpers.launch_foundation import (
    build_launch_foundation_input,
    build_launch_foundation_workflow_revision,
    seed_launch_foundation_workflow,
)
from tests.helpers.sqlite_runtime import (
    SyncSessionAdapter,
    create_runtime_schema_engine,
)


@dataclass(frozen=True, slots=True)
class _PreRootFailureObservation:
    failure_code: OperationFailureCode
    task_state: tuple[str | None, int | None]
    source_state: tuple[bool, str | None]
    dispatch_count: int


@dataclass(frozen=True, slots=True)
class _PreRootResumeObservation:
    task_state: tuple[str, int]
    source_successor_id: str | None
    successor: tuple[str, str, str | None, str | None]
    provider_start: tuple[int, datetime]


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


async def test_pre_root_resume_is_atomic_on_failure_and_consumes_task_start_once(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path, name="pre-root-task-resume.sqlite")
    workflow_revision = build_launch_foundation_workflow_revision()
    bootstrap_input = build_launch_foundation_input(
        tmp_path,
        workflow_revision=workflow_revision,
    )
    with engine.begin() as connection:
        seed_launch_foundation_workflow(
            connection,
            workflow_revision=workflow_revision,
        )
    sync_factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with SyncSessionAdapter(sync_factory) as session:
            async_session = cast(AsyncSession, session)
            (
                expected_team_revision_id,
                expected_control_revision,
            ) = await _persist_paused_pre_root_task(session, bootstrap_input)
            failure = await _attempt_invalid_pre_root_resume(
                session,
                async_session,
                bootstrap_input.task_id,
                expected_team_revision_id,
                expected_control_revision,
            )
            publisher = CapturedRuntimeEffectPublisher()
            resumed = await _resume_pre_root_task(
                session,
                async_session,
                bootstrap_input.task_id,
                expected_team_revision_id,
                expected_control_revision,
                publisher,
            )
    finally:
        engine.dispose()

    assert failure.failure_code == OperationFailureCode.ILLEGAL_STATE
    assert failure.task_state == ("paused", expected_control_revision)
    assert failure.source_state == (True, None)
    assert failure.dispatch_count == 0
    assert resumed.task_state == ("running", expected_control_revision + 1)
    successor_id, reason, predecessor_id, task_start_id = resumed.successor
    assert resumed.source_successor_id == successor_id
    assert (reason, predecessor_id, task_start_id) == (
        "operator_continue",
        None,
        bootstrap_input.task_id,
    )
    assert len(publisher.signals) == 1
    start_signal = publisher.signals[0]
    assert isinstance(start_signal, DispatchStartDue)
    assert start_signal.dispatch_id == successor_id
    assert (start_signal.provider_start_revision, start_signal.due_at) == (resumed.provider_start)


async def _persist_paused_pre_root_task(
    session: SyncSessionAdapter,
    bootstrap_input: RuntimeBootstrapInput,
) -> tuple[str, int]:
    await persist_bootstrap_runtime_from_precomputed(
        cast(AsyncSession, session),
        bootstrap_input,
    )
    task = await session.get(TaskModel, bootstrap_input.task_id)
    assert task is not None and task.current_team_revision_id is not None
    task.status = "paused"
    task.pause_reason = "runtime_transition_failed"
    task.pause_details = {"source": "task_start"}
    task.paused_at = utc_now()
    task.paused_by_actor_ref = "controller.runtime"
    task.control_revision += 1
    await session.commit()
    return task.current_team_revision_id, task.control_revision


async def _attempt_invalid_pre_root_resume(
    session: SyncSessionAdapter,
    async_session: AsyncSession,
    task_id: str,
    team_revision_id: str,
    control_revision: int,
) -> _PreRootFailureObservation:
    with pytest.raises(RuntimeOperationError) as failure:
        await continue_runtime_task(
            async_session,
            task_id,
            expected_team_revision_id=team_revision_id,
            expected_control_revision=control_revision,
            dependencies=DispatchOpeningDependencies.create(
                settings=Settings(),
                available_adapter_kinds={ProviderKind.CODEX},
                post_commit_publisher=CapturedRuntimeEffectPublisher(),
            ),
        )
    task = await session.get(TaskModel, task_id, populate_existing=True)
    source = await session.scalar(select(TaskStartSourceModel))
    return _PreRootFailureObservation(
        failure_code=failure.value.code,
        task_state=(
            task.status if task is not None else None,
            task.control_revision if task is not None else None,
        ),
        source_state=(
            source is not None,
            source.successor_dispatch_id if source is not None else None,
        ),
        dispatch_count=int(
            await session.scalar(select(func.count()).select_from(DispatchTurnModel)) or 0
        ),
    )


async def _resume_pre_root_task(
    session: SyncSessionAdapter,
    async_session: AsyncSession,
    task_id: str,
    team_revision_id: str,
    control_revision: int,
    publisher: CapturedRuntimeEffectPublisher,
) -> _PreRootResumeObservation:
    task = await continue_runtime_task(
        async_session,
        task_id,
        expected_team_revision_id=team_revision_id,
        expected_control_revision=control_revision,
        dependencies=_opening_dependencies(publisher),
    )
    source = await session.scalar(select(TaskStartSourceModel))
    attempt = await session.scalar(select(AttemptModel))
    assert source is not None
    assert attempt is not None and attempt.current_dispatch_id is not None
    successor = await session.get(DispatchTurnModel, attempt.current_dispatch_id)
    assert successor is not None
    return _PreRootResumeObservation(
        task_state=(task.status.value, task.control_revision),
        source_successor_id=source.successor_dispatch_id,
        successor=(
            successor.dispatch_id,
            successor.opened_reason,
            successor.predecessor_dispatch_id,
            successor.task_start_source_task_id,
        ),
        provider_start=(
            successor.provider_start_revision,
            successor.next_provider_start_at,
        ),
    )


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
