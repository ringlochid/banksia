from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentDecisionModel,
    AssignmentModel,
    AttemptCheckpointModel,
    FlowModel,
)
from autoclaw.runtime.boundary.source_transition import advance_accepted_boundary_state
from autoclaw.runtime.checkpoint import (
    CheckpointPreparation,
    commit_checkpoint_preparation,
    empty_checkpoint_preparation,
    read_exact_latest_checkpoint,
)
from autoclaw.runtime.clock import utc_now
from autoclaw.runtime.contracts import (
    BoundaryRead,
    CheckpointFileRef,
    CheckpointRead,
    TaskEventSource,
    TaskEventType,
)
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.dispatch.authority import NodeOperationAuthority
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.node_operations.contracts import (
    NodeOperationName,
    OpenHumanRequestRequest,
    RecordCheckpointRequest,
    ReturnBoundaryRequest,
    StartCommandRunRequest,
)
from autoclaw.runtime.node_operations.external_wait_handlers import (
    open_human_request,
    start_command_run,
)
from autoclaw.runtime.node_operations.result_reads import runtime_flow_read
from autoclaw.runtime.node_operations.source_transitions import close_source_dispatch
from autoclaw.runtime.task_events import append_task_event


async def execute_controller_node_operation(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    operation_name: NodeOperationName,
    request: BaseModel,
    *,
    checkpoint_preparation: CheckpointPreparation | None = None,
) -> BaseModel:
    if operation_name == NodeOperationName.RECORD_CHECKPOINT:
        assert isinstance(request, RecordCheckpointRequest)
        return await _record_checkpoint(
            session,
            authority,
            request,
            preparation=checkpoint_preparation,
        )
    if operation_name == NodeOperationName.RETURN_BOUNDARY:
        assert isinstance(request, ReturnBoundaryRequest)
        return await _return_boundary(session, authority, request)
    if operation_name == NodeOperationName.OPEN_HUMAN_REQUEST:
        assert isinstance(request, OpenHumanRequestRequest)
        return await open_human_request(session, authority, request)
    if operation_name == NodeOperationName.START_COMMAND_RUN:
        assert isinstance(request, StartCommandRunRequest)
        return await start_command_run(session, authority, request)

    from autoclaw.runtime.node_operations.structural_handlers import (
        execute_structural_node_operation,
    )

    return await execute_structural_node_operation(
        session,
        authority,
        operation_name,
        request,
    )


async def _record_checkpoint(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    request: RecordCheckpointRequest,
    *,
    preparation: CheckpointPreparation | None,
) -> CheckpointRead:
    body = request.checkpoint
    prepared = preparation or empty_checkpoint_preparation(authority, body)
    if prepared.body != body:
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="prepared checkpoint does not match the accepted request",
            is_retryable=False,
        )
    await commit_checkpoint_preparation(session, authority, prepared)
    checkpoint_ref = CheckpointFileRef(
        path=Path(f"_runtime/attempts/{authority.attempt_id}/latest-checkpoint.md"),
        description="Latest checkpoint projection for the current attempt.",
    )
    return CheckpointRead(
        attempt_id=authority.attempt_id,
        checkpoint_id=prepared.checkpoint_id,
        checkpoint_ref=checkpoint_ref,
        latest_checkpoint_ref=checkpoint_ref,
    )


async def _return_boundary(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    request: ReturnBoundaryRequest,
) -> BoundaryRead:
    outcome = request.boundary.value
    checkpoint = await _require_boundary_checkpoint(session, authority, outcome=outcome)
    decision = await _read_boundary_decision(session, authority, outcome=outcome)
    now = utc_now()
    await _persist_boundary_acceptance(
        session,
        authority,
        outcome=outcome,
        checkpoint=checkpoint,
        decision=decision,
        accepted_at=now,
    )
    resulting_flow_status = await _read_resulting_flow_status(session, authority)
    await _append_boundary_accepted_event(
        session,
        authority,
        outcome=outcome,
        checkpoint=checkpoint,
        decision=decision,
        resulting_flow_status=resulting_flow_status,
        occurred_at=now,
    )
    await _append_child_assignment_committed_event(
        session,
        authority,
        outcome=outcome,
        decision=decision,
        occurred_at=now,
    )
    await session.commit()
    return await _build_boundary_read(session, authority, request, checkpoint=checkpoint)


async def _require_boundary_checkpoint(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    outcome: str,
) -> AttemptCheckpointModel | None:
    checkpoint = await _latest_checkpoint(session, authority)
    if outcome != "yield" and (checkpoint is None or checkpoint.outcome != outcome):
        raise RuntimeOperationError(
            code=OperationFailureCode.BOUNDARY_PRECONDITION_FAILED,
            summary=f"{outcome} requires a matching terminal checkpoint",
            is_retryable=False,
        )
    return checkpoint


async def _read_boundary_decision(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    outcome: str,
) -> AssignmentDecisionModel | None:
    decision = await session.scalar(
        select(AssignmentDecisionModel).where(
            AssignmentDecisionModel.source_dispatch_id == authority.dispatch_id
        )
    )
    _validate_boundary_decision(authority, outcome, decision)
    return decision


