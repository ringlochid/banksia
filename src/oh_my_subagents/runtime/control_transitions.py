from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from oh_my_subagents.persistence.models import AttemptModel, DispatchTurnModel, TaskModel
from oh_my_subagents.runtime.contracts import TaskEventSource, TaskEventType
from oh_my_subagents.runtime.task_events import append_task_event

type _CurrentTaskDispatch = tuple[str, str, str]

_CURRENT_DISPATCH_CHANGED_MESSAGE = "a current Attempt Dispatch changed before Task control"


class TaskDispatchControlConflictError(RuntimeError):
    """A current Dispatch changed during one Task-wide control transaction."""


async def pause_task_for_runtime_transition_failure(
    session: AsyncSession,
    *,
    source_is_current: ColumnElement[bool],
    paused_at: datetime,
    pause_details: dict[str, str],
) -> tuple[str, ...]:
    """Pause an exact failed continuation and settle every runnable sibling lane."""

    row = (
        await session.execute(
            update(TaskModel)
            .where(
                TaskModel.status == "running",
                source_is_current,
            )
            .values(
                status="paused",
                pause_reason="runtime_transition_failed",
                pause_details=pause_details,
                paused_at=paused_at,
                paused_by_actor_ref="controller.runtime",
                control_revision=TaskModel.control_revision + 1,
                updated_at=paused_at,
            )
            .returning(
                TaskModel.task_id,
                TaskModel.current_team_revision_id,
                TaskModel.control_revision,
            )
        )
    ).one_or_none()
    if row is None:
        await session.rollback()
        return ()

    task_id, team_revision_id, control_revision = row
    try:
        closed_dispatch_ids = await close_current_task_dispatches(
            session,
            task_id=task_id,
            closed_reason="paused",
            closed_at=paused_at,
        )
    except TaskDispatchControlConflictError:
        await session.rollback()
        raise
    failure_code = pause_details["failure_code"]
    await append_task_event(
        session,
        task_id=task_id,
        event_type=TaskEventType.TASK_PAUSED,
        event_source=TaskEventSource.CONTROLLER,
        occurred_at=paused_at,
        team_revision_id=team_revision_id,
        actor_ref="controller.runtime",
        payload={
            "pause_reason": "runtime_transition_failed",
            "control_revision": control_revision,
            "actor_ref": "controller.runtime",
            "summary": f"Runtime continuation could not continue: {failure_code}.",
        },
    )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return closed_dispatch_ids


async def close_current_task_dispatches(
    session: AsyncSession,
    *,
    task_id: str,
    closed_reason: str,
    closed_at: datetime,
    reason_overrides: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Close and clear every current runnable Dispatch in one Task transaction."""

    current_dispatches = await _read_current_task_dispatches(session, task_id=task_id)
    closed_ids: list[str] = []
    for current_dispatch in current_dispatches:
        closed_dispatch_id = await _close_current_task_dispatch(
            session,
            task_id=task_id,
            current_dispatch=current_dispatch,
            closed_reason=(
                reason_overrides.get(current_dispatch[2], closed_reason)
                if reason_overrides is not None
                else closed_reason
            ),
            closed_at=closed_at,
        )
        await _clear_attempt_current_dispatch(
            session,
            task_id=task_id,
            current_dispatch=current_dispatch,
        )
        closed_ids.append(closed_dispatch_id)

    await _assert_all_current_task_dispatches_closed(session, task_id=task_id)
    return tuple(closed_ids)


async def _read_current_task_dispatches(
    session: AsyncSession,
    *,
    task_id: str,
) -> tuple[_CurrentTaskDispatch, ...]:
    rows = (
        await session.execute(
            select(
                AttemptModel.assignment_id,
                AttemptModel.attempt_id,
                DispatchTurnModel.dispatch_id,
            )
            .join(
                DispatchTurnModel,
                (DispatchTurnModel.task_id == AttemptModel.task_id)
                & (DispatchTurnModel.assignment_id == AttemptModel.assignment_id)
                & (DispatchTurnModel.attempt_id == AttemptModel.attempt_id)
                & (DispatchTurnModel.dispatch_id == AttemptModel.current_dispatch_id),
            )
            .where(
                AttemptModel.task_id == task_id,
                AttemptModel.status == "running",
                AttemptModel.current_dispatch_id.is_not(None),
                AttemptModel.current_wait_id.is_(None),
                DispatchTurnModel.status.in_(("starting", "open")),
            )
            .order_by(
                AttemptModel.assignment_id,
                AttemptModel.attempt_id,
                DispatchTurnModel.dispatch_id,
            )
        )
    ).all()
    return tuple(
        (assignment_id, attempt_id, dispatch_id) for assignment_id, attempt_id, dispatch_id in rows
    )


async def _close_current_task_dispatch(
    session: AsyncSession,
    *,
    task_id: str,
    current_dispatch: _CurrentTaskDispatch,
    closed_reason: str,
    closed_at: datetime,
) -> str:
    assignment_id, attempt_id, dispatch_id = current_dispatch
    closed_dispatch_id = await session.scalar(
        update(DispatchTurnModel)
        .where(
            DispatchTurnModel.dispatch_id == dispatch_id,
            DispatchTurnModel.task_id == task_id,
            DispatchTurnModel.assignment_id == assignment_id,
            DispatchTurnModel.attempt_id == attempt_id,
            DispatchTurnModel.status.in_(("starting", "open")),
        )
        .values(
            status="closed",
            closed_at=closed_at,
            closed_reason=closed_reason,
            next_provider_start_at=None,
            provider_start_retry_kind=None,
        )
        .returning(DispatchTurnModel.dispatch_id)
    )
    if closed_dispatch_id is None:
        raise TaskDispatchControlConflictError(_CURRENT_DISPATCH_CHANGED_MESSAGE)
    return closed_dispatch_id


async def _clear_attempt_current_dispatch(
    session: AsyncSession,
    *,
    task_id: str,
    current_dispatch: _CurrentTaskDispatch,
) -> None:
    assignment_id, attempt_id, dispatch_id = current_dispatch
    cleared_attempt_id = await session.scalar(
        update(AttemptModel)
        .where(
            AttemptModel.task_id == task_id,
            AttemptModel.assignment_id == assignment_id,
            AttemptModel.attempt_id == attempt_id,
            AttemptModel.status == "running",
            AttemptModel.current_dispatch_id == dispatch_id,
            AttemptModel.current_wait_id.is_(None),
        )
        .values(current_dispatch_id=None)
        .returning(AttemptModel.attempt_id)
    )
    if cleared_attempt_id is None:
        raise TaskDispatchControlConflictError(_CURRENT_DISPATCH_CHANGED_MESSAGE)


async def _assert_all_current_task_dispatches_closed(
    session: AsyncSession,
    *,
    task_id: str,
) -> None:
    unsettled_attempt_id = await session.scalar(
        select(AttemptModel.attempt_id)
        .where(
            AttemptModel.task_id == task_id,
            AttemptModel.status == "running",
            AttemptModel.current_dispatch_id.is_not(None),
        )
        .limit(1)
    )
    if unsettled_attempt_id is not None:
        raise TaskDispatchControlConflictError(
            "Task control did not settle every current Attempt Dispatch"
        )


__all__ = [
    "TaskDispatchControlConflictError",
    "close_current_task_dispatches",
    "pause_task_for_runtime_transition_failure",
]
