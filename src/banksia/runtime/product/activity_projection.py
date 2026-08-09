from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import NamedTuple, cast

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AttemptCheckpointModel,
    CheckpointFileReferenceModel,
    CommandRunModel,
    HumanRequestModel,
    TaskEventModel,
    TaskModel,
)
from banksia.runtime.contracts.primitives import TaskEventType
from banksia.runtime.contracts.refs import FileReference
from banksia.runtime.contracts.task import (
    TaskActivity,
    TaskActivityKind,
    TaskActivityLink,
    TaskActivityOutcome,
    TaskMemberReference,
)
from banksia.runtime.contracts.task_event_payloads import MemberSteeredEventPayload
from banksia.runtime.contracts.task_events import TaskEventRecord
from banksia.runtime.product.paths import build_product_api_path
from banksia.runtime.product.presenters import read_source_member_references
from banksia.runtime.task_events import encode_task_event_cursor, task_event_record_from_model


class _ActivitySources(NamedTuple):
    human: dict[str, HumanRequestModel]
    command: dict[str, CommandRunModel]
    boundary: dict[str, tuple[AcceptedBoundaryModel, AttemptCheckpointModel]]
    checkpoint_files: dict[str, tuple[FileReference, ...]]
    members: dict[str, TaskMemberReference]
    root_assignment_id: str | None


async def project_canonical_activity_rows(
    session: AsyncSession,
    rows: Iterable[TaskEventModel],
) -> tuple[TaskActivity, ...]:
    event_rows = tuple(rows)
    if not event_rows:
        return ()
    task_id = event_rows[0].task_id
    source_dispatch_ids = tuple(
        dict.fromkeys(row.dispatch_id for row in event_rows if row.dispatch_id is not None)
    )
    sources = await _read_activity_sources(
        session,
        task_id=task_id,
        source_dispatch_ids=source_dispatch_ids,
    )
    activities: list[TaskActivity] = []
    for row in event_rows:
        try:
            record = task_event_record_from_model(row)
        except ValidationError:
            continue
        source_dispatch_id = row.dispatch_id
        activity = _project_activity_record(
            record,
            human=(
                sources.human.get(source_dispatch_id) if source_dispatch_id is not None else None
            ),
            command=(
                sources.command.get(source_dispatch_id) if source_dispatch_id is not None else None
            ),
            boundary=(
                sources.boundary.get(source_dispatch_id) if source_dispatch_id is not None else None
            ),
            checkpoint_files=sources.checkpoint_files,
            member=(
                sources.members.get(source_dispatch_id) if source_dispatch_id is not None else None
            ),
            root_assignment_id=sources.root_assignment_id,
        )
        if activity is not None:
            activities.append(activity)
    return tuple(activities)


async def _read_activity_sources(
    session: AsyncSession,
    *,
    task_id: str,
    source_dispatch_ids: tuple[str, ...],
) -> _ActivitySources:
    human = {
        source.source_dispatch_id: source
        for source in await session.scalars(
            select(HumanRequestModel).where(
                HumanRequestModel.task_id == task_id,
                HumanRequestModel.source_dispatch_id.in_(source_dispatch_ids),
            )
        )
    }
    command = {
        source.source_dispatch_id: source
        for source in await session.scalars(
            select(CommandRunModel).where(
                CommandRunModel.task_id == task_id,
                CommandRunModel.source_dispatch_id.in_(source_dispatch_ids),
            )
        )
    }
    boundary_rows = tuple(
        await session.execute(
            select(AcceptedBoundaryModel, AttemptCheckpointModel)
            .join(
                AttemptCheckpointModel,
                AttemptCheckpointModel.checkpoint_id == AcceptedBoundaryModel.checkpoint_id,
            )
            .where(
                AcceptedBoundaryModel.task_id == task_id,
                AcceptedBoundaryModel.source_dispatch_id.in_(source_dispatch_ids),
            )
        )
    )
    boundary = {
        accepted.source_dispatch_id: (accepted, checkpoint)
        for accepted, checkpoint in boundary_rows
    }
    checkpoint_files = await _read_checkpoint_files(
        session,
        checkpoint_ids=tuple(checkpoint.checkpoint_id for _accepted, checkpoint in boundary_rows),
    )
    members = await read_source_member_references(
        session,
        task_id=task_id,
        source_dispatch_ids=source_dispatch_ids,
    )
    root_assignment_id = await session.scalar(
        select(TaskModel.root_assignment_id).where(TaskModel.task_id == task_id)
    )
    return _ActivitySources(
        human=human,
        command=command,
        boundary=boundary,
        checkpoint_files=checkpoint_files,
        members=members,
        root_assignment_id=root_assignment_id,
    )


