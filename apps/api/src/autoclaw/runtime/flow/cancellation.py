from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from autoclaw.persistence.models import (
    AttemptModel,
    FlowModel,
    FlowNodeModel,
    FlowWaitModel,
    HumanRequestModel,
    TransientLocalizationModel,
)
from autoclaw.runtime.command_run.service import request_command_run_cancellation
from autoclaw.runtime.contracts import (
    HumanRequestResolutionSurface,
    TaskEventSource,
    TaskEventType,
)
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.errors import RuntimeOperationError, illegal_state_error
from autoclaw.runtime.post_commit import (
    CommandRunCancellationRequested,
    HumanRequestTerminal,
    TransientCleanupRequested,
)
from autoclaw.runtime.task_events import append_task_event


async def cancel_external_wait(
    session: AsyncSession,
    *,
    flow: FlowModel,
    actor_ref: str | None,
    event_source: TaskEventSource,
    cancelled_at: datetime,
) -> tuple[HumanRequestTerminal | None, CommandRunCancellationRequested | None]:
    wait = await session.scalar(
        select(FlowWaitModel).options(raiseload("*")).where(FlowWaitModel.flow_id == flow.flow_id)
    )
    if flow.waiting_cause == "none":
        if wait is not None or flow.waiting_source_id is not None:
            raise illegal_state_error("flow wait authority is inconsistent")
        return None, None
    if wait is None or flow.waiting_source_id is None:
        raise illegal_state_error("flow wait authority is incomplete")
    human_signal: HumanRequestTerminal | None = None
    command_signal: CommandRunCancellationRequested | None = None
    if flow.waiting_cause == "human_request":
        request_id = await _cancel_human_request(
            session,
            flow=flow,
            wait=wait,
            actor_ref=actor_ref,
            event_source=event_source,
            cancelled_at=cancelled_at,
        )
        human_signal = HumanRequestTerminal(request_id=request_id)
    elif flow.waiting_cause == "command_run":
        command_signal = await _request_waiting_command_cancellation(
            session,
            flow=flow,
            wait=wait,
            actor_ref=actor_ref,
            event_source=event_source,
        )
    else:
        raise illegal_state_error(f"unsupported flow waiting cause '{flow.waiting_cause}'")
    await session.execute(delete(FlowWaitModel).where(FlowWaitModel.flow_id == flow.flow_id))
    return human_signal, command_signal


async def cancel_execution_rows(
    session: AsyncSession,
    *,
    flow: FlowModel,
    cancelled_at: datetime,
) -> None:
    await session.execute(
        update(AttemptModel)
        .where(
            AttemptModel.flow_id == flow.flow_id,
            AttemptModel.status.in_(("pending", "running")),
        )
        .values(status="cancelled", terminal_outcome=None, closed_at=cancelled_at)
    )
    await session.execute(
        update(FlowNodeModel)
        .where(
            FlowNodeModel.flow_id == flow.flow_id,
            FlowNodeModel.flow_revision_id == flow.active_flow_revision_id,
            FlowNodeModel.state.in_(("ready", "running", "waiting", "paused")),
        )
        .values(state="cancelled")
    )


async def read_expired_transient_cleanup_signals(
    session: AsyncSession,
    *,
    task_id: str,
) -> tuple[TransientCleanupRequested, ...]:
    rows = tuple(
        (
            await session.execute(
                select(
                    TransientLocalizationModel.transient_localization_id,
                    TransientLocalizationModel.expires_at,
                )
                .where(
                    TransientLocalizationModel.task_id == task_id,
                    TransientLocalizationModel.retention_status == "expired",
                )
                .order_by(TransientLocalizationModel.transient_localization_id)
            )
        ).all()
    )
    signals: list[TransientCleanupRequested] = []
    for transient_localization_id, expires_at in rows:
        if expires_at is None:
            raise illegal_state_error(
                f"expired transient '{transient_localization_id}' has no retention generation"
            )
        signals.append(
            TransientCleanupRequested(
                transient_localization_id=transient_localization_id,
                expires_at=expires_at,
            )
        )
    return tuple(signals)


