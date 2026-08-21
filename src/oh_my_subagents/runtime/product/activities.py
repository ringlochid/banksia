from __future__ import annotations

from collections.abc import Iterable
from typing import NamedTuple

from sqlalchemy import Select, case, func, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.persistence.models import (
    AcceptedBoundaryModel,
    CommandRunModel,
    HumanRequestModel,
    TaskEventModel,
    TaskModel,
    TaskStartSourceModel,
)
from oh_my_subagents.runtime.contracts.primitives import TaskEventType
from oh_my_subagents.runtime.contracts.task import TaskActivity, TaskActivityPage
from oh_my_subagents.runtime.contracts.task_events import TaskEventRecord
from oh_my_subagents.runtime.product.activity_projection import project_canonical_activity_rows
from oh_my_subagents.runtime.task_events import (
    TaskEventCursorResetRequiredError,
    decode_task_event_cursor,
    encode_task_event_cursor,
)

_ACTIVITY_EVENT_TYPES = (
    TaskEventType.TASK_STARTED.value,
    TaskEventType.TASK_PAUSED.value,
    TaskEventType.TASK_RESUMED.value,
    TaskEventType.TASK_CANCELLED.value,
    TaskEventType.BOUNDARY_ACCEPTED.value,
    TaskEventType.HUMAN_REQUEST_OPENED.value,
    TaskEventType.HUMAN_REQUEST_RESOLVED.value,
    TaskEventType.HUMAN_REQUEST_TIMED_OUT.value,
    TaskEventType.HUMAN_REQUEST_CANCELLED.value,
    TaskEventType.COMMAND_RUN_OPENED.value,
    TaskEventType.COMMAND_RUN_SUCCEEDED.value,
    TaskEventType.COMMAND_RUN_FAILED.value,
    TaskEventType.COMMAND_RUN_TIMED_OUT.value,
    TaskEventType.COMMAND_RUN_CANCELLED.value,
    TaskEventType.COMMAND_RUN_ABANDONED.value,
    TaskEventType.MEMBER_STEERED.value,
)
_CONTROL_EVENT_TYPES = (
    TaskEventType.TASK_PAUSED.value,
    TaskEventType.TASK_RESUMED.value,
    TaskEventType.TASK_CANCELLED.value,
)
_HUMAN_TERMINAL_EVENT_TYPES = (
    TaskEventType.HUMAN_REQUEST_RESOLVED.value,
    TaskEventType.HUMAN_REQUEST_TIMED_OUT.value,
    TaskEventType.HUMAN_REQUEST_CANCELLED.value,
)
_COMMAND_TERMINAL_EVENT_TYPES = (
    TaskEventType.COMMAND_RUN_SUCCEEDED.value,
    TaskEventType.COMMAND_RUN_FAILED.value,
    TaskEventType.COMMAND_RUN_TIMED_OUT.value,
    TaskEventType.COMMAND_RUN_CANCELLED.value,
    TaskEventType.COMMAND_RUN_ABANDONED.value,
)


class RecentTaskActivities(NamedTuple):
    items: tuple[TaskActivity, ...]
    is_truncated: bool


async def list_task_activities(
    session: AsyncSession,
    *,
    task_id: str,
    cursor: str | None = None,
    limit: int = 50,
) -> TaskActivityPage:
    """Read one keyset page of canonical source-backed Activity."""

    if not 1 <= limit <= 200:
        raise ValueError("activity limit must be between 1 and 200")
    start_after_seq = await _activity_cursor_sequence(
        session,
        task_id=task_id,
        cursor=cursor,
    )
    rows = list(
        await session.scalars(
            _canonical_activity_statement(task_id=task_id)
            .where(TaskEventModel.event_seq > start_after_seq)
            .order_by(TaskEventModel.event_seq.asc())
            .limit(limit + 1)
        )
    )
    page_rows = rows[:limit]
    activities = await project_canonical_activity_rows(session, page_rows)
    return TaskActivityPage(
        items=activities,
        next_cursor=(
            encode_task_event_cursor(page_rows[-1].event_id)
            if len(rows) > limit and page_rows
            else None
        ),
    )


async def list_recent_task_activities(
    session: AsyncSession,
    *,
    task_id: str,
    limit: int = 20,
) -> RecentTaskActivities:
    if not 1 <= limit <= 100:
        raise ValueError("recent Activity limit must be between 1 and 100")
    rows = list(
        await session.scalars(
            _canonical_activity_statement(task_id=task_id)
            .order_by(TaskEventModel.event_seq.desc())
            .limit(limit + 1)
        )
    )
    page_rows = rows[:limit]
    projected = await project_canonical_activity_rows(session, page_rows)
    return RecentTaskActivities(
        items=tuple(reversed(projected)),
        is_truncated=len(rows) > limit,
    )