def _project_activity_record(
    event: TaskEventRecord,
    *,
    human: HumanRequestModel | None,
    command: CommandRunModel | None,
    boundary: tuple[AcceptedBoundaryModel, AttemptCheckpointModel] | None,
    checkpoint_files: dict[str, tuple[FileReference, ...]],
    member: TaskMemberReference | None,
    root_assignment_id: str | None,
) -> TaskActivity | None:
    if event.event_type in {
        TaskEventType.TASK_STARTED,
        TaskEventType.TASK_PAUSED,
        TaskEventType.TASK_RESUMED,
        TaskEventType.TASK_CANCELLED,
    }:
        return _project_task_activity(event)
    if event.event_type == TaskEventType.BOUNDARY_ACCEPTED and boundary is not None:
        return _project_boundary_activity(
            event,
            boundary=boundary,
            checkpoint_files=checkpoint_files,
            member=member,
            root_assignment_id=root_assignment_id,
        )
    if event.event_type == TaskEventType.MEMBER_STEERED:
        payload = cast(MemberSteeredEventPayload, event.payload)
        return TaskActivity(
            id=encode_task_event_cursor(event.event_id),
            kind="member_steered",
            occurred_at=event.occurred_at,
            title="Member steered",
            summary=payload.message,
            member=member,
        )
    if human is not None:
        return _project_human_activity(event, human=human, member=member)
    if command is not None:
        return _project_command_activity(event, command=command, member=member)
    return None


def _project_task_activity(event: TaskEventRecord) -> TaskActivity:
    activity_id = encode_task_event_cursor(event.event_id)
    if event.event_type == TaskEventType.TASK_STARTED:
        return TaskActivity(
            id=activity_id,
            kind="task_started",
            occurred_at=event.occurred_at,
            title="Run started",
        )
    if event.event_type == TaskEventType.TASK_PAUSED:
        return TaskActivity(
            id=activity_id,
            kind="task_paused",
            occurred_at=event.occurred_at,
            title="Run paused",
        )
    if event.event_type == TaskEventType.TASK_RESUMED:
        return TaskActivity(
            id=activity_id,
            kind="task_resumed",
            occurred_at=event.occurred_at,
            title="Run resumed",
        )
    return TaskActivity(
        id=activity_id,
        kind="task_cancelled",
        occurred_at=event.occurred_at,
        title="Run cancelled",
        outcome="cancelled",
    )


def _project_boundary_activity(
    event: TaskEventRecord,
    *,
    boundary: tuple[AcceptedBoundaryModel, AttemptCheckpointModel],
    checkpoint_files: dict[str, tuple[FileReference, ...]],
    member: TaskMemberReference | None,
    root_assignment_id: str | None,
) -> TaskActivity:
    accepted, checkpoint = boundary
    is_root = accepted.assignment_id == root_assignment_id
    if is_root:
        kind: TaskActivityKind = (
            "task_blocked" if accepted.outcome == "blocked" else "task_completed"
        )
        title = "Run blocked" if accepted.outcome == "blocked" else "Run completed"
    else:
        kind = "work_blocked" if accepted.outcome == "blocked" else "work_completed"
        title = "Work blocked" if accepted.outcome == "blocked" else "Work completed"
    return TaskActivity(
        id=encode_task_event_cursor(event.event_id),
        kind=kind,
        occurred_at=accepted.committed_at,
        title=title,
        # The exact root Checkpoint already owns the singular Result surface.
        # The terminal Activity records only that the boundary occurred; copying
        # the Result body here made one answer appear repeatedly in Run Studio.
        summary=None if is_root else checkpoint.summary,
        member=member,
        outcome="blocked" if accepted.outcome == "blocked" else "completed",
        files=() if is_root else checkpoint_files.get(checkpoint.checkpoint_id, ()),
    )


