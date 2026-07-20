from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from sqlalchemy import Select, and_, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from autoclaw.config import get_settings
from autoclaw.persistence.models import (
    DispatchCapabilitySetModel,
    DispatchTurnModel,
    FlowModel,
    TaskModel,
)
from autoclaw.runtime.contracts import (
    DispatchRuntimeRead,
    EffectiveCapabilityReadback,
    EffectiveNetworkAccess,
    EffectiveProviderNativeAccess,
    ProviderStartReadback,
    RuntimeFlowPauseReason,
    RuntimeFlowRead,
    RuntimeFlowSummary,
    RuntimeFlowSummaryListResponse,
    RuntimeFlowTerminalOutcome,
    RuntimeFlowWaitingCause,
    RuntimeLifecycleStatus,
    WorkflowManifestRef,
    WorkPlanRead,
)
from autoclaw.runtime.errors import (
    illegal_state_error,
    invalid_request_shape_error,
    missing_resource_error,
)
from autoclaw.runtime.flow.current_sources import read_runtime_flow_current_sources
from autoclaw.runtime.watchdog.deadline import calculate_watchdog_due_at
from autoclaw.runtime.work_plan import read_assignment_work_plan

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
    {"any", "pending", "running", "paused", "completed", "cancelled"}
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

    current_sources = await read_runtime_flow_current_sources(session, flow)
    target = current_sources.target
    current_dispatch = await read_current_dispatch(session, flow)
    latest_dispatch_id = await read_latest_dispatch_id(session, flow)
    stored_plan = (
        await read_assignment_work_plan(session, assignment_id=target.assignment_id)
        if target is not None
        else None
    )
    current_plan = WorkPlanRead.model_validate(stored_plan) if stored_plan is not None else None
    watchdog_recovery_count = (
        await session.scalar(
            select(func.count())
            .select_from(DispatchTurnModel)
            .where(
                DispatchTurnModel.task_id == task_id,
                DispatchTurnModel.attempt_id == target.attempt_id,
                DispatchTurnModel.opened_reason == "watchdog_recovery",
            )
        )
        if target is not None
        else None
    )
    return RuntimeFlowRead(
        task_id=task.task_id,
        task_title=task.title,
        task_summary=task.summary,
        workflow_key=task.workflow_key,
        status=RuntimeLifecycleStatus(flow.status),
        terminal_outcome=normalized_terminal_outcome(flow.terminal_outcome),
        active_flow_revision_id=flow.active_flow_revision_id,
        control_revision=flow.control_revision,
        workflow_manifest_ref=workflow_manifest_ref(),
        current_node_key=target.node_key if target is not None else None,
        active_assignment_id=target.assignment_id if target is not None else None,
        active_attempt_id=target.attempt_id if target is not None else None,
        waiting_cause=normalized_waiting_cause(flow.waiting_cause),
        pause_reason=normalized_pause_reason(flow.pause_reason),
        current_dispatch=current_dispatch,
        latest_dispatch_id=latest_dispatch_id,
        current_plan=current_plan,
        watchdog_recovery_count=watchdog_recovery_count,
        current_human_request=current_sources.human_request,
        current_command_run=current_sources.command_run,
        updated_at=coerce_datetime_to_utc(flow.updated_at),
    )


async def read_current_dispatch(
    session: AsyncSession,
    flow: FlowModel,
) -> DispatchRuntimeRead | None:
    if flow.current_dispatch_id is None:
        return None
    row = (
        await session.execute(
            select(DispatchTurnModel, DispatchCapabilitySetModel)
            .join(
                DispatchCapabilitySetModel,
                DispatchCapabilitySetModel.dispatch_id == DispatchTurnModel.dispatch_id,
            )
            .options(raiseload("*"))
            .where(
                DispatchTurnModel.dispatch_id == flow.current_dispatch_id,
                DispatchTurnModel.task_id == flow.task_id,
                DispatchTurnModel.flow_id == flow.flow_id,
                DispatchTurnModel.status.in_(("starting", "open")),
            )
        )
    ).one_or_none()
    if row is None:
        raise illegal_state_error("flow current-dispatch pointer is inconsistent")
    dispatch, capabilities = row
    provider_start = (
        ProviderStartReadback(
            revision=dispatch.provider_start_revision,
            attempt_count=dispatch.provider_start_attempt_count,
            next_attempt_at=_optional_utc(dispatch.next_provider_start_at),
            retry_kind=dispatch.provider_start_retry_kind,
            last_error_code=dispatch.provider_start_last_error_code,
        )
        if dispatch.status == "starting"
        else None
    )
    watchdog_due_at = None
    if dispatch.status == "open" and dispatch.adapter_started_at is not None:
        watchdog_due_at = calculate_watchdog_due_at(
            adapter_started_at=dispatch.adapter_started_at,
            last_node_activity_at=dispatch.last_node_activity_at,
            inactivity_timeout_seconds=(get_settings().runtime.watchdog_inactivity_timeout_seconds),
        )
    return DispatchRuntimeRead(
        dispatch_id=dispatch.dispatch_id,
        predecessor_dispatch_id=dispatch.predecessor_dispatch_id,
        assignment_id=dispatch.assignment_id,
        attempt_id=dispatch.attempt_id,
        status=dispatch.status,
        opened_reason=dispatch.opened_reason,
        requested_provider=dispatch.requested_provider,
        resolved_provider=dispatch.resolved_provider,
        selection_basis=dispatch.provider_selection_basis,
        adapter_started_at=_optional_utc(dispatch.adapter_started_at),
        last_node_activity_at=_optional_utc(dispatch.last_node_activity_at),
        node_activity_revision=dispatch.node_activity_revision,
        watchdog_due_at=watchdog_due_at,
        provider_start=provider_start,
        effective_capabilities=effective_capability_readback(capabilities),
    )


