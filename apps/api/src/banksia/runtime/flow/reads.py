from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from sqlalchemy import Select, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from banksia.persistence.models import (
    AssignmentModel,
    FlowModel,
    TaskModel,
)
from banksia.runtime.checkpoint import read_task_result
from banksia.runtime.contracts import (
    RuntimeFlowPauseReason,
    RuntimeFlowRead,
    RuntimeFlowSummary,
    RuntimeFlowSummaryListResponse,
    RuntimeFlowTerminalOutcome,
    RuntimeLifecycleStatus,
    WorkflowManifestRef,
)
from banksia.runtime.errors import (
    illegal_state_error,
    invalid_request_shape_error,
    missing_resource_error,
)

WORKFLOW_MANIFEST_REF_DESCRIPTION = "Whole-workflow visible contract for the current task."

RUNTIME_FLOW_LIST_SORTS = frozenset(
    {
        "updated_at_desc",
        "updated_at_asc",
        "task_title_asc",
        "task_title_desc",
    }
)
RUNTIME_FLOW_LIST_STATUSES = frozenset(
    {"any", "pending", "running", "paused", "completed", "blocked", "cancelled"}
)


async def read_runtime_flow(session: AsyncSession, task_id: str) -> RuntimeFlowRead:
    """Read controller-owned current flow facts for one task."""

    row = (
        await session.execute(
            select(TaskModel, FlowModel)
            .join(FlowModel, FlowModel.task_id == TaskModel.task_id)
            .options(raiseload("*"))
            .where(TaskModel.task_id == task_id)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if row is None:
        raise missing_resource_error(f"unknown task_id '{task_id}'")
    task, flow = row
    if flow.active_flow_revision_id is None:
        raise illegal_state_error(f"task '{task_id}' has no active flow revision")

    root_prompt = await _read_root_assignment_prompt(session, flow)
    task_title, task_summary = _task_prompt_excerpts(root_prompt)
    result = await read_task_result(session, task_id=task.task_id)
    return RuntimeFlowRead(
        task_id=task.task_id,
        task_title=task_title,
        task_summary=task_summary,
        workflow_key=task.workflow_key,
        status=RuntimeLifecycleStatus(flow.status),
        terminal_outcome=normalized_terminal_outcome(flow.terminal_outcome),
        result=result,
        active_flow_revision_id=flow.active_flow_revision_id,
        control_revision=flow.control_revision,
        workflow_manifest_ref=workflow_manifest_ref(),
        pause_reason=normalized_pause_reason(flow.pause_reason),
        updated_at=coerce_datetime_to_utc(flow.updated_at),
    )


async def list_runtime_flow_summaries(
    session: AsyncSession,
    *,
    q: str | None,
    cursor: str | None,
    status: str,
    limit: int,
    sort: str,
) -> RuntimeFlowSummaryListResponse:
    """Return a bounded controller-row task list without support-file reads."""

    validate_runtime_flow_list_arguments(status=status, sort=sort, limit=limit)
    offset = parse_runtime_flow_cursor(cursor)
    statement = runtime_flow_summary_statement(q=q, status=status, sort=sort).offset(offset)
    rows = list((await session.execute(statement.limit(limit + 1))).all())
    page = rows[:limit]
    summaries: list[RuntimeFlowSummary] = []
    for task, flow, root_assignment in page:
        if flow.active_flow_revision_id is None:
            raise illegal_state_error(f"task '{task.task_id}' has no active flow revision")
        task_title, task_summary = _task_prompt_excerpts(root_assignment.prompt)
        summaries.append(
            RuntimeFlowSummary(
                task_id=task.task_id,
                task_title=task_title,
                task_summary=task_summary,
                workflow_key=task.workflow_key,
                status=RuntimeLifecycleStatus(flow.status),
                terminal_outcome=normalized_terminal_outcome(flow.terminal_outcome),
                active_flow_revision_id=flow.active_flow_revision_id,
                workflow_manifest_ref=workflow_manifest_ref(),
                updated_at=coerce_datetime_to_utc(flow.updated_at),
            )
        )
    return RuntimeFlowSummaryListResponse(
        items=tuple(summaries),
        next_cursor=str(offset + limit) if len(rows) > limit else None,
    )


def runtime_flow_summary_statement(
    *,
    q: str | None,
    status: str,
    sort: str,
) -> Select[tuple[TaskModel, FlowModel, AssignmentModel]]:
    statement = (
        select(TaskModel, FlowModel, AssignmentModel)
        .join(FlowModel, FlowModel.task_id == TaskModel.task_id)
        .join(
            AssignmentModel,
            (AssignmentModel.task_id == TaskModel.task_id)
            & (AssignmentModel.flow_id == FlowModel.flow_id)
            & AssignmentModel.parent_assignment_id.is_(None)
            & AssignmentModel.superseded_at.is_(None),
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
    statement = _filter_runtime_flow_status(statement, status)
    if sort == "updated_at_asc":
        return statement.order_by(FlowModel.updated_at.asc(), TaskModel.task_id.asc())
    if sort == "task_title_asc":
        return statement.order_by(AssignmentModel.prompt.asc(), TaskModel.task_id.asc())
    if sort == "task_title_desc":
        return statement.order_by(AssignmentModel.prompt.desc(), TaskModel.task_id.desc())
    return statement.order_by(FlowModel.updated_at.desc(), TaskModel.task_id.desc())


def normalized_pause_reason(
    pause_reason: str | None,
) -> RuntimeFlowPauseReason | None:
    if pause_reason is None:
        return None
    if pause_reason not in {
        "paused_by_operator",
        "runtime_recovery_exhausted",
        "runtime_transition_failed",
    }:
        raise illegal_state_error(f"flow has unsupported pause reason '{pause_reason}'")
    return cast(RuntimeFlowPauseReason, pause_reason)


def normalized_terminal_outcome(
    terminal_outcome: str | None,
) -> RuntimeFlowTerminalOutcome | None:
    if terminal_outcome is None:
        return None
    if terminal_outcome not in {"green", "blocked"}:
        raise illegal_state_error(f"flow has unsupported terminal outcome '{terminal_outcome}'")
    return cast(RuntimeFlowTerminalOutcome, terminal_outcome)


def workflow_manifest_ref() -> WorkflowManifestRef:
    return WorkflowManifestRef(
        path=Path("manifest.md"),
        description=WORKFLOW_MANIFEST_REF_DESCRIPTION,
    )


def parse_runtime_flow_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        offset = int(cursor)
    except ValueError as exc:
        raise invalid_request_shape_error("runtime task cursor must be an integer offset") from exc
    if offset < 0:
        raise invalid_request_shape_error("runtime task cursor must be non-negative")
    return offset


def validate_runtime_flow_list_arguments(*, status: str, sort: str, limit: int) -> None:
    if status not in RUNTIME_FLOW_LIST_STATUSES:
        raise invalid_request_shape_error(f"unknown status filter '{status}'")
    if sort not in RUNTIME_FLOW_LIST_SORTS:
        raise invalid_request_shape_error(f"unknown runtime task sort '{sort}'")
    if not 1 <= limit <= 200:
        raise invalid_request_shape_error("runtime task limit must be between 1 and 200")


def coerce_datetime_to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def _read_root_assignment_prompt(
    session: AsyncSession,
    flow: FlowModel,
) -> str:
    prompt = await session.scalar(
        select(AssignmentModel.prompt).where(
            AssignmentModel.task_id == flow.task_id,
            AssignmentModel.flow_id == flow.flow_id,
            AssignmentModel.parent_assignment_id.is_(None),
            AssignmentModel.superseded_at.is_(None),
        )
    )
    if prompt is None:
        raise illegal_state_error(f"task '{flow.task_id}' has no current root Assignment")
    return prompt


def _task_prompt_excerpts(prompt: str) -> tuple[str, str]:
    compact = " ".join(prompt.split())
    if not compact:
        raise illegal_state_error("root Assignment prompt is blank")
    return compact[:80], compact[:240]


def _filter_runtime_flow_status(
    statement: Select[tuple[TaskModel, FlowModel, AssignmentModel]],
    status: str,
) -> Select[tuple[TaskModel, FlowModel, AssignmentModel]]:
    if status == "any":
        return statement
    if status == "pending":
        return statement.where(false())
    if status == "completed":
        return statement.where(
            FlowModel.status == "completed",
            FlowModel.terminal_outcome == "green",
        )
    if status == "blocked":
        return statement.where(
            FlowModel.status == "completed",
            FlowModel.terminal_outcome == "blocked",
        )
    return statement.where(FlowModel.status == status)


__all__ = [
    "RUNTIME_FLOW_LIST_SORTS",
    "RUNTIME_FLOW_LIST_STATUSES",
    "WORKFLOW_MANIFEST_REF_DESCRIPTION",
    "list_runtime_flow_summaries",
    "normalized_pause_reason",
    "normalized_terminal_outcome",
    "read_runtime_flow",
]
