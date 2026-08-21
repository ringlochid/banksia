from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import uuid4

from sqlalchemy import exists, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from oh_my_subagents.persistence.models import TaskModel, TaskStartSourceModel
from oh_my_subagents.runtime.contracts.operation_failure import OperationFailureCode
from oh_my_subagents.runtime.dispatch.currentness import AttemptDispatchConflictError
from oh_my_subagents.runtime.dispatch.opening import (
    StartingDispatchBasis,
    TaskResumeEventBasis,
    stage_starting_dispatch,
)
from oh_my_subagents.runtime.dispatch.ordinary_continuation import publish_dispatch_start_due
from oh_my_subagents.runtime.dispatch.preparation import (
    DispatchOpeningDependencies,
    PreparedDispatchRequest,
    prepare_dispatch_request,
)
from oh_my_subagents.runtime.dispatch.prompt_snapshot import build_root_dispatch_request
from oh_my_subagents.runtime.errors import RuntimeOperationError
from oh_my_subagents.runtime.launch.root_source import (
    RootOpeningSnapshot,
    read_root_opening_snapshot,
    root_context_is_current,
)
from oh_my_subagents.runtime.post_commit import TaskStartCommitted
from oh_my_subagents.runtime.providers import ProviderResolutionError

type TaskStartHandler = Callable[[AsyncSession, TaskStartCommitted], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class TaskStartOpeningResult:
    outcome: Literal["opened", "skipped", "paused"]
    dispatch_id: str | None = None


def create_task_start_handler(
    dependencies: DispatchOpeningDependencies,
) -> TaskStartHandler:
    async def handle(session: AsyncSession, signal: TaskStartCommitted) -> None:
        await open_root_dispatch(session, signal=signal, dependencies=dependencies)

    return handle


async def open_root_dispatch(
    session: AsyncSession,
    *,
    signal: TaskStartCommitted,
    dependencies: DispatchOpeningDependencies,
) -> TaskStartOpeningResult:
    transition_at = dependencies.clock()
    try:
        candidate = await _prepare_root_dispatch(
            session,
            task_id=signal.task_id,
            dependencies=dependencies,
            expected_task_status="running",
            expected_team_revision_id=None,
            expected_control_revision=None,
            due_at=transition_at,
            rollback_before_request=True,
        )
        if candidate is None:
            await session.rollback()
            return TaskStartOpeningResult(outcome="skipped")
        snapshot, prepared = candidate
    except (ProviderResolutionError, ValueError, OSError) as exc:
        await session.rollback()
        failure_code = getattr(exc, "code", "root_dispatch_preparation_failed")
        await _pause_failed_task_start(
            session,
            task_id=signal.task_id,
            paused_at=transition_at,
            failure_code=str(failure_code),
        )
        return TaskStartOpeningResult(outcome="paused")

    if not await _stage_root_dispatch_if_current(
        session,
        snapshot=snapshot,
        prepared=prepared,
        should_commit=True,
        rollback_on_conflict=True,
    ):
        return TaskStartOpeningResult(outcome="skipped")
    publish_dispatch_start_due(dependencies, prepared)
    return TaskStartOpeningResult(outcome="opened", dispatch_id=prepared.dispatch_id)


async def continue_paused_root_dispatch(
    session: AsyncSession,
    *,
    task_id: str,
    expected_team_revision_id: str,
    expected_control_revision: int,
    dependencies: DispatchOpeningDependencies,
    resume_event: TaskResumeEventBasis,
) -> TaskStartOpeningResult:
    """Directly resume one paused, unconsumed Task-start source."""

    try:
        candidate = await _prepare_root_dispatch(
            session,
            task_id=task_id,
            dependencies=dependencies,
            expected_task_status="paused",
            expected_team_revision_id=expected_team_revision_id,
            expected_control_revision=expected_control_revision,
            due_at=dependencies.clock(),
            rollback_before_request=True,
        )
        if candidate is None:
            raise _root_continue_conflict("paused Task start is no longer current")
        snapshot, prepared = candidate
    except RuntimeOperationError:
        await session.rollback()
        raise
    except (ProviderResolutionError, ValueError, OSError) as exc:
        await session.rollback()
        code = str(getattr(exc, "code", "operator_continue_preparation_failed"))
        raise RuntimeOperationError(
            code=OperationFailureCode.ILLEGAL_STATE,
            summary=f"operator continue preparation failed: {code}",
            is_retryable=False,
            suggested_next_step="Repair the exact source or provider route, then retry continue.",
        ) from exc

    if not await _stage_root_dispatch_if_current(
        session,
        snapshot=snapshot,
        prepared=prepared,
        resume_event=resume_event,
        should_commit=True,
        rollback_on_conflict=True,
    ):
        raise _root_continue_conflict("another controller transition won during continue")
    publish_dispatch_start_due(dependencies, prepared)
    return TaskStartOpeningResult(outcome="opened", dispatch_id=prepared.dispatch_id)


async def stage_initial_root_dispatch(
    session: AsyncSession,
    *,
    task_id: str,
    dependencies: DispatchOpeningDependencies,
) -> PreparedDispatchRequest:
    """Stage the first exact Dispatch inside Task admission."""

    candidate = await _prepare_root_dispatch(
        session,
        task_id=task_id,
        dependencies=dependencies,
        expected_task_status="running",
        expected_team_revision_id=None,
        expected_control_revision=None,
        due_at=dependencies.clock(),
        rollback_before_request=False,
    )
    if candidate is None:
        raise RuntimeError("new Task is missing its exact root Dispatch source")
    snapshot, prepared = candidate
    staged = await _stage_root_dispatch_if_current(
        session,
        snapshot=snapshot,
        prepared=prepared,
        should_commit=False,
        rollback_on_conflict=False,
    )
    if not staged:
        raise RuntimeError("new Task root Dispatch source changed during admission")
    return prepared


async def _prepare_root_dispatch(
    session: AsyncSession,
    *,
    task_id: str,
    dependencies: DispatchOpeningDependencies,
    expected_task_status: Literal["running", "paused"],
    expected_team_revision_id: str | None,
    expected_control_revision: int | None,
    due_at: datetime,
    rollback_before_request: bool,
) -> tuple[RootOpeningSnapshot, PreparedDispatchRequest] | None:
    dispatch_id = f"dispatch.{uuid4().hex}"
    snapshot = await read_root_opening_snapshot(
        session,
        task_id=task_id,
        dispatch_id=dispatch_id,
        dependencies=dependencies,
        expected_task_status=expected_task_status,
        expected_team_revision_id=expected_team_revision_id,
        expected_control_revision=expected_control_revision,
    )
    if snapshot is None:
        return None
    request = build_root_dispatch_request(snapshot.prompt, trigger=snapshot.trigger)
    if rollback_before_request:
        await session.rollback()
    prepared = prepare_dispatch_request(
        dependencies=dependencies,
        dispatch_id=dispatch_id,
        due_at=due_at,
        provider=snapshot.provider,
        capabilities=snapshot.capabilities,
        request=request,
    )
    return snapshot, prepared


async def _stage_root_dispatch_if_current(
    session: AsyncSession,
    *,
    snapshot: RootOpeningSnapshot,
    prepared: PreparedDispatchRequest,
    resume_event: TaskResumeEventBasis | None = None,
    should_commit: bool,
    rollback_on_conflict: bool,
) -> bool:
    prompt = snapshot.prompt
    if not await _advance_root_task_state(
        session,
        snapshot=snapshot,
        prepared=prepared,
    ):
        if rollback_on_conflict:
            await session.rollback()
        return False
    if not await _claim_root_dispatch_source(
        session,
        snapshot=snapshot,
        dispatch_id=prepared.dispatch_id,
    ):
        if rollback_on_conflict:
            await session.rollback()
        return False
    try:
        await stage_starting_dispatch(
            session,
            basis=StartingDispatchBasis(
                task_id=prompt.task_id,
                assignment_id=prompt.assignment_id,
                team_revision_id=prompt.team_revision_id,
                member_id=prompt.member_id,
                member_configuration_id=prompt.member_configuration_id,
                member_branch_basis_id=prompt.member_branch_basis_id,
                attempt_id=prompt.attempt_id,
                opened_reason=snapshot.opened_reason,
                predecessor_dispatch_id=None,
                task_start_source_task_id=prompt.task_id,
                resume_event=resume_event,
            ),
            prepared=prepared,
        )
    except AttemptDispatchConflictError:
        if rollback_on_conflict:
            await session.rollback()
        return False
    if should_commit:
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    return True


async def _claim_root_dispatch_source(
    session: AsyncSession,
    *,
    snapshot: RootOpeningSnapshot,
    dispatch_id: str,
) -> bool:
    prompt = snapshot.prompt
    claimed = await session.scalar(
        update(TaskStartSourceModel)
        .where(
            TaskStartSourceModel.task_id == prompt.task_id,
            TaskStartSourceModel.root_assignment_id == prompt.assignment_id,
            TaskStartSourceModel.root_attempt_id == prompt.attempt_id,
            TaskStartSourceModel.successor_dispatch_id.is_(None),
            TaskStartSourceModel.committed_at == snapshot.source_committed_at,
        )
        .values(successor_dispatch_id=dispatch_id)
        .returning(TaskStartSourceModel.task_id)
    )
    return claimed is not None


async def _advance_root_task_state(
    session: AsyncSession,
    *,
    snapshot: RootOpeningSnapshot,
    prepared: PreparedDispatchRequest,
) -> bool:
    prompt = snapshot.prompt
    predicates: list[ColumnElement[bool]] = [
        TaskModel.task_id == prompt.task_id,
        TaskModel.root_assignment_id == prompt.assignment_id,
        TaskModel.status == snapshot.expected_task_status,
        TaskModel.current_team_revision_id == prompt.team_revision_id,
        TaskModel.control_revision == snapshot.task_control_revision,
        root_context_is_current(snapshot),
    ]
    values: dict[str, object] = {"updated_at": TaskModel.updated_at}
    if snapshot.expected_task_status == "paused":
        predicates.append(TaskModel.pause_reason == snapshot.expected_pause_reason)
        values.update(
            status="running",
            pause_reason=None,
            pause_details=None,
            paused_at=None,
            paused_by_actor_ref=None,
            control_revision=TaskModel.control_revision + 1,
            updated_at=prepared.due_at,
        )
    updated_task = await session.scalar(
        update(TaskModel).where(*predicates).values(**values).returning(TaskModel.task_id)
    )
    return updated_task is not None


async def _pause_failed_task_start(
    session: AsyncSession,
    *,
    task_id: str,
    paused_at: datetime,
    failure_code: str,
) -> None:
    source_is_unconsumed = exists().where(
        TaskStartSourceModel.task_id == TaskModel.task_id,
        TaskStartSourceModel.successor_dispatch_id.is_(None),
    )
    await session.execute(
        update(TaskModel)
        .where(
            TaskModel.task_id == task_id,
            TaskModel.status == "running",
            source_is_unconsumed,
        )
        .values(
            status="paused",
            pause_reason="runtime_transition_failed",
            pause_details={"source": "task_start", "failure_code": failure_code},
            paused_at=paused_at,
            paused_by_actor_ref="controller.runtime",
            control_revision=TaskModel.control_revision + 1,
            updated_at=paused_at,
        )
    )
    await session.commit()


def _root_continue_conflict(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary=summary,
        is_retryable=False,
        suggested_next_step="Reread the Task and retry only from the same paused revision.",
        status_code_override=409,
    )


__all__ = [
    "TaskStartHandler",
    "TaskStartOpeningResult",
    "continue_paused_root_dispatch",
    "create_task_start_handler",
    "open_root_dispatch",
    "stage_initial_root_dispatch",
]
