from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload
from sqlalchemy.sql.elements import ColumnElement

from banksia.persistence.models import (
    AttemptModel,
    DispatchTurnModel,
    FlowModel,
    ReplanTransitionModel,
)
from banksia.runtime.clock import utc_now
from banksia.runtime.contracts import (
    RuntimeFlowPauseResponse,
    RuntimeFlowRead,
    TaskEventSource,
    TaskEventType,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.opening import TaskResumeEventBasis
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import (
    RuntimeOperationError,
    missing_resource_error,
    stale_flow_revision_error,
)
from banksia.runtime.flow.cancellation import (
    cancel_attempt_waits,
    cancel_execution_rows,
)
from banksia.runtime.flow.continuation import continue_paused_flow
from banksia.runtime.flow.reads import read_runtime_flow
from banksia.runtime.post_commit import (
    CommandRunCancellationRequested,
    DispatchCleanupRequested,
    HumanRequestTerminal,
    RuntimeEffectPublisher,
    RuntimeEffectSignal,
)
from banksia.runtime.task_events import append_task_event

logger = logging.getLogger(__name__)


async def pause_flow(
    session: AsyncSession,
    task_id: str,
    *,
    expected_active_flow_revision_id: str,
    expected_control_revision: int,
    actor_ref: str | None = None,
    event_source: TaskEventSource = TaskEventSource.CONTROL_API,
    runtime_effect_publisher: RuntimeEffectPublisher | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> RuntimeFlowPauseResponse:
    """Pause one exact running flow while retaining any external wait."""

    flow = await _read_control_flow(session, task_id)
    _require_control_snapshot(
        flow,
        expected_active_flow_revision_id=expected_active_flow_revision_id,
        expected_control_revision=expected_control_revision,
        allowed_statuses={"running"},
    )
    paused_at = clock()
    changed = await _update_flow_to_paused(
        session,
        flow=flow,
        expected_control_revision=expected_control_revision,
        actor_ref=actor_ref,
        paused_at=paused_at,
    )
    if not changed:
        await session.rollback()
        raise _flow_control_conflict("another controller transition won before pause")
    closed_dispatch_ids = await _close_current_dispatches(
        session,
        flow=flow,
        closed_reason="paused",
        closed_at=paused_at,
    )
    await append_task_event(
        session,
        task_id=flow.task_id,
        event_type=TaskEventType.TASK_PAUSED,
        event_source=event_source,
        occurred_at=paused_at,
        flow_revision_id=expected_active_flow_revision_id,
        dispatch_id=_single_dispatch_id(closed_dispatch_ids),
        actor_ref=actor_ref,
        payload={
            "pause_reason": "paused_by_operator",
            "control_revision": expected_control_revision + 1,
            "actor_ref": actor_ref,
            "summary": "Paused by operator.",
        },
    )
    await _commit_or_rollback(session)
    _publish_cleanups(runtime_effect_publisher, closed_dispatch_ids)
    return RuntimeFlowPauseResponse(flow=await read_runtime_flow(session, task_id))


async def continue_flow(
    session: AsyncSession,
    task_id: str,
    *,
    expected_active_flow_revision_id: str,
    expected_control_revision: int,
    dependencies: DispatchOpeningDependencies,
    actor_ref: str | None = None,
    event_source: TaskEventSource = TaskEventSource.CONTROL_API,
) -> RuntimeFlowRead:
    """Open one exact paused-flow successor before returning."""

    flow = await _read_control_flow(session, task_id)
    _require_control_snapshot(
        flow,
        expected_active_flow_revision_id=expected_active_flow_revision_id,
        expected_control_revision=expected_control_revision,
        allowed_statuses={"paused"},
    )
    result = await continue_paused_flow(
        session,
        task_id=task_id,
        expected_active_flow_revision_id=expected_active_flow_revision_id,
        expected_control_revision=expected_control_revision,
        dependencies=dependencies,
        resume_event=TaskResumeEventBasis(
            control_revision=expected_control_revision + 1,
            actor_ref=actor_ref,
            event_source=event_source,
        ),
    )
    if result.outcome != "opened" or result.dispatch_id is None:
        raise _flow_control_conflict("paused flow did not open one successor")
    return await read_runtime_flow(session, task_id)


async def cancel_flow(
    session: AsyncSession,
    task_id: str,
    *,
    expected_active_flow_revision_id: str,
    expected_control_revision: int,
    actor_ref: str | None = None,
    event_source: TaskEventSource = TaskEventSource.CONTROL_API,
    runtime_effect_publisher: RuntimeEffectPublisher | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> RuntimeFlowRead:
    """Cancel one exact nonterminal flow without opening a successor."""

    flow = await _read_control_flow(session, task_id)
    _require_control_snapshot(
        flow,
        expected_active_flow_revision_id=expected_active_flow_revision_id,
        expected_control_revision=expected_control_revision,
        allowed_statuses={"running", "paused"},
    )
    cancelled_at = clock()
    changed = await _update_flow_to_cancelled(
        session,
        flow=flow,
        expected_control_revision=expected_control_revision,
        cancelled_at=cancelled_at,
    )
    if not changed:
        await session.rollback()
        raise _flow_control_conflict("another controller transition won before cancellation")
    closed_dispatch_ids = await _close_current_dispatches(
        session,
        flow=flow,
        closed_reason="cancelled",
        closed_at=cancelled_at,
    )
    cancellation_signals = await cancel_attempt_waits(
        session,
        flow=flow,
        actor_ref=actor_ref,
        event_source=event_source,
        cancelled_at=cancelled_at,
    )
    await cancel_execution_rows(session, flow=flow, cancelled_at=cancelled_at)
    await _cancel_pending_replan_transition(
        session,
        flow=flow,
        cancelled_at=cancelled_at,
    )
    await append_task_event(
        session,
        task_id=flow.task_id,
        event_type=TaskEventType.TASK_CANCELLED,
        event_source=event_source,
        occurred_at=cancelled_at,
        flow_revision_id=expected_active_flow_revision_id,
        dispatch_id=_single_dispatch_id(closed_dispatch_ids),
        actor_ref=actor_ref,
        payload={
            "control_revision": expected_control_revision + 1,
            "actor_ref": actor_ref,
            "summary": "Cancelled by operator.",
        },
    )
    await _commit_or_rollback(session)
    _publish_cleanups(runtime_effect_publisher, closed_dispatch_ids)
    for human_signal in cancellation_signals.human:
        _publish_human_terminal(runtime_effect_publisher, human_signal)
    for command_signal in cancellation_signals.command:
        _publish_command_cancellation(runtime_effect_publisher, command_signal)
    return await read_runtime_flow(session, task_id)


async def _read_control_flow(session: AsyncSession, task_id: str) -> FlowModel:
    flow = await session.scalar(
        select(FlowModel)
        .options(raiseload("*"))
        .where(FlowModel.task_id == task_id)
        .execution_options(populate_existing=True)
    )
    if flow is None:
        raise missing_resource_error(f"unknown task_id '{task_id}'")
    return flow


def _require_control_snapshot(
    flow: FlowModel,
    *,
    expected_active_flow_revision_id: str,
    expected_control_revision: int,
    allowed_statuses: set[str],
) -> None:
    if flow.active_flow_revision_id != expected_active_flow_revision_id:
        raise stale_flow_revision_error("the active flow revision changed before control")
    if flow.control_revision != expected_control_revision:
        raise _flow_control_conflict("the flow control revision changed before control")
    if flow.status not in allowed_statuses:
        raise _flow_control_conflict(f"flow cannot be controlled from status '{flow.status}'")


async def _close_current_dispatches(
    session: AsyncSession,
    *,
    flow: FlowModel,
    closed_reason: str,
    closed_at: datetime,
) -> tuple[str, ...]:
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
                & (DispatchTurnModel.flow_id == AttemptModel.flow_id)
                & (DispatchTurnModel.assignment_id == AttemptModel.assignment_id)
                & (DispatchTurnModel.attempt_id == AttemptModel.attempt_id)
                & (DispatchTurnModel.dispatch_id == AttemptModel.current_dispatch_id),
            )
            .where(
                AttemptModel.task_id == flow.task_id,
                AttemptModel.flow_id == flow.flow_id,
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
    closed_ids: list[str] = []
    for assignment_id, attempt_id, dispatch_id in rows:
        closed_dispatch_id = await session.scalar(
            update(DispatchTurnModel)
            .where(
                DispatchTurnModel.dispatch_id == dispatch_id,
                DispatchTurnModel.task_id == flow.task_id,
                DispatchTurnModel.flow_id == flow.flow_id,
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
            await session.rollback()
            raise _flow_control_conflict("a current Attempt dispatch changed before control")
        cleared_attempt_id = await session.scalar(
            update(AttemptModel)
            .where(
                AttemptModel.task_id == flow.task_id,
                AttemptModel.flow_id == flow.flow_id,
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
            await session.rollback()
            raise _flow_control_conflict("a current Attempt dispatch changed before control")
        closed_ids.append(closed_dispatch_id)
    unsettled_attempt_id = await session.scalar(
        select(AttemptModel.attempt_id)
        .where(
            AttemptModel.task_id == flow.task_id,
            AttemptModel.flow_id == flow.flow_id,
            AttemptModel.status == "running",
            AttemptModel.current_dispatch_id.is_not(None),
        )
        .limit(1)
    )
    if unsettled_attempt_id is not None:
        await session.rollback()
        raise _flow_control_conflict("control did not settle every current Attempt dispatch")
    return tuple(closed_ids)


async def _update_flow_to_paused(
    session: AsyncSession,
    *,
    flow: FlowModel,
    expected_control_revision: int,
    actor_ref: str | None,
    paused_at: datetime,
) -> bool:
    return bool(
        await session.scalar(
            update(FlowModel)
            .where(*_flow_snapshot_conditions(flow, expected_control_revision))
            .values(
                status="paused",
                pause_reason="paused_by_operator",
                pause_details={"summary": "Paused by operator."},
                paused_at=paused_at,
                paused_by_actor_ref=actor_ref,
                control_revision=FlowModel.control_revision + 1,
                updated_at=paused_at,
            )
            .returning(FlowModel.flow_id)
        )
    )


async def _update_flow_to_cancelled(
    session: AsyncSession,
    *,
    flow: FlowModel,
    expected_control_revision: int,
    cancelled_at: datetime,
) -> bool:
    return bool(
        await session.scalar(
            update(FlowModel)
            .where(*_flow_snapshot_conditions(flow, expected_control_revision))
            .values(
                status="cancelled",
                terminal_outcome=None,
                pause_reason=None,
                pause_details=None,
                paused_at=None,
                paused_by_actor_ref=None,
                control_revision=FlowModel.control_revision + 1,
                updated_at=cancelled_at,
            )
            .returning(FlowModel.flow_id)
        )
    )


async def _cancel_pending_replan_transition(
    session: AsyncSession,
    *,
    flow: FlowModel,
    cancelled_at: datetime,
) -> None:
    await session.execute(
        update(ReplanTransitionModel)
        .where(
            ReplanTransitionModel.task_id == flow.task_id,
            ReplanTransitionModel.flow_id == flow.flow_id,
            ReplanTransitionModel.successor_flow_revision_id == flow.active_flow_revision_id,
            ReplanTransitionModel.successor_state.not_in(("opened", "cancelled")),
            ReplanTransitionModel.successor_dispatch_id.is_(None),
        )
        .values(
            successor_state="cancelled",
            failure_code=case(
                (
                    ReplanTransitionModel.manifest_state == "repair_required",
                    ReplanTransitionModel.failure_code,
                ),
                else_=None,
            ),
            failure_detail=case(
                (
                    ReplanTransitionModel.manifest_state == "repair_required",
                    ReplanTransitionModel.failure_detail,
                ),
                else_=None,
            ),
            updated_at=cancelled_at,
        )
    )


def _flow_snapshot_conditions(
    flow: FlowModel, expected_control_revision: int
) -> tuple[ColumnElement[bool], ...]:
    return (
        FlowModel.flow_id == flow.flow_id,
        FlowModel.task_id == flow.task_id,
        FlowModel.status == flow.status,
        FlowModel.active_flow_revision_id == flow.active_flow_revision_id,
        FlowModel.control_revision == expected_control_revision,
    )


async def _commit_or_rollback(session: AsyncSession) -> None:
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise


def _publish_cleanups(
    publisher: RuntimeEffectPublisher | None,
    dispatch_ids: tuple[str, ...],
) -> None:
    if publisher is None:
        return
    for dispatch_id in dispatch_ids:
        _publish_effect(publisher, DispatchCleanupRequested(dispatch_id=dispatch_id))


def _single_dispatch_id(dispatch_ids: tuple[str, ...]) -> str | None:
    if len(dispatch_ids) != 1:
        return None
    return dispatch_ids[0]


def _publish_command_cancellation(
    publisher: RuntimeEffectPublisher | None,
    signal: CommandRunCancellationRequested | None,
) -> None:
    if publisher is None or signal is None:
        return
    _publish_effect(publisher, signal)


def _publish_human_terminal(
    publisher: RuntimeEffectPublisher | None,
    signal: HumanRequestTerminal | None,
) -> None:
    if publisher is None or signal is None:
        return
    _publish_effect(publisher, signal)


def _publish_effect(publisher: RuntimeEffectPublisher, signal: RuntimeEffectSignal) -> None:
    try:
        publisher.publish(signal)
    except Exception:
        logger.exception("post-commit flow-control signal publication failed")


def _flow_control_conflict(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary=summary,
        is_retryable=False,
        suggested_next_step="Reread the task and retry only against its current revisions.",
    )


__all__ = ["cancel_flow", "continue_flow", "pause_flow"]
