from __future__ import annotations

from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.persistence.models import DispatchTurnModel, FlowModel
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.dispatch.authority import NodeOperationAuthority
from autoclaw.runtime.errors import RuntimeOperationError


async def close_source_dispatch(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    now: datetime,
    closed_reason: str,
    waiting_cause: str,
    waiting_source_id: str | None,
) -> None:
    closed = await session.scalar(
        update(DispatchTurnModel)
        .where(
            DispatchTurnModel.dispatch_id == authority.dispatch_id,
            DispatchTurnModel.task_id == authority.task_id,
            DispatchTurnModel.assignment_id == authority.assignment_id,
            DispatchTurnModel.attempt_id == authority.attempt_id,
            DispatchTurnModel.status.in_(("starting", "open")),
        )
        .values(
            status="closed",
            closed_at=now,
            closed_reason=closed_reason,
            next_provider_start_at=None,
            provider_start_retry_kind=None,
        )
        .returning(DispatchTurnModel.dispatch_id)
    )
    if closed is None:
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="another transition already closed the source dispatch",
            is_retryable=False,
        )
    changed_flow = await session.scalar(
        update(FlowModel)
        .where(
            FlowModel.flow_id == authority.flow_id,
            FlowModel.task_id == authority.task_id,
            FlowModel.status == "running",
            FlowModel.current_dispatch_id == authority.dispatch_id,
            FlowModel.active_flow_revision_id == authority.flow_revision_id,
            FlowModel.waiting_cause == "none",
        )
        .values(
            current_dispatch_id=None,
            waiting_cause=waiting_cause,
            waiting_source_id=waiting_source_id,
            control_revision=FlowModel.control_revision + 1,
        )
        .returning(FlowModel.flow_id)
    )
    if changed_flow is None:
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="another transition already changed current flow authority",
            is_retryable=False,
        )


__all__ = ["close_source_dispatch"]
