from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    AttemptModel,
    AttemptWaitModel,
    CommandRunModel,
    DispatchTurnModel,
    HumanRequestModel,
    TaskEventModel,
    TaskModel,
    TaskStartSourceModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.clock import utc_now
from banksia.runtime.contracts import HumanRequestResolveRequest
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.human_request.service import resolve_human_request
from banksia.runtime.launch.persistence.runtime import persist_bootstrap_runtime_from_precomputed
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    CommandRunCancellationRequested,
    DispatchStartDue,
    HumanRequestTerminal,
)
from banksia.runtime.task_control.service import (
    cancel_runtime_task,
    continue_runtime_task,
    pause_runtime_task,
)
from tests.helpers.executor_harness import (
    make_seed_child_terminal,
    seeded_executor,
)
from tests.helpers.launch_foundation import (
    build_launch_foundation_input,
    build_launch_foundation_workflow_revision,
    seed_launch_foundation_workflow,
)
from tests.helpers.lineage_seed import RuntimeIds
from tests.helpers.sqlite_runtime import (
    SyncSessionAdapter,
    create_runtime_schema_engine,
)


async def test_resume_opens_every_runnable_attempt_lane_in_one_task_transition(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="task-resume-multi") as (
        _,
        session_factory,
        ids,
        _,
    ):
        async with session_factory() as session:
            await _activate_seed_child_lane(session, ids)
            task = await session.get(TaskModel, ids.task_id)
            assert task is not None
            paused = await pause_runtime_task(
                cast(AsyncSession, session),
                ids.task_id,
                expected_team_revision_id=ids.team_revision_id,
                expected_control_revision=task.control_revision,
            )

        async with session_factory() as session:
            resumed = await continue_runtime_task(
                cast(AsyncSession, session),
                ids.task_id,
                expected_team_revision_id=ids.team_revision_id,
                expected_control_revision=paused.task.control_revision,
                dependencies=_opening_dependencies(publisher),
            )
            root_attempt = await session.get(AttemptModel, ids.root_attempt_id)
            child_attempt = await session.get(AttemptModel, ids.child_attempt_id)
            successors = tuple(
                await session.scalars(
                    select(DispatchTurnModel).where(
                        DispatchTurnModel.predecessor_dispatch_id.in_(
                            (ids.current_dispatch_id, ids.child_dispatch_id)
                        )
                    )
                )
            )
            resumed_event_count = await session.scalar(
                select(func.count())
                .select_from(TaskEventModel)
                .where(TaskEventModel.event_type == "task_resumed")
            )

    assert resumed.status.value == "running"
    assert resumed.control_revision == paused.task.control_revision + 1
    assert root_attempt is not None and root_attempt.current_dispatch_id is not None
    assert child_attempt is not None and child_attempt.current_dispatch_id is not None
    assert {
        root_attempt.current_dispatch_id,
        child_attempt.current_dispatch_id,
    } == {dispatch.dispatch_id for dispatch in successors}
    assert {
        (dispatch.assignment_id, dispatch.predecessor_dispatch_id) for dispatch in successors
    } == {
        (ids.root_assignment_id, ids.current_dispatch_id),
        (ids.child_assignment_id, ids.child_dispatch_id),
    }
    assert resumed_event_count == 1
    assert len(publisher.signals) == 2
    assert all(isinstance(signal, DispatchStartDue) for signal in publisher.signals)


