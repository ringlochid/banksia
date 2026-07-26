"""Controller-owned Task lifecycle reads."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import Select, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from banksia.persistence.models import AssignmentModel, TaskModel
from banksia.runtime.checkpoint import read_task_result
from banksia.runtime.contracts import FileReference
from banksia.runtime.errors import (
    illegal_state_error,
    invalid_request_shape_error,
    missing_resource_error,
)
from banksia.runtime.task_control.contracts import (
    ControllerTaskLifecycleStatus,
    ControllerTaskPauseReason,
    ControllerTaskState,
    ControllerTaskSummary,
    ControllerTaskSummaryPage,
    ControllerTaskTerminalOutcome,
)
from banksia.runtime.task_control.presentation import (
    TASK_SUMMARY_MAX_CHARACTERS,
    TASK_TITLE_MAX_CHARACTERS,
    task_prompt_excerpt,
)

WORKFLOW_MANIFEST_REF_DESCRIPTION = "Whole-workflow visible contract for the current task."

RUNTIME_TASK_LIST_SORTS = frozenset(
    {
        "updated_at_desc",
        "updated_at_asc",
        "task_title_asc",
        "task_title_desc",
    }
)
RUNTIME_TASK_LIST_STATUSES = frozenset(
    {"any", "pending", "running", "paused", "completed", "blocked", "cancelled"}
)


async def read_runtime_task(session: AsyncSession, task_id: str) -> ControllerTaskState:
    """Read controller-owned lifecycle facts for one Task."""

    task = await session.scalar(
        select(TaskModel)
        .options(raiseload("*"))
        .where(TaskModel.task_id == task_id)
        .execution_options(populate_existing=True)
    )
    if task is None:
        raise missing_resource_error(f"unknown task_id '{task_id}'")
    if task.current_team_revision_id is None:
        raise illegal_state_error(f"task '{task_id}' has no current Team revision")

    root_prompt = await _read_root_assignment_prompt(session, task)
    task_title = task_prompt_excerpt(
        root_prompt,
        max_characters=TASK_TITLE_MAX_CHARACTERS,
    )
    task_summary = task_prompt_excerpt(
        root_prompt,
        max_characters=TASK_SUMMARY_MAX_CHARACTERS,
    )
    result = await read_task_result(session, task_id=task.task_id)
    return ControllerTaskState(
        task_id=task.task_id,
        task_title=task_title,
        task_summary=task_summary,
        workflow_key=task.workflow_key,
        status=ControllerTaskLifecycleStatus(task.status),
        terminal_outcome=normalized_terminal_outcome(task.terminal_outcome),
        result=result,
        current_team_revision_id=task.current_team_revision_id,
        control_revision=task.control_revision,
        workflow_manifest_ref=workflow_manifest_ref(task.task_id),
        pause_reason=normalized_pause_reason(task.pause_reason),
        created_at=coerce_datetime_to_utc(task.created_at),
        updated_at=coerce_datetime_to_utc(task.updated_at),
    )


async def list_runtime_task_summaries(
    session: AsyncSession,
    *,
    q: str | None,
    cursor: str | None,
    status: str,
    limit: int,
    sort: str,
) -> ControllerTaskSummaryPage:
    """Return a bounded controller-row Task list without support-file reads."""

    validate_runtime_task_list_arguments(status=status, sort=sort, limit=limit)
    offset = parse_runtime_task_cursor(cursor)
    statement = runtime_task_summary_statement(q=q, status=status, sort=sort).offset(offset)
    rows = list((await session.execute(statement.limit(limit + 1))).all())
    page = rows[:limit]
    summaries: list[ControllerTaskSummary] = []
    for task, root_assignment in page:
        if task.current_team_revision_id is None:
            raise illegal_state_error(f"task '{task.task_id}' has no current Team revision")
        task_title = task_prompt_excerpt(
            root_assignment.prompt,
            max_characters=TASK_TITLE_MAX_CHARACTERS,
        )
        task_summary = task_prompt_excerpt(
            root_assignment.prompt,
            max_characters=TASK_SUMMARY_MAX_CHARACTERS,
        )
        summaries.append(
            ControllerTaskSummary(
                task_id=task.task_id,
                task_title=task_title,
                task_summary=task_summary,
                workflow_key=task.workflow_key,
                status=ControllerTaskLifecycleStatus(task.status),
                terminal_outcome=normalized_terminal_outcome(task.terminal_outcome),
                current_team_revision_id=task.current_team_revision_id,
                workflow_manifest_ref=workflow_manifest_ref(task.task_id),
                created_at=coerce_datetime_to_utc(task.created_at),
                updated_at=coerce_datetime_to_utc(task.updated_at),
            )
        )
    return ControllerTaskSummaryPage(
        items=tuple(summaries),
        next_cursor=str(offset + limit) if len(rows) > limit else None,
    )


def runtime_task_summary_statement(
    *,
    q: str | None,
    status: str,
    sort: str,
) -> Select[tuple[TaskModel, AssignmentModel]]:
    statement = (
        select(TaskModel, AssignmentModel)
        .join(
            AssignmentModel,
            (AssignmentModel.task_id == TaskModel.task_id)
            & (AssignmentModel.assignment_id == TaskModel.root_assignment_id),
        )
        .options(raiseload("*"))
    )
    normalized_query = (q or "").strip().lower()
    if normalized_query:
        pattern = f"%{normalized_query}%"
        statement = statement.where(
            or_(
                func.lower(TaskModel.task_id).like(pattern),
                func.lower(AssignmentModel.prompt).like(pattern),
                func.lower(func.coalesce(TaskModel.workflow_key, "")).like(pattern),
            )
        )
    statement = _filter_runtime_task_status(statement, status)
    if sort == "updated_at_asc":
        return statement.order_by(TaskModel.updated_at.asc(), TaskModel.task_id.asc())
    if sort == "task_title_asc":
        return statement.order_by(AssignmentModel.prompt.asc(), TaskModel.task_id.asc())
    if sort == "task_title_desc":
        return statement.order_by(AssignmentModel.prompt.desc(), TaskModel.task_id.desc())
    return statement.order_by(TaskModel.updated_at.desc(), TaskModel.task_id.desc())


def normalized_pause_reason(
    pause_reason: str | None,
) -> ControllerTaskPauseReason | None:
    if pause_reason is None:
        return None
    if pause_reason not in {
        "paused_by_operator",
        "runtime_recovery_exhausted",
        "runtime_transition_failed",
    }:
        raise illegal_state_error(f"Task has unsupported pause reason '{pause_reason}'")
    return cast(ControllerTaskPauseReason, pause_reason)


def normalized_terminal_outcome(
    terminal_outcome: str | None,
) -> ControllerTaskTerminalOutcome | None:
    if terminal_outcome is None:
        return None
    if terminal_outcome not in {"green", "blocked"}:
        raise illegal_state_error(f"Task has unsupported terminal outcome '{terminal_outcome}'")
    return cast(ControllerTaskTerminalOutcome, terminal_outcome)


def workflow_manifest_ref(task_id: str) -> FileReference:
    return FileReference(
        path=f".banksia/{task_id}/manifest.md",
        description=WORKFLOW_MANIFEST_REF_DESCRIPTION,
    )


def parse_runtime_task_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        offset = int(cursor)
    except ValueError as exc:
        raise invalid_request_shape_error("runtime task cursor must be an integer offset") from exc
    if offset < 0:
        raise invalid_request_shape_error("runtime task cursor must be non-negative")
    return offset


def validate_runtime_task_list_arguments(*, status: str, sort: str, limit: int) -> None:
    if status not in RUNTIME_TASK_LIST_STATUSES:
        raise invalid_request_shape_error(f"unknown status filter '{status}'")
    if sort not in RUNTIME_TASK_LIST_SORTS:
        raise invalid_request_shape_error(f"unknown runtime task sort '{sort}'")
    if not 1 <= limit <= 200:
        raise invalid_request_shape_error("runtime task limit must be between 1 and 200")


def coerce_datetime_to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def _read_root_assignment_prompt(
    session: AsyncSession,
    task: TaskModel,
) -> str:
    if task.root_assignment_id is None:
        raise illegal_state_error(f"task '{task.task_id}' has no root Assignment")
    prompt = await session.scalar(
        select(AssignmentModel.prompt).where(
            AssignmentModel.task_id == task.task_id,
            AssignmentModel.assignment_id == task.root_assignment_id,
        )
    )
    if prompt is None:
        raise illegal_state_error(f"task '{task.task_id}' has no current root Assignment")
    return prompt


def _filter_runtime_task_status(
    statement: Select[tuple[TaskModel, AssignmentModel]],
    status: str,
) -> Select[tuple[TaskModel, AssignmentModel]]:
    if status == "any":
        return statement
    if status == "pending":
        return statement.where(false())
    if status == "completed":
        return statement.where(
            TaskModel.status == "completed",
            TaskModel.terminal_outcome == "green",
        )
    if status == "blocked":
        return statement.where(
            TaskModel.status == "completed",
            TaskModel.terminal_outcome == "blocked",
        )
    return statement.where(TaskModel.status == status)


__all__ = [
    "RUNTIME_TASK_LIST_SORTS",
    "RUNTIME_TASK_LIST_STATUSES",
    "WORKFLOW_MANIFEST_REF_DESCRIPTION",
    "list_runtime_task_summaries",
    "normalized_pause_reason",
    "normalized_terminal_outcome",
    "read_runtime_task",
]
