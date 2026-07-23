from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentDecisionModel,
    AssignmentModel,
    FlowModel,
)
from banksia.runtime.boundary.source_transition import advance_accepted_boundary_state
from banksia.runtime.checkpoint import commit_checkpoint
from banksia.runtime.clock import utc_now
from banksia.runtime.contracts import (
    BoundaryRead,
    CheckpointRequest,
    EgressBoundary,
    TaskEventSource,
    TaskEventType,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.node_operations.contracts import (
    NodeOperationName,
    OpenHumanRequestRequest,
    ReturnBoundaryRequest,
    StartCommandRunRequest,
)
from banksia.runtime.node_operations.external_wait_handlers import (
    open_human_request,
    start_command_run,
)
from banksia.runtime.node_operations.result_reads import runtime_flow_read
from banksia.runtime.node_operations.source_transitions import close_source_dispatch
from banksia.runtime.task_events import append_task_event


async def execute_controller_node_operation(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    operation_name: NodeOperationName,
    request: BaseModel,
    *,
    dispatch_opening_dependencies: DispatchOpeningDependencies | None = None,
) -> BaseModel:
    if operation_name == NodeOperationName.CHECKPOINT:
        assert isinstance(request, CheckpointRequest)
        return await commit_checkpoint(session, authority, request)
    if operation_name == NodeOperationName.RETURN_BOUNDARY:
        assert isinstance(request, ReturnBoundaryRequest)
        return await _return_yield_boundary(session, authority, request)
    if operation_name == NodeOperationName.OPEN_HUMAN_REQUEST:
        assert isinstance(request, OpenHumanRequestRequest)
        return await open_human_request(session, authority, request)
    if operation_name == NodeOperationName.START_COMMAND_RUN:
        assert isinstance(request, StartCommandRunRequest)
        return await start_command_run(session, authority, request)

    from banksia.runtime.node_operations.structural_handlers import (
        execute_structural_node_operation,
    )

    return await execute_structural_node_operation(
        session,
        authority,
        operation_name,
        request,
        dispatch_opening_dependencies=dispatch_opening_dependencies,
    )


async def _return_yield_boundary(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    request: ReturnBoundaryRequest,
) -> BoundaryRead:
    if request.boundary != "yield":
        raise RuntimeOperationError(
            code=OperationFailureCode.INVALID_REQUEST_SHAPE,
            summary="return_boundary is a migration-only staged-child yield",
            is_retryable=False,
        )
    decision = await session.scalar(
        select(AssignmentDecisionModel).where(
            AssignmentDecisionModel.source_dispatch_id == authority.dispatch_id,
            AssignmentDecisionModel.decision_kind == "staged_child",
        )
    )
    if decision is None:
        raise RuntimeOperationError(
            code=OperationFailureCode.BOUNDARY_PRECONDITION_FAILED,
            summary="yield requires the exact staged-child decision",
            is_retryable=False,
        )
    now = utc_now()
    await close_source_dispatch(
        session,
        authority,
        now=now,
        closed_reason="boundary",
        waiting_cause="none",
        waiting_source_id=None,
    )
    await advance_accepted_boundary_state(
        session,
        authority,
        outcome="yield",
        decision=decision,
        transitioned_at=now,
    )
    session.add(
        AcceptedBoundaryModel(
            accepted_boundary_id=f"accepted-boundary.{authority.dispatch_id}",
            source_dispatch_id=authority.dispatch_id,
            task_id=authority.task_id,
            flow_id=authority.flow_id,
            assignment_id=authority.assignment_id,
            attempt_id=authority.attempt_id,
            outcome="yield",
            checkpoint_id=None,
            assignment_decision_id=decision.assignment_decision_id,
            committed_at=now,
        )
    )
    resulting_flow_status = await session.scalar(
        select(FlowModel.status).where(FlowModel.flow_id == authority.flow_id)
    )
    if resulting_flow_status is None:
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="yield lost its Flow",
            is_retryable=False,
        )
    await append_task_event(
        session,
        task_id=authority.task_id,
        event_type=TaskEventType.BOUNDARY_ACCEPTED,
        event_source=TaskEventSource.NODE,
        occurred_at=now,
        flow_revision_id=authority.flow_revision_id,
        dispatch_id=authority.dispatch_id,
        attempt_id=authority.attempt_id,
        node_key=authority.node_key,
        payload={
            "source_dispatch_id": authority.dispatch_id,
            "assignment_id": authority.assignment_id,
            "attempt_id": authority.attempt_id,
            "outcome": "yield",
            "checkpoint_id": None,
            "assignment_decision_id": decision.assignment_decision_id,
            "resulting_flow_status": resulting_flow_status,
        },
    )
    await _append_child_assignment_committed_event(
        session,
        authority,
        decision=decision,
        occurred_at=now,
    )
    await session.commit()
    flow = await runtime_flow_read(session, authority)
    return BoundaryRead(
        accepted_boundary=EgressBoundary.YIELD,
        flow=flow,
    )


async def _append_child_assignment_committed_event(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    decision: AssignmentDecisionModel,
    occurred_at: datetime,
) -> None:
    child_assignment_id = decision.staged_child_assignment_id
    child_attempt_id = decision.staged_child_attempt_id
    child_node_key = await session.scalar(
        select(AssignmentModel.node_key).where(AssignmentModel.assignment_id == child_assignment_id)
    )
    if child_node_key is None:
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="staged child assignment disappeared before yield",
            is_retryable=False,
        )
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


__all__ = ["execute_controller_node_operation"]