def effective_capability_readback(
    capabilities: DispatchCapabilitySetModel,
) -> EffectiveCapabilityReadback:
    return EffectiveCapabilityReadback(
        provider_native_access=EffectiveProviderNativeAccess.model_validate(
            {
                "effective": capabilities.provider_native_access,
                "source": capabilities.provider_native_access_source,
            }
        ),
        network_access=EffectiveNetworkAccess.model_validate(
            {
                "effective": capabilities.network_access,
                "source": capabilities.network_access_source,
            }
        ),
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
    for task, flow, dispatch in page:
        if flow.active_flow_revision_id is None:
            raise illegal_state_error(f"task '{task.task_id}' has no active flow revision")
        if dispatch is not None:
            current_node_key = dispatch.node_key
            active_assignment_id = dispatch.assignment_id
            active_attempt_id = dispatch.attempt_id
        else:
            target = (await read_runtime_flow_current_sources(session, flow)).target
            current_node_key = target.node_key if target is not None else None
            active_assignment_id = target.assignment_id if target is not None else None
            active_attempt_id = target.attempt_id if target is not None else None
        summaries.append(
            RuntimeFlowSummary(
                task_id=task.task_id,
                task_title=task.title,
                task_summary=task.summary,
                workflow_key=task.workflow_key,
                status=RuntimeLifecycleStatus(flow.status),
                terminal_outcome=normalized_terminal_outcome(flow.terminal_outcome),
                active_flow_revision_id=flow.active_flow_revision_id,
                workflow_manifest_ref=workflow_manifest_ref(),
                current_node_key=current_node_key,
                active_assignment_id=active_assignment_id,
                active_attempt_id=active_attempt_id,
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
) -> Select[tuple[TaskModel, FlowModel, DispatchTurnModel]]:
    statement = (
        select(TaskModel, FlowModel, DispatchTurnModel)
        .join(FlowModel, FlowModel.task_id == TaskModel.task_id)
        .outerjoin(
            DispatchTurnModel,
            and_(
                DispatchTurnModel.flow_id == FlowModel.flow_id,
                DispatchTurnModel.dispatch_id == FlowModel.current_dispatch_id,
            ),
        )
        .options(raiseload("*"))
    )
    normalized_query = (q or "").strip().lower()
    if normalized_query:
        pattern = f"%{normalized_query}%"
        statement = statement.where(
            or_(
                func.lower(TaskModel.task_id).like(pattern),
                func.lower(TaskModel.title).like(pattern),
                func.lower(TaskModel.summary).like(pattern),
                func.lower(func.coalesce(TaskModel.workflow_key, "")).like(pattern),
            )
        )
    statement = _filter_runtime_flow_status(statement, status)
    if sort == "updated_at_asc":
        return statement.order_by(FlowModel.updated_at.asc(), TaskModel.task_id.asc())
    if sort == "task_title_asc":
        return statement.order_by(TaskModel.title.asc(), TaskModel.task_id.asc())
    if sort == "task_title_desc":
        return statement.order_by(TaskModel.title.desc(), TaskModel.task_id.desc())
    return statement.order_by(FlowModel.updated_at.desc(), TaskModel.task_id.desc())


async def read_latest_dispatch_id(
    session: AsyncSession,
    flow: FlowModel,
) -> str | None:
    return cast(
        str | None,
        await session.scalar(
            select(DispatchTurnModel.dispatch_id)
            .where(
                DispatchTurnModel.task_id == flow.task_id,
                DispatchTurnModel.flow_id == flow.flow_id,
            )
            .order_by(
                DispatchTurnModel.created_at.desc(),
                DispatchTurnModel.dispatch_id.desc(),
            )
            .limit(1)
        ),
    )


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


def normalized_waiting_cause(waiting_cause: str) -> RuntimeFlowWaitingCause | None:
    if waiting_cause not in {"human_request", "command_run"}:
        return None
    return cast(RuntimeFlowWaitingCause, waiting_cause)


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
        path=Path("_runtime/workflow-manifest.md"),
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


def _filter_runtime_flow_status(
    statement: Select[tuple[TaskModel, FlowModel, DispatchTurnModel]],
    status: str,
) -> Select[tuple[TaskModel, FlowModel, DispatchTurnModel]]:
    if status == "any":
        return statement
    if status == "pending":
        return statement.where(false())
    return statement.where(FlowModel.status == status)


def _optional_utc(value: datetime | None) -> datetime | None:
    return coerce_datetime_to_utc(value) if value is not None else None


__all__ = [
    "RUNTIME_FLOW_LIST_SORTS",
    "RUNTIME_FLOW_LIST_STATUSES",
    "WORKFLOW_MANIFEST_REF_DESCRIPTION",
    "effective_capability_readback",
    "list_runtime_flow_summaries",
    "normalized_pause_reason",
    "normalized_terminal_outcome",
    "normalized_waiting_cause",
    "read_current_dispatch",
    "read_runtime_flow",
]
