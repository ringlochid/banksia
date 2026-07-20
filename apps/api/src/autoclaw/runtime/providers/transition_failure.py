from __future__ import annotations

from datetime import datetime

from sqlalchemy import exists, update
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.persistence.models import DispatchTurnModel, FlowModel
from autoclaw.runtime.contracts import TaskEventSource, TaskEventType
from autoclaw.runtime.dispatch.provider_start import ProviderStartCandidate
from autoclaw.runtime.post_commit import DispatchStartDue
from autoclaw.runtime.task_events import append_task_event


async def pause_invalid_provider_start(
    session: AsyncSession,
    *,
    signal: DispatchStartDue,
    candidate: ProviderStartCandidate,
    failed_at: datetime,
    failure_code: str,
) -> bool:
    """Pause only the exact still-current dispatch with invalid committed input."""

    if not await _close_invalid_starting_dispatch(session, signal, candidate, failed_at):
        await session.rollback()
        return False
    if not await _pause_invalid_starting_flow(
        session,
        signal,
        candidate,
        failed_at,
        failure_code,
    ):
        await session.rollback()
        return False

    await _append_invalid_provider_start_event(
        session,
        signal,
        candidate,
        failed_at,
        failure_code,
    )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return True


async def _close_invalid_starting_dispatch(
    session: AsyncSession,
    signal: DispatchStartDue,
    candidate: ProviderStartCandidate,
    failed_at: datetime,
) -> bool:
    dispatch_id = await session.scalar(
        update(DispatchTurnModel)
        .where(
            DispatchTurnModel.dispatch_id == signal.dispatch_id,
            DispatchTurnModel.task_id == candidate.task_id,
            DispatchTurnModel.flow_id == candidate.flow_id,
            DispatchTurnModel.status == "starting",
            DispatchTurnModel.provider_start_revision == signal.provider_start_revision,
            DispatchTurnModel.provider_start_attempt_count
            == candidate.provider_start_attempt_count,
            DispatchTurnModel.next_provider_start_at == candidate.persisted_due_at,
            exists().where(
                FlowModel.flow_id == candidate.flow_id,
                FlowModel.task_id == candidate.task_id,
                FlowModel.status == "running",
                FlowModel.current_dispatch_id == signal.dispatch_id,
                FlowModel.waiting_cause == "none",
                FlowModel.control_revision == candidate.flow_control_revision,
            ),
        )
        .values(
            status="closed",
            closed_at=failed_at,
            closed_reason="control_failed",
            next_provider_start_at=None,
            provider_start_retry_kind=None,
            provider_start_last_error_code=None,
        )
        .returning(DispatchTurnModel.dispatch_id)
    )
    return dispatch_id is not None


async def _pause_invalid_starting_flow(
    session: AsyncSession,
    signal: DispatchStartDue,
    candidate: ProviderStartCandidate,
    failed_at: datetime,
    failure_code: str,
) -> bool:
    flow_id = await session.scalar(
        update(FlowModel)
        .where(
            FlowModel.flow_id == candidate.flow_id,
            FlowModel.task_id == candidate.task_id,
            FlowModel.status == "running",
            FlowModel.active_flow_revision_id == candidate.flow_revision_id,
            FlowModel.current_dispatch_id == signal.dispatch_id,
            FlowModel.waiting_cause == "none",
            FlowModel.control_revision == candidate.flow_control_revision,
        )
        .values(
            status="paused",
            current_dispatch_id=None,
            pause_reason="runtime_transition_failed",
            pause_details={
                "source": "provider_start",
                "source_dispatch_id": signal.dispatch_id,
                "failure_code": failure_code,
            },
            paused_at=failed_at,
            paused_by_actor_ref="controller.runtime",
            control_revision=FlowModel.control_revision + 1,
            updated_at=failed_at,
        )
        .returning(FlowModel.flow_id)
    )
    return flow_id is not None


async def _append_invalid_provider_start_event(
    session: AsyncSession,
    signal: DispatchStartDue,
    candidate: ProviderStartCandidate,
    failed_at: datetime,
    failure_code: str,
) -> None:
    await append_task_event(
        session,
        task_id=candidate.task_id,
        event_type=TaskEventType.TASK_PAUSED,
        event_source=TaskEventSource.CONTROLLER,
        occurred_at=failed_at,
        flow_revision_id=candidate.flow_revision_id,
        dispatch_id=signal.dispatch_id,
        attempt_id=candidate.attempt_id,
        node_key=candidate.node_key,
        actor_ref="controller.runtime",
        payload={
            "pause_reason": "runtime_transition_failed",
            "control_revision": candidate.flow_control_revision + 1,
            "actor_ref": "controller.runtime",
            "summary": f"Provider start could not continue: {failure_code}.",
        },
    )


__all__ = ["pause_invalid_provider_start"]
