from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AttemptModel,
    AttemptWaitModel,
    CommandRunModel,
    DispatchTurnModel,
    HumanRequestModel,
    TaskEventModel,
    TaskModel,
)
from banksia.runtime.contracts import HumanRequestResolveRequest
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.human_request.service import resolve_human_request
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
from tests.helpers.disjoint_team_runtime import create_runtime_opening_dependencies
from tests.helpers.executor_harness import (
    SessionFactory,
    make_seed_child_terminal,
    seeded_executor,
)
from tests.helpers.lineage_seed import RuntimeIds
from tests.helpers.sqlite_runtime import SyncSessionAdapter


@dataclass(frozen=True, slots=True)
class _UnresolvedResumeObservation:
    control_revision: int
    root_wait_id: str | None
    root_dispatch_id: str | None
    child_dispatch_id: str | None
    request_status: str


@dataclass(frozen=True, slots=True)
class _TerminalResumeObservation:
    task_status: str
    human_successor_id: str
    attempt_state: tuple[str | None, str | None, str | None]
    successor_reason: str
    duplicate_failure_code: OperationFailureCode
    persisted_source_successor_id: str | None
    dispatch_counts: tuple[int, int]


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
        unresolved = await _pause_resume_with_unresolved_human_wait(
            session_factory,
            ids,
            request_id,
            publisher,
        )
        assert unresolved.root_wait_id is not None
        assert unresolved.root_dispatch_id is None
        assert unresolved.child_dispatch_id is not None
        assert unresolved.request_status == "open"
        terminal = await _resolve_human_wait_and_resume_once(
            session_factory,
            ids,
            request_id,
            unresolved.control_revision,
            publisher,
        )

    assert terminal.task_status == "running"
    root_wait_id, root_dispatch_id, child_dispatch_id = terminal.attempt_state
    assert root_wait_id is None
    assert root_dispatch_id == terminal.human_successor_id
    assert child_dispatch_id is not None
    assert terminal.successor_reason == "human_result"
    assert terminal.duplicate_failure_code == OperationFailureCode.CONFLICT
    assert terminal.persisted_source_successor_id == terminal.human_successor_id
    assert terminal.dispatch_counts[1] == terminal.dispatch_counts[0]


async def _pause_resume_with_unresolved_human_wait(
    session_factory: SessionFactory,
    ids: RuntimeIds,
    request_id: str,
    publisher: CapturedRuntimeEffectPublisher,
) -> _UnresolvedResumeObservation:
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
        root = await session.get(AttemptModel, ids.root_attempt_id)
        child = await session.get(AttemptModel, ids.child_attempt_id)
        request = await session.get(HumanRequestModel, request_id)
    assert root is not None
    assert child is not None
    assert request is not None
    return _UnresolvedResumeObservation(
        control_revision=resumed.control_revision,
        root_wait_id=root.current_wait_id,
        root_dispatch_id=root.current_dispatch_id,
        child_dispatch_id=child.current_dispatch_id,
        request_status=request.status,
    )


async def _resolve_human_wait_and_resume_once(
    session_factory: SessionFactory,
    ids: RuntimeIds,
    request_id: str,
    control_revision: int,
    publisher: CapturedRuntimeEffectPublisher,
) -> _TerminalResumeObservation:
    async with session_factory() as session:
        paused = await pause_runtime_task(
            cast(AsyncSession, session),
            ids.task_id,
            expected_team_revision_id=ids.team_revision_id,
            expected_control_revision=control_revision,
        )
        await resolve_human_request(
            cast(AsyncSession, session),
            task_id=ids.task_id,
            request_id=request_id,
            request=HumanRequestResolveRequest.model_validate(
                {"item_responses": {"direction": {"kind": "option", "option_id": "a"}}}
            ),
        )
        resumed = await continue_runtime_task(
            cast(AsyncSession, session),
            ids.task_id,
            expected_team_revision_id=ids.team_revision_id,
            expected_control_revision=paused.task.control_revision,
            dependencies=_opening_dependencies(publisher),
        )
        source = await session.get(HumanRequestModel, request_id)
        root = await session.get(AttemptModel, ids.root_attempt_id, populate_existing=True)
        child = await session.get(
            AttemptModel,
            ids.child_attempt_id,
            populate_existing=True,
        )
        assert source is not None and source.successor_dispatch_id is not None
        successor = await session.get(DispatchTurnModel, source.successor_dispatch_id)
        dispatch_count = await _dispatch_count(session)
        with pytest.raises(RuntimeOperationError) as duplicate:
            await continue_runtime_task(
                cast(AsyncSession, session),
                ids.task_id,
                expected_team_revision_id=ids.team_revision_id,
                expected_control_revision=paused.task.control_revision,
                dependencies=_opening_dependencies(publisher),
            )
        current_source = await session.get(
            HumanRequestModel,
            request_id,
            populate_existing=True,
        )
        final_dispatch_count = await _dispatch_count(session)
    assert root is not None and child is not None
    assert successor is not None and current_source is not None
    return _TerminalResumeObservation(
        task_status=resumed.status.value,
        human_successor_id=source.successor_dispatch_id,
        attempt_state=(
            root.current_wait_id,
            root.current_dispatch_id,
            child.current_dispatch_id,
        ),
        successor_reason=successor.opened_reason,
        duplicate_failure_code=duplicate.value.code,
        persisted_source_successor_id=current_source.successor_dispatch_id,
        dispatch_counts=(dispatch_count, final_dispatch_count),
    )


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


async def _dispatch_count(session: AsyncSession | SyncSessionAdapter) -> int:
    return int(await session.scalar(select(func.count()).select_from(DispatchTurnModel)) or 0)


def _opening_dependencies(
    publisher: CapturedRuntimeEffectPublisher,
) -> DispatchOpeningDependencies:
    return create_runtime_opening_dependencies(publisher=publisher)


__all__ = []