async def project_task_event(
    session: AsyncSession,
    event: TaskEventRecord,
) -> TaskActivity | None:
    projected = await project_task_events(session, (event,))
    return projected.get(event.event_id)


async def project_task_events(
    session: AsyncSession,
    events: Iterable[TaskEventRecord],
) -> dict[str, TaskActivity]:
    """Batch-project only records that remain canonical for their source truth."""

    records = tuple(events)
    if not records:
        return {}
    task_ids = {event.task_id for event in records}
    if len(task_ids) != 1:
        raise ValueError("Activity projection requires events from one Task")
    task_id = next(iter(task_ids))
    event_sequences = tuple(event.event_seq for event in records)
    canonical_rows = tuple(
        await session.scalars(
            _canonical_activity_statement(task_id=task_id).where(
                TaskEventModel.event_seq.in_(event_sequences)
            )
        )
    )
    projected = await project_canonical_activity_rows(session, canonical_rows)
    return {decode_task_event_cursor(activity.id): activity for activity in projected}


def _canonical_activity_statement(*, task_id: str) -> Select[tuple[TaskEventModel]]:
    canonical_sequences = union_all(
        _task_started_sequences(task_id),
        _task_control_sequences(task_id),
        _boundary_sequences(task_id),
        _human_opened_sequences(task_id),
        _human_terminal_sequences(task_id),
        _command_opened_sequences(task_id),
        _command_terminal_sequences(task_id),
        _member_steered_sequences(task_id),
    ).subquery()
    return select(TaskEventModel).where(
        TaskEventModel.task_id == task_id,
        TaskEventModel.event_type.in_(_ACTIVITY_EVENT_TYPES),
        TaskEventModel.event_seq.in_(select(canonical_sequences.c.event_seq)),
    )


def _task_started_sequences(task_id: str) -> Select[tuple[int]]:
    return (
        select(func.min(TaskEventModel.event_seq).label("event_seq"))
        .join(
            TaskStartSourceModel,
            TaskStartSourceModel.task_id == TaskEventModel.task_id,
        )
        .where(
            TaskEventModel.task_id == task_id,
            TaskEventModel.event_type == TaskEventType.TASK_STARTED.value,
        )
        .group_by(TaskEventModel.task_id)
    )


def _member_steered_sequences(task_id: str) -> Select[tuple[int]]:
    return select(TaskEventModel.event_seq).where(
        TaskEventModel.task_id == task_id,
        TaskEventModel.event_type == TaskEventType.MEMBER_STEERED.value,
    )


def _task_control_sequences(task_id: str) -> Select[tuple[int]]:
    control_revision = TaskEventModel.payload["control_revision"].as_integer()
    return (
        select(func.min(TaskEventModel.event_seq).label("event_seq"))
        .join(TaskModel, TaskModel.task_id == TaskEventModel.task_id)
        .where(
            TaskEventModel.task_id == task_id,
            TaskEventModel.event_type.in_(_CONTROL_EVENT_TYPES),
            control_revision.is_not(None),
            control_revision <= TaskModel.control_revision,
        )
        .group_by(control_revision)
    )


def _boundary_sequences(task_id: str) -> Select[tuple[int]]:
    return (
        select(func.min(TaskEventModel.event_seq).label("event_seq"))
        .join(
            AcceptedBoundaryModel,
            (AcceptedBoundaryModel.task_id == TaskEventModel.task_id)
            & (AcceptedBoundaryModel.source_dispatch_id == TaskEventModel.dispatch_id)
            & (AcceptedBoundaryModel.attempt_id == TaskEventModel.attempt_id)
            & (AcceptedBoundaryModel.committed_at == TaskEventModel.occurred_at),
        )
        .join(TaskModel, TaskModel.task_id == AcceptedBoundaryModel.task_id)
        .where(
            TaskEventModel.task_id == task_id,
            TaskEventModel.event_type == TaskEventType.BOUNDARY_ACCEPTED.value,
            AcceptedBoundaryModel.outcome.in_(("green", "blocked")),
            or_(
                AcceptedBoundaryModel.assignment_id != TaskModel.root_assignment_id,
                TaskModel.result_boundary_id == AcceptedBoundaryModel.accepted_boundary_id,
            ),
        )
        .group_by(AcceptedBoundaryModel.source_dispatch_id)
    )


