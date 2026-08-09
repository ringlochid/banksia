from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path
from secrets import token_urlsafe
from typing import cast

from sqlalchemy import Select, case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from banksia.persistence.models import (
    AssignmentModel,
    DispatchTurnModel,
    HumanRequestModel,
    TaskModel,
    WorkflowRevisionModel,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.contracts.primitives import TaskEventSource
from banksia.runtime.contracts.start import TaskStartRequest
from banksia.runtime.contracts.task import (
    ProductAction,
    ProductActionConfirmation,
    TaskControlKind,
    TaskControlReceipt,
    TaskControlRequest,
    TaskProductStatus,
    TaskSearchResponse,
    TaskStartReceipt,
    TaskSummary,
    TaskView,
    TaskWorkflowView,
)
from banksia.runtime.contracts.text import MAX_WORK_PROMPT_BYTES
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.post_commit import RuntimeEffectPublisher
from banksia.runtime.product.action_ids import product_action_id, select_action_kind
from banksia.runtime.product.activities import list_recent_task_activities
from banksia.runtime.product.command_runs import list_product_command_runs
from banksia.runtime.product.human_requests import list_product_human_requests
from banksia.runtime.product.paths import build_product_api_path
from banksia.runtime.product.task_projection import (
    build_task_attention,
    product_task_result,
    read_product_task_status,
    read_product_task_workflow,
    read_product_team,
    task_status_message,
)
from banksia.runtime.task_control.contracts import ControllerTaskState
from banksia.runtime.task_control.presentation import (
    TASK_SUMMARY_MAX_CHARACTERS,
    task_prompt_excerpt,
)
from banksia.runtime.task_control.service import (
    cancel_runtime_task,
    continue_runtime_task,
    pause_runtime_task,
    runtime_task_read,
)
from banksia.runtime.task_start import start_task

_TASK_CURSOR_PREFIX = "task-search."
_TASK_PROMPT_WHITESPACE = (
    " \t\n\r\u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007"
    "\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
)
_TASK_PROMPT_SPACE_COLLAPSE_PASSES = (MAX_WORK_PROMPT_BYTES - 1).bit_length()


async def start_product_task(
    request: TaskStartRequest,
    *,
    dependencies: DispatchOpeningDependencies,
    session: AsyncSession | None = None,
    default_workspace: Path | None = None,
) -> TaskStartReceipt:
    accepted = await start_task(
        request,
        session=session,
        dependencies=dependencies,
        default_workspace=default_workspace,
    )
    return TaskStartReceipt(
        receipt_id=f"receipt.{token_urlsafe(24)}",
        task_id=accepted.task_id,
        workflow_id=accepted.workflow,
        workflow_revision=accepted.workflow_revision,
        workspace=str(accepted.workspace),
        manifest=str(accepted.manifest),
    )


async def control_product_task(
    session: AsyncSession,
    *,
    task_id: str,
    action_id: str,
    request: TaskControlRequest,
    dependencies: DispatchOpeningDependencies,
    actor_ref: str | None,
    event_source: TaskEventSource,
    runtime_effect_publisher: RuntimeEffectPublisher | None = None,
) -> TaskControlReceipt:
    current = await runtime_task_read(session, task_id)
    actions = task_control_actions(current)
    action_kind = select_action_kind(
        action_id,
        ((action.id, action.kind) for action in actions),
    )
    if action_kind is None:
        raise _action_unavailable()
    control_kind = cast(TaskControlKind, action_kind)
    action = next(item for item in actions if item.kind == action_kind)
    if action.confirmation.is_required and not request.is_confirmed:
        raise _invalid_request("Confirm the action before applying it.")

    if action_kind == "pause":
        await pause_runtime_task(
            session,
            task_id,
            expected_team_revision_id=current.current_team_revision_id,
            expected_control_revision=current.control_revision,
            actor_ref=actor_ref,
            event_source=event_source,
            runtime_effect_publisher=runtime_effect_publisher,
        )
        status_message = "The run is paused. In-flight cleanup may finish separately."
    elif action_kind == "resume":
        await continue_runtime_task(
            session,
            task_id,
            expected_team_revision_id=current.current_team_revision_id,
            expected_control_revision=current.control_revision,
            dependencies=dependencies,
            actor_ref=actor_ref,
            event_source=event_source,
        )
        status_message = "The run resumed. Work starts asynchronously."
    else:
        await cancel_runtime_task(
            session,
            task_id,
            expected_team_revision_id=current.current_team_revision_id,
            expected_control_revision=current.control_revision,
            actor_ref=actor_ref,
            event_source=event_source,
            runtime_effect_publisher=runtime_effect_publisher,
        )
        status_message = "The run was cancelled. In-flight cleanup may finish separately."
    return TaskControlReceipt(
        receipt_id=f"receipt.{token_urlsafe(24)}",
        action=control_kind,
        status_message=status_message,
        task=await read_product_task(session, task_id),
    )


async def search_product_tasks(
    session: AsyncSession,
    *,
    q: str | None = None,
    status: str = "any",
    cursor: str | None = None,
    limit: int = 50,
) -> TaskSearchResponse:
    _validate_task_search(status=status, limit=limit)
    normalized_q = (q or "").strip().casefold()
    cursor_created_at, cursor_task_id = _decode_task_cursor(
        cursor,
        normalized_q=normalized_q,
        status=status,
    )
    statement = _task_search_statement(
        normalized_q=normalized_q,
        status=status,
        cursor_created_at=cursor_created_at,
        cursor_task_id=cursor_task_id,
    )
    rows = tuple(
        await session.execute(
            statement.order_by(TaskModel.created_at.desc(), TaskModel.task_id.desc()).limit(
                limit + 1
            )
        )
    )
    page_rows = rows[:limit]
    summaries = tuple(
        _task_summary(
            task=task,
            prompt=prompt,
            workflow_description=workflow_description,
            product_status=product_status,
            attention_count=attention_count,
        )
        for (
            task,
            prompt,
            workflow_description,
            product_status,
            attention_count,
        ) in page_rows
    )
    return TaskSearchResponse(
        items=summaries,
        next_cursor=(
            _encode_task_cursor(
                page_rows[-1][0].created_at,
                page_rows[-1][0].task_id,
                normalized_q=normalized_q,
                status=status,
            )
            if len(rows) > limit and page_rows
            else None
        ),
    )


async def read_product_task(session: AsyncSession, task_id: str) -> TaskView:
    controller = await runtime_task_read(session, task_id)
    task_row = await session.get(TaskModel, task_id)
    if task_row is None:  # pragma: no cover - controller read already proved it
        raise RuntimeError("Task disappeared during product projection")
    workflow = await read_product_task_workflow(
        session,
        workflow_id=task_row.workflow_key,
        revision_no=task_row.workflow_revision_no,
    )
    human_requests = await list_product_human_requests(session, task_id=task_id)
    command_runs = await list_product_command_runs(session, task_id=task_id)
    status = await read_product_task_status(session, controller)
    team = await read_product_team(
        session,
        task=controller,
    )
    result = product_task_result(controller)
    actions = task_control_actions(controller)
    activities = await list_recent_task_activities(session, task_id=task_id, limit=20)
    attention = build_task_attention(
        task_id=task_id,
        human_requests=human_requests.items,
        result=result,
    )
    return TaskView(
        id=task_id,
        prompt_excerpt=controller.task_summary,
        workflow=workflow,
        status=status,
        status_message=task_status_message(status),
        started_at=controller.created_at,
        updated_at=controller.updated_at,
        team=team,
        attention=attention,
        actions=actions,
        result=result,
        activities=activities.items,
        activities_href=build_product_api_path(f"/tasks/{task_id}/activities"),
        is_activity_history_truncated=activities.is_truncated,
        human_requests=human_requests.items,
        human_request_count=human_requests.total_count,
        is_human_request_history_truncated=human_requests.is_truncated,
        command_runs=command_runs.items,
        command_run_count=command_runs.total_count,
        is_command_run_history_truncated=command_runs.is_truncated,
    )


def task_control_actions(task: ControllerTaskState) -> tuple[ProductAction, ...]:
    kinds: tuple[str, ...]
    if task.status.value == "running":
        kinds = ("pause", "cancel")
    elif task.status.value == "paused":
        kinds = ("cancel",) if task.pause_reason == "provider_retired" else ("resume", "cancel")
    else:
        kinds = ()
    return tuple(_task_control_action(task, kind=kind) for kind in kinds)


def _validate_task_search(*, status: str, limit: int) -> None:
    supported_statuses = {
        "any",
        "starting",
        "working",
        "waiting_for_you",
        "paused",
        "completed",
        "blocked",
        "cancelled",
    }
    if status not in supported_statuses:
        raise _invalid_request("That run status filter is not supported.")
    if not 1 <= limit <= 100:
        raise _invalid_request("Run search limit must be between 1 and 100.")


def _task_search_statement(
    *,
    normalized_q: str,
    status: str,
    cursor_created_at: datetime | None,
    cursor_task_id: str | None,
) -> Select[tuple[TaskModel, str, str, str, int]]:
    semantic_status = _task_product_status_expression()
    description = WorkflowRevisionModel.content_json["description"].as_string()
    statement = (
        select(
            TaskModel,
            func.substr(
                _normalized_task_prompt_expression(),
                1,
                TASK_SUMMARY_MAX_CHARACTERS,
            ).label("prompt_excerpt_source"),
            description.label("workflow_description"),
            semantic_status,
            _task_attention_count_expression(),
        )
        .join(
            AssignmentModel,
            (AssignmentModel.task_id == TaskModel.task_id)
            & (AssignmentModel.assignment_id == TaskModel.root_assignment_id),
        )
        .join(
            WorkflowRevisionModel,
            (WorkflowRevisionModel.workflow_key == TaskModel.workflow_key)
            & (WorkflowRevisionModel.revision_no == TaskModel.workflow_revision_no)
            & (WorkflowRevisionModel.content_hash == TaskModel.workflow_content_hash)
            & WorkflowRevisionModel.provenance.is_not(None),
        )
    )
    if normalized_q:
        pattern = f"%{normalized_q}%"
        statement = statement.where(
            or_(
                func.lower(TaskModel.task_id).like(pattern),
                func.lower(TaskModel.workflow_key).like(pattern),
                func.lower(AssignmentModel.prompt).like(pattern),
                func.lower(description).like(pattern),
            )
        )
    if status != "any":
        statement = statement.where(semantic_status == status)
    if cursor_created_at is not None and cursor_task_id is not None:
        statement = statement.where(
            or_(
                TaskModel.created_at < cursor_created_at,
                (TaskModel.created_at == cursor_created_at) & (TaskModel.task_id < cursor_task_id),
            )
        )
    return statement


def _normalized_task_prompt_expression() -> ColumnElement[str]:
    """Build the portable SQL equivalent of ``" ".join(prompt.split())``."""

    normalized = cast(ColumnElement[str], AssignmentModel.prompt)
    for whitespace in _TASK_PROMPT_WHITESPACE:
        if whitespace != " ":
            normalized = func.replace(normalized, whitespace, " ")
    for _ in range(_TASK_PROMPT_SPACE_COLLAPSE_PASSES):
        normalized = func.replace(normalized, "  ", " ")
    return func.trim(normalized)


def _task_product_status_expression() -> ColumnElement[str]:
    open_request_exists = exists().where(
        HumanRequestModel.task_id == TaskModel.task_id,
        HumanRequestModel.status == "open",
    )
    starting_dispatch_exists = exists().where(
        DispatchTurnModel.task_id == TaskModel.task_id,
        DispatchTurnModel.status == "starting",
    )
    return case(
        (
            TaskModel.status == "completed",
            case((TaskModel.terminal_outcome == "blocked", "blocked"), else_="completed"),
        ),
        (TaskModel.status == "paused", "paused"),
        (TaskModel.status == "cancelled", "cancelled"),
        (TaskModel.status == "pending", "starting"),
        (open_request_exists, "waiting_for_you"),
        (starting_dispatch_exists, "starting"),
        else_="working",
    ).label("product_status")


def _task_attention_count_expression() -> ColumnElement[int]:
    open_request_count = (
        select(func.count())
        .select_from(HumanRequestModel)
        .where(
            HumanRequestModel.task_id == TaskModel.task_id,
            HumanRequestModel.status == "open",
        )
        .correlate(TaskModel)
        .scalar_subquery()
    )
    blocked_result_count = case((TaskModel.terminal_outcome == "blocked", 1), else_=0)
    return (open_request_count + blocked_result_count).label("attention_count")


def _task_summary(
    *,
    task: TaskModel,
    prompt: str,
    workflow_description: str,
    product_status: str,
    attention_count: int,
) -> TaskSummary:
    status = cast(TaskProductStatus, product_status)
    result_status = (
        "blocked"
        if task.terminal_outcome == "blocked"
        else "completed"
        if task.terminal_outcome == "green"
        else None
    )
    return TaskSummary(
        id=task.task_id,
        prompt_excerpt=task_prompt_excerpt(
            prompt,
            max_characters=TASK_SUMMARY_MAX_CHARACTERS,
        ),
        workflow=TaskWorkflowView(
            id=task.workflow_key,
            description=workflow_description,
        ),
        status=status,
        status_message=task_status_message(status),
        started_at=task.created_at,
        updated_at=task.updated_at,
        attention_count=attention_count,
        result_status=result_status,
    )


def _encode_task_cursor(
    created_at: datetime,
    task_id: str,
    *,
    normalized_q: str,
    status: str,
) -> str:
    payload = json.dumps(
        {
            "created_at": created_at.isoformat(),
            "q": normalized_q,
            "status": status,
            "task_id": task_id,
            "version": 2,
        },
        separators=(",", ":"),
    )
    token = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{_TASK_CURSOR_PREFIX}{token}"


def _decode_task_cursor(
    cursor: str | None,
    *,
    normalized_q: str,
    status: str,
) -> tuple[datetime | None, str | None]:
    if cursor is None:
        return None, None
    if not cursor.startswith(_TASK_CURSOR_PREFIX):
        raise _invalid_request("The run-search cursor is no longer usable.")
    try:
        token = cursor.removeprefix(_TASK_CURSOR_PREFIX)
        padded = token + "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        created_at = datetime.fromisoformat(payload["created_at"])
        task_id = payload["task_id"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _invalid_request("The run-search cursor is no longer usable.") from exc
    if (
        payload.get("version") != 2
        or payload.get("q") != normalized_q
        or payload.get("status") != status
        or not isinstance(task_id, str)
        or not task_id
    ):
        raise _invalid_request("The run-search cursor is no longer usable.")
    return created_at, task_id


def _task_control_action(task: ControllerTaskState, *, kind: str) -> ProductAction:
    labels = {"pause": "Pause run", "resume": "Resume run", "cancel": "Cancel run"}
    consequences = {
        "pause": "Banksia will stop opening new work until the run is resumed.",
        "resume": "Banksia will reopen currently runnable work.",
        "cancel": "Banksia will cancel unfinished work and close open waits.",
    }
    action_id = product_action_id(
        "task-control",
        task.task_id,
        task.current_team_revision_id,
        task.control_revision,
        kind,
    )
    return ProductAction(
        id=action_id,
        kind=kind,
        label=labels[kind],
        href=build_product_api_path(f"/tasks/{task.task_id}/controls/{action_id}"),
        confirmation=ProductActionConfirmation(
            is_required=kind == "cancel",
            title=f"{labels[kind]}?",
            consequence=consequences[kind],
        ),
        input_schema={
            "type": "object",
            "properties": {"confirmed": {"type": "boolean"}},
            "additionalProperties": False,
        },
    )


def _invalid_request(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.INVALID_REQUEST_SHAPE,
        summary=summary,
        is_retryable=False,
        suggested_next_step="Reload current run information and try again.",
        status_code_override=400,
    )


def _action_unavailable() -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary="That run action is no longer available.",
        is_retryable=False,
        suggested_next_step="Reload the run and use one of its current actions.",
        status_code_override=409,
    )


__all__ = [
    "control_product_task",
    "read_product_task",
    "search_product_tasks",
    "start_product_task",
    "task_control_actions",
]