async def test_resume_retains_an_unresolved_wait_then_consumes_its_terminal_source_once(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="task-resume-human") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        request_id = await _open_human_request(executor, ids)
        async with session_factory() as session:
            await _activate_seed_child_lane(session, ids)
            task = await session.get(TaskModel, ids.task_id)
            assert task is not None
            first_pause = await pause_runtime_task(
                cast(AsyncSession, session),
                ids.task_id,
                expected_team_revision_id=ids.team_revision_id,
                expected_control_revision=task.control_revision,
            )

        async with session_factory() as session:
            first_resume = await continue_runtime_task(
                cast(AsyncSession, session),
                ids.task_id,
                expected_team_revision_id=ids.team_revision_id,
                expected_control_revision=first_pause.task.control_revision,
                dependencies=_opening_dependencies(publisher),
            )
            root_attempt = await session.get(AttemptModel, ids.root_attempt_id)
            child_attempt = await session.get(AttemptModel, ids.child_attempt_id)
            request = await session.get(HumanRequestModel, request_id)
            assert root_attempt is not None and root_attempt.current_wait_id is not None
            assert root_attempt.current_dispatch_id is None
            assert child_attempt is not None and child_attempt.current_dispatch_id is not None
            assert request is not None and request.status == "open"

            second_pause = await pause_runtime_task(
                cast(AsyncSession, session),
                ids.task_id,
                expected_team_revision_id=ids.team_revision_id,
                expected_control_revision=first_resume.control_revision,
            )
            await resolve_human_request(
                cast(AsyncSession, session),
                task_id=ids.task_id,
                request_id=request_id,
                request=HumanRequestResolveRequest.model_validate(
                    {
                        "item_responses": {
                            "direction": {
                                "kind": "option",
                                "option_id": "a",
                            }
                        }
                    }
                ),
            )
            resumed = await continue_runtime_task(
                cast(AsyncSession, session),
                ids.task_id,
                expected_team_revision_id=ids.team_revision_id,
                expected_control_revision=second_pause.task.control_revision,
                dependencies=_opening_dependencies(publisher),
            )
            source = await session.get(HumanRequestModel, request_id)
            root_attempt = await session.get(
                AttemptModel,
                ids.root_attempt_id,
                populate_existing=True,
            )
            child_attempt = await session.get(
                AttemptModel,
                ids.child_attempt_id,
                populate_existing=True,
            )
            assert source is not None and source.successor_dispatch_id is not None
            human_successor_id = source.successor_dispatch_id
            human_successor = await session.get(
                DispatchTurnModel,
                human_successor_id,
            )
            dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )
            with pytest.raises(RuntimeOperationError) as duplicate:
                await continue_runtime_task(
                    cast(AsyncSession, session),
                    ids.task_id,
                    expected_team_revision_id=ids.team_revision_id,
                    expected_control_revision=second_pause.task.control_revision,
                    dependencies=_opening_dependencies(publisher),
                )
            current_source = await session.get(
                HumanRequestModel,
                request_id,
                populate_existing=True,
            )
            final_dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )

    assert resumed.status.value == "running"
    assert root_attempt is not None and root_attempt.current_wait_id is None
    assert root_attempt.current_dispatch_id == human_successor_id
    assert child_attempt is not None and child_attempt.current_dispatch_id is not None
    assert human_successor is not None and human_successor.opened_reason == "human_result"
    assert duplicate.value.code == OperationFailureCode.CONFLICT
    assert current_source is not None
    assert current_source.successor_dispatch_id == human_successor_id
    assert final_dispatch_count == dispatch_count


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
            await persist_bootstrap_runtime_from_precomputed(async_session, bootstrap_input)
            task = await session.get(TaskModel, bootstrap_input.task_id)
            assert task is not None and task.current_team_revision_id is not None
            task.status = "paused"
            task.pause_reason = "runtime_transition_failed"
            task.pause_details = {"source": "task_start"}
            task.paused_at = utc_now()
            task.paused_by_actor_ref = "controller.runtime"
            task.control_revision += 1
            await session.commit()
            expected_team_revision_id = task.current_team_revision_id
            expected_control_revision = task.control_revision

            with pytest.raises(RuntimeOperationError) as preparation_failure:
                await continue_runtime_task(
                    async_session,
                    task.task_id,
                    expected_team_revision_id=expected_team_revision_id,
                    expected_control_revision=expected_control_revision,
                    dependencies=DispatchOpeningDependencies.create(
                        settings=Settings(),
                        available_adapter_kinds={ProviderKind.CODEX},
                        post_commit_publisher=CapturedRuntimeEffectPublisher(),
                    ),
                )
            failed_task = await session.get(
                TaskModel,
                task.task_id,
                populate_existing=True,
            )
            failed_source = await session.scalar(select(TaskStartSourceModel))
            failed_dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )
            failed_status = failed_task.status if failed_task is not None else None
            failed_control_revision = (
                failed_task.control_revision if failed_task is not None else None
            )
            failed_source_successor = (
                failed_source.successor_dispatch_id if failed_source is not None else None
            )

            publisher = CapturedRuntimeEffectPublisher()
            resumed = await continue_runtime_task(
                async_session,
                task.task_id,
                expected_team_revision_id=expected_team_revision_id,
                expected_control_revision=expected_control_revision,
                dependencies=_opening_dependencies(publisher),
            )
            source = await session.scalar(select(TaskStartSourceModel))
            attempt = await session.scalar(select(AttemptModel))
            assert attempt is not None and attempt.current_dispatch_id is not None
            successor = await session.get(
                DispatchTurnModel,
                attempt.current_dispatch_id,
            )
    finally:
        engine.dispose()

    assert preparation_failure.value.code == OperationFailureCode.ILLEGAL_STATE
    assert failed_status == "paused"
    assert failed_control_revision == expected_control_revision
    assert failed_source is not None and failed_source_successor is None
    assert failed_dispatch_count == 0
    assert resumed.status.value == "running"
    assert resumed.control_revision == expected_control_revision + 1
    assert successor is not None
    assert source is not None and source.successor_dispatch_id == successor.dispatch_id
    assert successor.opened_reason == "operator_continue"
    assert successor.predecessor_dispatch_id is None
    assert successor.task_start_source_task_id == bootstrap_input.task_id
    assert len(publisher.signals) == 1
    start_signal = publisher.signals[0]
    assert isinstance(start_signal, DispatchStartDue)
    assert start_signal.dispatch_id == successor.dispatch_id
    assert start_signal.provider_start_revision == successor.provider_start_revision
    assert start_signal.due_at == successor.next_provider_start_at