def _project_human_activity(
    event: TaskEventRecord,
    *,
    human: HumanRequestModel,
    member: TaskMemberReference | None,
) -> TaskActivity | None:
    activity_id = encode_task_event_cursor(event.event_id)
    if event.event_type == TaskEventType.HUMAN_REQUEST_OPENED:
        return TaskActivity(
            id=activity_id,
            kind="input_requested",
            occurred_at=human.opened_at,
            title="Input requested",
            summary=human.request_summary,
            member=member,
            action=TaskActivityLink(
                label="Respond",
                href=build_product_api_path(
                    f"/tasks/{event.task_id}/human-requests/{human.request_id}"
                ),
            ),
        )
    mapping: dict[TaskEventType, tuple[TaskActivityKind, str, TaskActivityOutcome]] = {
        TaskEventType.HUMAN_REQUEST_RESOLVED: (
            "input_received",
            "Input received",
            "completed",
        ),
        TaskEventType.HUMAN_REQUEST_TIMED_OUT: (
            "input_expired",
            "Input request expired",
            "failed",
        ),
        TaskEventType.HUMAN_REQUEST_CANCELLED: (
            "input_cancelled",
            "Input request cancelled",
            "cancelled",
        ),
    }
    presentation = mapping.get(event.event_type)
    if presentation is None:
        return None
    kind, title, outcome = presentation
    return TaskActivity(
        id=activity_id,
        kind=kind,
        occurred_at=cast(datetime, human.resolved_at),
        title=title,
        summary=(
            None
            if event.event_type == TaskEventType.HUMAN_REQUEST_RESOLVED
            else human.resolution_summary
        ),
        member=member,
        outcome=outcome,
    )


def _project_command_activity(
    event: TaskEventRecord,
    *,
    command: CommandRunModel,
    member: TaskMemberReference | None,
) -> TaskActivity | None:
    activity_id = encode_task_event_cursor(event.event_id)
    if event.event_type == TaskEventType.COMMAND_RUN_OPENED:
        return TaskActivity(
            id=activity_id,
            kind="action_started",
            occurred_at=command.created_at,
            title="Action started",
            summary=command.summary,
            member=member,
            action=TaskActivityLink(
                label="View action",
                href=build_product_api_path(
                    f"/tasks/{event.task_id}/command-runs/{command.run_id}"
                ),
            ),
        )
    mapping: dict[TaskEventType, tuple[TaskActivityKind, str, TaskActivityOutcome]] = {
        TaskEventType.COMMAND_RUN_SUCCEEDED: (
            "action_succeeded",
            "Action succeeded",
            "completed",
        ),
        TaskEventType.COMMAND_RUN_FAILED: ("action_failed", "Action failed", "failed"),
        TaskEventType.COMMAND_RUN_TIMED_OUT: (
            "action_timed_out",
            "Action timed out",
            "failed",
        ),
        TaskEventType.COMMAND_RUN_CANCELLED: (
            "action_cancelled",
            "Action cancelled",
            "cancelled",
        ),
        TaskEventType.COMMAND_RUN_ABANDONED: (
            "action_failed",
            "Action could not be completed",
            "failed",
        ),
    }
    presentation = mapping.get(event.event_type)
    if presentation is None:
        return None
    kind, title, outcome = presentation
    return TaskActivity(
        id=activity_id,
        kind=kind,
        occurred_at=cast(datetime, command.ended_at),
        title=title,
        summary=command.terminal_summary,
        member=member,
        outcome=outcome,
        action=TaskActivityLink(
            label="View output",
            href=build_product_api_path(
                f"/tasks/{event.task_id}/command-runs/{command.run_id}/output"
            ),
        ),
    )


async def _read_checkpoint_files(
    session: AsyncSession,
    *,
    checkpoint_ids: tuple[str, ...],
) -> dict[str, tuple[FileReference, ...]]:
    if not checkpoint_ids:
        return {}
    rows = await session.scalars(
        select(CheckpointFileReferenceModel)
        .where(CheckpointFileReferenceModel.checkpoint_id.in_(checkpoint_ids))
        .order_by(
            CheckpointFileReferenceModel.checkpoint_id,
            CheckpointFileReferenceModel.order_index,
        )
    )
    grouped: defaultdict[str, list[FileReference]] = defaultdict(list)
    for row in rows:
        grouped[row.checkpoint_id].append(FileReference(path=row.path, description=row.description))
    return {checkpoint_id: tuple(files) for checkpoint_id, files in grouped.items()}


__all__ = ["project_canonical_activity_rows"]