def _human_opened_sequences(task_id: str) -> Select[tuple[int]]:
    return (
        select(func.min(TaskEventModel.event_seq).label("event_seq"))
        .join(
            HumanRequestModel,
            (HumanRequestModel.task_id == TaskEventModel.task_id)
            & (HumanRequestModel.source_dispatch_id == TaskEventModel.dispatch_id)
            & (HumanRequestModel.attempt_id == TaskEventModel.attempt_id),
        )
        .where(
            TaskEventModel.task_id == task_id,
            TaskEventModel.event_type == TaskEventType.HUMAN_REQUEST_OPENED.value,
        )
        .group_by(HumanRequestModel.source_dispatch_id)
    )


def _human_terminal_sequences(task_id: str) -> Select[tuple[int]]:
    expected_event_type = case(
        (HumanRequestModel.status == "resolved", TaskEventType.HUMAN_REQUEST_RESOLVED.value),
        (HumanRequestModel.status == "timed_out", TaskEventType.HUMAN_REQUEST_TIMED_OUT.value),
        (HumanRequestModel.status == "cancelled", TaskEventType.HUMAN_REQUEST_CANCELLED.value),
        else_="",
    )
    return (
        select(func.min(TaskEventModel.event_seq).label("event_seq"))
        .join(
            HumanRequestModel,
            (HumanRequestModel.task_id == TaskEventModel.task_id)
            & (HumanRequestModel.source_dispatch_id == TaskEventModel.dispatch_id)
            & (HumanRequestModel.attempt_id == TaskEventModel.attempt_id)
            & (HumanRequestModel.resolved_at == TaskEventModel.occurred_at),
        )
        .where(
            TaskEventModel.task_id == task_id,
            TaskEventModel.event_type.in_(_HUMAN_TERMINAL_EVENT_TYPES),
            TaskEventModel.event_type == expected_event_type,
        )
        .group_by(HumanRequestModel.source_dispatch_id)
    )


def _command_opened_sequences(task_id: str) -> Select[tuple[int]]:
    return (
        select(func.min(TaskEventModel.event_seq).label("event_seq"))
        .join(
            CommandRunModel,
            (CommandRunModel.task_id == TaskEventModel.task_id)
            & (CommandRunModel.source_dispatch_id == TaskEventModel.dispatch_id)
            & (CommandRunModel.attempt_id == TaskEventModel.attempt_id),
        )
        .where(
            TaskEventModel.task_id == task_id,
            TaskEventModel.event_type == TaskEventType.COMMAND_RUN_OPENED.value,
        )
        .group_by(CommandRunModel.source_dispatch_id)
    )


def _command_terminal_sequences(task_id: str) -> Select[tuple[int]]:
    expected_event_type = case(
        (CommandRunModel.state == "succeeded", TaskEventType.COMMAND_RUN_SUCCEEDED.value),
        (CommandRunModel.state == "failed", TaskEventType.COMMAND_RUN_FAILED.value),
        (CommandRunModel.state == "timed_out", TaskEventType.COMMAND_RUN_TIMED_OUT.value),
        (CommandRunModel.state == "cancelled", TaskEventType.COMMAND_RUN_CANCELLED.value),
        (CommandRunModel.state == "abandoned", TaskEventType.COMMAND_RUN_ABANDONED.value),
        else_="",
    )
    return (
        select(func.min(TaskEventModel.event_seq).label("event_seq"))
        .join(
            CommandRunModel,
            (CommandRunModel.task_id == TaskEventModel.task_id)
            & (CommandRunModel.source_dispatch_id == TaskEventModel.dispatch_id)
            & (CommandRunModel.attempt_id == TaskEventModel.attempt_id)
            & (CommandRunModel.ended_at == TaskEventModel.occurred_at),
        )
        .where(
            TaskEventModel.task_id == task_id,
            TaskEventModel.event_type.in_(_COMMAND_TERMINAL_EVENT_TYPES),
            TaskEventModel.event_type == expected_event_type,
        )
        .group_by(CommandRunModel.source_dispatch_id)
    )


async def _activity_cursor_sequence(
    session: AsyncSession,
    *,
    task_id: str,
    cursor: str | None,
) -> int:
    if cursor is None:
        return 0
    event_id = decode_task_event_cursor(cursor)
    event_seq = await session.scalar(
        select(TaskEventModel.event_seq).where(
            TaskEventModel.task_id == task_id,
            TaskEventModel.event_id == event_id,
        )
    )
    if event_seq is None:
        raise TaskEventCursorResetRequiredError(cursor)
    return event_seq


__all__ = [
    "RecentTaskActivities",
    "list_recent_task_activities",
    "list_task_activities",
    "project_task_event",
    "project_task_events",
]