async def test_cancel_beats_stale_resume_and_settles_human_and_command_waits(
    tmp_path: Path,
) -> None:
    human_publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="task-cancel-human") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        async with session_factory() as session:
            await make_seed_child_terminal(session, ids)
        request_id = await _open_human_request(executor, ids)
        async with session_factory() as session:
            task = await session.get(TaskModel, ids.task_id)
            assert task is not None
            paused = await pause_runtime_task(
                cast(AsyncSession, session),
                ids.task_id,
                expected_team_revision_id=ids.team_revision_id,
                expected_control_revision=task.control_revision,
            )
            cancelled = await cancel_runtime_task(
                cast(AsyncSession, session),
                ids.task_id,
                expected_team_revision_id=ids.team_revision_id,
                expected_control_revision=paused.task.control_revision,
                runtime_effect_publisher=human_publisher,
            )
            with pytest.raises(RuntimeOperationError) as stale_resume:
                await continue_runtime_task(
                    cast(AsyncSession, session),
                    ids.task_id,
                    expected_team_revision_id=ids.team_revision_id,
                    expected_control_revision=paused.task.control_revision,
                    dependencies=_opening_dependencies(human_publisher),
                )
            request = await session.get(HumanRequestModel, request_id)
            wait = await session.scalar(
                select(AttemptWaitModel).where(AttemptWaitModel.human_request_id == request_id)
            )

    assert cancelled.status.value == "cancelled"
    assert stale_resume.value.code == OperationFailureCode.CONFLICT
    assert request is not None and request.status == "cancelled"
    assert request.resolution_kind == "cancelled"
    assert wait is None
    assert human_publisher.signals == (HumanRequestTerminal(request_id=request_id),)
    assert not any(isinstance(signal, DispatchStartDue) for signal in human_publisher.signals)

    command_publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="task-cancel-command") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        async with session_factory() as session:
            await make_seed_child_terminal(session, ids)
        run_id = await _open_command_run(executor, ids)
        async with session_factory() as session:
            task = await session.get(TaskModel, ids.task_id)
            assert task is not None
            await cancel_runtime_task(
                cast(AsyncSession, session),
                ids.task_id,
                expected_team_revision_id=ids.team_revision_id,
                expected_control_revision=task.control_revision,
                runtime_effect_publisher=command_publisher,
            )
            command = await session.get(CommandRunModel, run_id)
            wait = await session.scalar(
                select(AttemptWaitModel).where(AttemptWaitModel.command_run_id == run_id)
            )

    assert command is not None and command.state == "cancellation_requested"
    assert wait is None
    assert command_publisher.signals == (
        CommandRunCancellationRequested(
            run_id=run_id,
            ownership_revision=command.ownership_revision,
        ),
    )


async def _activate_seed_child_lane(
    session: AsyncSession | SyncSessionAdapter,
    ids: RuntimeIds,
) -> None:
    child_attempt = await session.get(AttemptModel, ids.child_attempt_id)
    child_dispatch = await session.get(DispatchTurnModel, ids.child_dispatch_id)
    assert child_attempt is not None
    assert child_dispatch is not None
    child_attempt.current_dispatch_id = child_dispatch.dispatch_id
    child_dispatch.status = "open"
    child_dispatch.closed_at = None
    child_dispatch.closed_reason = None
    await session.commit()


async def _open_human_request(
    executor: NodeOperationExecutor,
    ids: RuntimeIds,
) -> str:
    opened = await executor.execute(
        scope=NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        ),
        operation_name="open_human_request",
        arguments={
            "request": {
                "kind": "direction",
                "summary": "Choose one exact direction.",
                "items": [
                    {
                        "id": "direction",
                        "prompt": "Which direction?",
                        "options": [
                            {"id": "a", "title": "A"},
                            {"id": "b", "title": "B"},
                        ],
                    }
                ],
            }
        },
    )
    return cast(str, opened.model_dump()["request_id"])


async def _open_command_run(
    executor: NodeOperationExecutor,
    ids: RuntimeIds,
) -> str:
    opened = await executor.execute(
        scope=NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        ),
        operation_name="start_command_run",
        arguments={
            "request": {
                "command": {"kind": "argv", "argv": ["python", "-V"]},
                "summary": "Read the Python version.",
            }
        },
    )
    return cast(str, opened.model_dump()["command_id"])


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