async def _cancel_human_request(
    session: AsyncSession,
    *,
    flow: FlowModel,
    wait: FlowWaitModel,
    actor_ref: str | None,
    event_source: TaskEventSource,
    cancelled_at: datetime,
) -> str:
    request_id = wait.human_request_id
    if request_id is None or request_id != flow.waiting_source_id:
        raise illegal_state_error("flow human-request wait source is inconsistent")
    source = await session.scalar(
        select(HumanRequestModel)
        .options(raiseload("*"))
        .where(
            HumanRequestModel.request_id == request_id,
            HumanRequestModel.task_id == flow.task_id,
            HumanRequestModel.flow_id == flow.flow_id,
            HumanRequestModel.status == "open",
        )
    )
    if source is None:
        raise _flow_control_conflict("the waiting human request changed before task cancellation")
    changed = await session.scalar(
        update(HumanRequestModel)
        .where(
            HumanRequestModel.request_id == request_id,
            HumanRequestModel.task_id == flow.task_id,
            HumanRequestModel.flow_id == flow.flow_id,
            HumanRequestModel.status == "open",
        )
        .values(
            status="cancelled",
            resolution_kind="cancelled",
            item_responses_json=None,
            resolution_policy_basis_json=None,
            resolution_summary="Cancelled because the task was cancelled.",
            resolved_by_actor_ref=actor_ref,
            resolved_by_surface=_human_resolution_surface(event_source).value,
            resolved_at=cancelled_at,
        )
        .returning(HumanRequestModel.request_id)
    )
    if changed is None:
        raise _flow_control_conflict("the waiting human request changed before task cancellation")
    await append_task_event(
        session,
        task_id=flow.task_id,
        event_type=TaskEventType.HUMAN_REQUEST_CANCELLED,
        event_source=event_source,
        occurred_at=cancelled_at,
        flow_revision_id=flow.active_flow_revision_id,
        dispatch_id=wait.source_dispatch_id,
        actor_ref=actor_ref,
        payload={
            "request_id": request_id,
            "kind": source.request_kind,
            "summary": source.request_summary,
            "source_dispatch_id": source.source_dispatch_id,
            "due_at": source.due_at,
            "status": "cancelled",
            "resolution_kind": "cancelled",
            "resolution_summary": "Cancelled because the task was cancelled.",
            "resolved_at": cancelled_at,
            "resolved_by_surface": _human_resolution_surface(event_source).value,
            "resolved_by_actor_ref": actor_ref,
        },
    )
    return request_id


async def _request_waiting_command_cancellation(
    session: AsyncSession,
    *,
    flow: FlowModel,
    wait: FlowWaitModel,
    actor_ref: str | None,
    event_source: TaskEventSource,
) -> CommandRunCancellationRequested | None:
    run_id = wait.command_run_id
    if run_id is None or run_id != flow.waiting_source_id:
        raise illegal_state_error("flow command-run wait source is inconsistent")
    source, changed = await request_command_run_cancellation(
        session,
        task_id=flow.task_id,
        run_id=run_id,
        actor_ref=actor_ref,
        event_source=event_source,
        is_already_requested_allowed=True,
    )
    if not changed:
        return None
    return CommandRunCancellationRequested(
        run_id=source.run_id,
        ownership_revision=source.ownership_revision,
    )


def _human_resolution_surface(event_source: TaskEventSource) -> HumanRequestResolutionSurface:
    if event_source == TaskEventSource.OPERATOR_MCP:
        return HumanRequestResolutionSurface.OPERATOR_MCP
    if event_source == TaskEventSource.CONTROL_API:
        return HumanRequestResolutionSurface.CONTROL_API
    return HumanRequestResolutionSurface.CONTROLLER


def _flow_control_conflict(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary=summary,
        is_retryable=False,
        suggested_next_step="Reread the task and retry only against its current revisions.",
    )


__all__ = [
    "cancel_execution_rows",
    "cancel_external_wait",
    "read_expired_transient_cleanup_signals",
]
