"""Task pause, resume, and cancel transitions."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload
from sqlalchemy.sql.elements import ColumnElement

from oh_my_subagents.persistence.models import ReplanTransitionModel, TaskModel
from oh_my_subagents.runtime.clock import utc_now
from oh_my_subagents.runtime.contracts import TaskEventSource, TaskEventType
from oh_my_subagents.runtime.contracts.operation_failure import OperationFailureCode
from oh_my_subagents.runtime.control_transitions import (
    TaskDispatchControlConflictError,
    close_current_task_dispatches,
)
from oh_my_subagents.runtime.dispatch.opening import TaskResumeEventBasis
from oh_my_subagents.runtime.dispatch.preparation import DispatchOpeningDependencies
from oh_my_subagents.runtime.errors import (
    RuntimeOperationError,
    missing_resource_error,
    stale_team_revision_error,
)
from oh_my_subagents.runtime.post_commit import (
    CommandRunCancellationRequested,
    DispatchCleanupRequested,
    HumanRequestTerminal,
    RuntimeEffectPublisher,
    RuntimeEffectSignal,
)
from oh_my_subagents.runtime.task_control.cancellation import (
    cancel_attempt_waits,
    cancel_execution_rows,
)
from oh_my_subagents.runtime.task_control.continuation import continue_paused_task
from oh_my_subagents.runtime.task_control.contracts import (
    ControllerTaskPauseResult,
    ControllerTaskState,
)
from oh_my_subagents.runtime.task_control.reads import read_runtime_task
from oh_my_subagents.runtime.task_events import append_task_event
from oh_my_subagents.runtime.workspace.availability import task_workspace_is_available

logger = logging.getLogger(__name__)


async def pause_task(
    session: AsyncSession,
    task_id: str,
    *,
    expected_team_revision_id: str,
    expected_control_revision: int,
    actor_ref: str | None = None,
    event_source: TaskEventSource = TaskEventSource.CONTROL_API,
    runtime_effect_publisher: RuntimeEffectPublisher | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> ControllerTaskPauseResult:
    """Pause one exact running Task while retaining any external wait."""

    task = await _read_control_task(session, task_id)
    _require_control_snapshot(
        task,
        expected_team_revision_id=expected_team_revision_id,
        expected_control_revision=expected_control_revision,
        allowed_statuses={"running"},
    )
    paused_at = clock()
    changed = await _update_task_to_paused(
        session,
        task=task,
        expected_control_revision=expected_control_revision,
        actor_ref=actor_ref,
        paused_at=paused_at,
    )
    if not changed:
        await session.rollback()
        raise _task_control_conflict("another controller transition won before pause")
    try:
        closed_dispatch_ids = await close_current_task_dispatches(
            session,
            task_id=task.task_id,
            closed_reason="paused",
            closed_at=paused_at,
        )
    except TaskDispatchControlConflictError as exc:
        await session.rollback()
        raise _task_control_conflict(str(exc)) from exc
    await append_task_event(
        session,
        task_id=task.task_id,
        event_type=TaskEventType.TASK_PAUSED,
        event_source=event_source,
        occurred_at=paused_at,
        team_revision_id=expected_team_revision_id,
        actor_ref=actor_ref,
        payload={
            "pause_reason": "paused_by_operator",
            "control_revision": expected_control_revision + 1,
            "actor_ref": actor_ref,
            "summary": "Paused by operator.",
        },
    )
    await _commit_or_rollback(session)
    _publish_cleanups(runtime_effect_publisher, closed_dispatch_ids)
    return ControllerTaskPauseResult(task=await read_runtime_task(session, task_id))


async def continue_task(
    session: AsyncSession,
    task_id: str,
    *,
    expected_team_revision_id: str,
    expected_control_revision: int,
    dependencies: DispatchOpeningDependencies,
    actor_ref: str | None = None,
    event_source: TaskEventSource = TaskEventSource.CONTROL_API,
) -> ControllerTaskState:
    """Resume every runnable Attempt lane from one exact paused Task snapshot."""

    task = await _read_control_task(session, task_id)
    _require_control_snapshot(
        task,
        expected_team_revision_id=expected_team_revision_id,
        expected_control_revision=expected_control_revision,
        allowed_statuses={"paused"},
    )
    if task.pause_reason == "provider_retired":
        raise _task_control_conflict(
            "the current Team selects retired provider OpenClaw and cannot be resumed"
        )
    if not await asyncio.to_thread(
        task_workspace_is_available,
        Path(task.task_root_path),
        task_id=task.task_id,
    ):
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="The Task workspace is unavailable and the run cannot be resumed.",
            is_retryable=False,
            suggested_next_step=(
                "Restore or remount the original workspace, then reread the Task before resuming."
            ),
        )
    await continue_paused_task(
        session,
        task_id=task_id,
        expected_team_revision_id=expected_team_revision_id,
        expected_control_revision=expected_control_revision,
        dependencies=dependencies,
        resume_event=TaskResumeEventBasis(
            control_revision=expected_control_revision + 1,
            actor_ref=actor_ref,
            event_source=event_source,
        ),
    )
    return await read_runtime_task(session, task_id)


async def cancel_task(
    session: AsyncSession,
    task_id: str,
    *,
    expected_team_revision_id: str,
    expected_control_revision: int,
    actor_ref: str | None = None,
    event_source: TaskEventSource = TaskEventSource.CONTROL_API,
    runtime_effect_publisher: RuntimeEffectPublisher | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> ControllerTaskState:
    """Cancel one exact nonterminal Task without opening a successor."""

    task = await _read_control_task(session, task_id)
    _require_control_snapshot(
        task,
        expected_team_revision_id=expected_team_revision_id,
        expected_control_revision=expected_control_revision,
        allowed_statuses={"running", "paused"},
    )
    cancelled_at = clock()
    changed = await _update_task_to_cancelled(
        session,
        task=task,
        expected_control_revision=expected_control_revision,
        cancelled_at=cancelled_at,
    )
    if not changed:
        await session.rollback()
        raise _task_control_conflict("another controller transition won before cancellation")
    try:
        closed_dispatch_ids = await close_current_task_dispatches(
            session,
            task_id=task.task_id,
            closed_reason="cancelled",
            closed_at=cancelled_at,
        )
    except TaskDispatchControlConflictError as exc:
        await session.rollback()
        raise _task_control_conflict(str(exc)) from exc
    cancellation_signals = await cancel_attempt_waits(
        session,
        task=task,
        actor_ref=actor_ref,
        event_source=event_source,
        cancelled_at=cancelled_at,
    )
    await cancel_execution_rows(session, task=task, cancelled_at=cancelled_at)
    await _cancel_pending_replan_transition(
        session,
        task=task,
        cancelled_at=cancelled_at,
    )
    await append_task_event(
        session,
        task_id=task.task_id,
        event_type=TaskEventType.TASK_CANCELLED,
        event_source=event_source,
        occurred_at=cancelled_at,
        team_revision_id=expected_team_revision_id,
        actor_ref=actor_ref,
        payload={
            "control_revision": expected_control_revision + 1,
            "actor_ref": actor_ref,
            "summary": "Cancelled by operator.",
        },
    )
    await _commit_or_rollback(session)
    _publish_cleanups(runtime_effect_publisher, closed_dispatch_ids)
    for human_signal in cancellation_signals.human:
        _publish_human_terminal(runtime_effect_publisher, human_signal)
    for command_signal in cancellation_signals.command:
        _publish_command_cancellation(runtime_effect_publisher, command_signal)
    return await read_runtime_task(session, task_id)


async def _read_control_task(session: AsyncSession, task_id: str) -> TaskModel:
    task = await session.scalar(
        select(TaskModel)
        .options(raiseload("*"))
        .where(TaskModel.task_id == task_id)
        .execution_options(populate_existing=True)
    )
    if task is None:
        raise missing_resource_error(f"unknown task_id '{task_id}'")
    return task


def _require_control_snapshot(
    task: TaskModel,
    *,
    expected_team_revision_id: str,
    expected_control_revision: int,
    allowed_statuses: set[str],
) -> None:
    if task.current_team_revision_id != expected_team_revision_id:
        raise stale_team_revision_error("the current Team revision changed before control")
    if task.control_revision != expected_control_revision:
        raise _task_control_conflict("the Task control revision changed before control")
    if task.status not in allowed_statuses:
        raise _task_control_conflict(f"Task cannot be controlled from status '{task.status}'")


async def _update_task_to_paused(
    session: AsyncSession,
    *,
    task: TaskModel,
    expected_control_revision: int,
    actor_ref: str | None,
    paused_at: datetime,
) -> bool:
    return bool(
        await session.scalar(
            update(TaskModel)
            .where(*_task_snapshot_conditions(task, expected_control_revision))
            .values(
                status="paused",
                pause_reason="paused_by_operator",
                pause_details={"summary": "Paused by operator."},
                paused_at=paused_at,
                paused_by_actor_ref=actor_ref,
                control_revision=TaskModel.control_revision + 1,
                updated_at=paused_at,
            )
            .returning(TaskModel.task_id)
        )
    )


async def _update_task_to_cancelled(
    session: AsyncSession,
    *,
    task: TaskModel,
    expected_control_revision: int,
    cancelled_at: datetime,
) -> bool:
    return bool(
        await session.scalar(
            update(TaskModel)
            .where(*_task_snapshot_conditions(task, expected_control_revision))
            .values(
                status="cancelled",
                terminal_outcome=None,
                result_boundary_id=None,
                pause_reason=None,
                pause_details=None,
                paused_at=None,
                paused_by_actor_ref=None,
                control_revision=TaskModel.control_revision + 1,
                updated_at=cancelled_at,
            )
            .returning(TaskModel.task_id)
        )
    )


async def _cancel_pending_replan_transition(
    session: AsyncSession,
    *,
    task: TaskModel,
    cancelled_at: datetime,
) -> None:
    await session.execute(
        update(ReplanTransitionModel)
        .where(
            ReplanTransitionModel.task_id == task.task_id,
            ReplanTransitionModel.successor_team_revision_id == task.current_team_revision_id,
            ReplanTransitionModel.successor_state.not_in(("opened", "cancelled")),
            ReplanTransitionModel.successor_dispatch_id.is_(None),
        )
        .values(
            successor_state="cancelled",
            failure_code=case(
                (
                    ReplanTransitionModel.manifest_state == "repair_required",
                    ReplanTransitionModel.failure_code,
                ),
                else_=None,
            ),
            failure_detail=case(
                (
                    ReplanTransitionModel.manifest_state == "repair_required",
                    ReplanTransitionModel.failure_detail,
                ),
                else_=None,
            ),
            updated_at=cancelled_at,
        )
    )


def _task_snapshot_conditions(
    task: TaskModel,
    expected_control_revision: int,
) -> tuple[ColumnElement[bool], ...]:
    return (
        TaskModel.task_id == task.task_id,
        TaskModel.status == task.status,
        TaskModel.current_team_revision_id == task.current_team_revision_id,
        TaskModel.control_revision == expected_control_revision,
    )


async def _commit_or_rollback(session: AsyncSession) -> None:
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise


def _publish_cleanups(
    publisher: RuntimeEffectPublisher | None,
    dispatch_ids: tuple[str, ...],
) -> None:
    if publisher is None:
        return
    for dispatch_id in dispatch_ids:
        _publish_effect(publisher, DispatchCleanupRequested(dispatch_id=dispatch_id))


def _publish_command_cancellation(
    publisher: RuntimeEffectPublisher | None,
    signal: CommandRunCancellationRequested | None,
) -> None:
    if publisher is None or signal is None:
        return
    _publish_effect(publisher, signal)


def _publish_human_terminal(
    publisher: RuntimeEffectPublisher | None,
    signal: HumanRequestTerminal | None,
) -> None:
    if publisher is None or signal is None:
        return
    _publish_effect(publisher, signal)


def _publish_effect(publisher: RuntimeEffectPublisher, signal: RuntimeEffectSignal) -> None:
    try:
        publisher.publish(signal)
    except Exception:
        logger.exception("post-commit Task-control signal publication failed")


def _task_control_conflict(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary=summary,
        is_retryable=False,
        suggested_next_step="Reread the Task and retry only against its current revisions.",
    )


__all__ = ["cancel_task", "continue_task", "pause_task"]