async def _persist_boundary_acceptance(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    outcome: str,
    checkpoint: AttemptCheckpointModel | None,
    decision: AssignmentDecisionModel | None,
    accepted_at: datetime,
) -> None:
    await close_source_dispatch(
        session,
        authority,
        now=accepted_at,
        closed_reason="boundary",
        waiting_cause="none",
        waiting_source_id=None,
    )
    await advance_accepted_boundary_state(
        session,
        authority,
        outcome=outcome,
        decision=decision,
        transitioned_at=accepted_at,
    )
    session.add(
        AcceptedBoundaryModel(
            accepted_boundary_id=f"accepted-boundary.{authority.dispatch_id}",
            source_dispatch_id=authority.dispatch_id,
            task_id=authority.task_id,
            flow_id=authority.flow_id,
            assignment_id=authority.assignment_id,
            attempt_id=authority.attempt_id,
            outcome=outcome,
            checkpoint_id=checkpoint.checkpoint_id if checkpoint is not None else None,
            assignment_decision_id=(
                decision.assignment_decision_id if decision is not None else None
            ),
        )
    )


async def _read_resulting_flow_status(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> str:
    resulting_flow_status = await session.scalar(
        select(FlowModel.status).where(FlowModel.flow_id == authority.flow_id)
    )
    assert resulting_flow_status is not None
    return resulting_flow_status


async def _append_boundary_accepted_event(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    outcome: str,
    checkpoint: AttemptCheckpointModel | None,
    decision: AssignmentDecisionModel | None,
    resulting_flow_status: str,
    occurred_at: datetime,
) -> None:
    checkpoint_ref_path = (
        f"_runtime/attempts/{authority.attempt_id}/latest-checkpoint.md"
        if checkpoint is not None
        else None
    )
    await append_task_event(
        session,
        task_id=authority.task_id,
        event_type=TaskEventType.BOUNDARY_ACCEPTED,
        event_source=TaskEventSource.NODE,
        occurred_at=occurred_at,
        flow_revision_id=authority.flow_revision_id,
        dispatch_id=authority.dispatch_id,
        attempt_id=authority.attempt_id,
        node_key=authority.node_key,
        payload={
            "source_dispatch_id": authority.dispatch_id,
            "assignment_id": authority.assignment_id,
            "attempt_id": authority.attempt_id,
            "outcome": outcome,
            "checkpoint_id": checkpoint.checkpoint_id if checkpoint is not None else None,
            "checkpoint_ref": checkpoint_ref_path,
            "assignment_decision_id": (
                decision.assignment_decision_id if decision is not None else None
            ),
            "resulting_flow_status": resulting_flow_status,
        },
    )


async def _append_child_assignment_committed_event(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    outcome: str,
    decision: AssignmentDecisionModel | None,
    occurred_at: datetime,
) -> None:
    if outcome != "yield" or decision is None:
        return
    child_assignment_id = decision.staged_child_assignment_id
    child_attempt_id = decision.staged_child_attempt_id
    assert child_assignment_id is not None and child_attempt_id is not None
    child_node_key = await session.scalar(
        select(AssignmentModel.node_key).where(AssignmentModel.assignment_id == child_assignment_id)
    )
    assert child_node_key is not None
    await append_task_event(
        session,
        task_id=authority.task_id,
        event_type=TaskEventType.CHILD_ASSIGNMENT_COMMITTED,
        event_source=TaskEventSource.NODE,
        occurred_at=occurred_at,
        flow_revision_id=authority.flow_revision_id,
        dispatch_id=authority.dispatch_id,
        attempt_id=child_attempt_id,
        node_key=child_node_key,
        payload={
            "source_dispatch_id": authority.dispatch_id,
            "parent_assignment_id": authority.assignment_id,
            "child_assignment_id": child_assignment_id,
            "child_attempt_id": child_attempt_id,
            "child_node_key": child_node_key,
            "flow_revision_id": authority.flow_revision_id,
        },
    )


async def _build_boundary_read(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    request: ReturnBoundaryRequest,
    *,
    checkpoint: AttemptCheckpointModel | None,
) -> BoundaryRead:
    flow = await runtime_flow_read(session, authority)
    checkpoint_ref = (
        CheckpointFileRef(
            path=Path(f"_runtime/attempts/{authority.attempt_id}/latest-checkpoint.md"),
            description="Latest checkpoint projection for the source attempt.",
        )
        if checkpoint is not None
        else None
    )
    return BoundaryRead(
        accepted_boundary=request.boundary,
        flow=flow,
        latest_checkpoint_ref=checkpoint_ref,
    )


async def _latest_checkpoint(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> AttemptCheckpointModel | None:
    return await read_exact_latest_checkpoint(session, authority)


def _validate_boundary_decision(
    authority: NodeOperationAuthority,
    outcome: str,
    decision: AssignmentDecisionModel | None,
) -> None:
    expected: str | None = None
    if outcome == "yield":
        expected = "staged_child"
    elif outcome == "green" and authority.node_kind.value in {"parent", "root"}:
        expected = "release_green"
    elif outcome == "blocked" and authority.node_kind.value == "root":
        expected = "release_blocked"
    elif outcome == "retry" and authority.node_kind.value != "worker":
        raise RuntimeOperationError(
            code=OperationFailureCode.ILLEGAL_CALLER,
            summary="only workers may return retry",
            is_retryable=False,
        )
    if expected is None:
        return
    if decision is None or decision.decision_kind != expected:
        raise RuntimeOperationError(
            code=OperationFailureCode.BOUNDARY_PRECONDITION_FAILED,
            summary=f"{outcome} requires a current {expected} decision",
            is_retryable=False,
        )


__all__ = ["execute_controller_node_operation"]
