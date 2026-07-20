from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.persistence.models import (
    AssignmentDecisionModel,
    AssignmentModel,
    AttemptModel,
    FlowModel,
    FlowNodeModel,
)
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.dispatch.authority import NodeOperationAuthority
from autoclaw.runtime.errors import RuntimeOperationError, budget_exhausted_error


async def advance_accepted_boundary_state(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    outcome: str,
    decision: AssignmentDecisionModel | None,
    transitioned_at: datetime,
) -> None:
    """Apply the semantic transition owned by one accepted boundary transaction."""

    if outcome == "yield":
        if decision is None:
            raise _conflict("yield is missing its exact staged-child decision")
        await _activate_staged_child(
            session,
            authority,
            decision=decision,
        )
        return

    await _complete_source_attempt(
        session,
        authority,
        outcome=outcome,
        transitioned_at=transitioned_at,
    )
    source_assignment = await _read_source_assignment(session, authority)
    if outcome == "retry":
        await _start_semantic_retry(
            session,
            authority,
            source_assignment=source_assignment,
            transitioned_at=transitioned_at,
        )
        return
    await _finish_source_node(
        session,
        authority,
        outcome=outcome,
    )
    if source_assignment.parent_assignment_id is not None:
        await _resume_parent(
            session,
            authority,
            parent_assignment_id=source_assignment.parent_assignment_id,
        )
        return
    if authority.node_kind.value != "root":
        raise _conflict("a non-root terminal boundary is missing parent assignment lineage")
    await _complete_root_flow(
        session,
        authority,
        outcome=outcome,
        transitioned_at=transitioned_at,
    )


async def _activate_staged_child(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    decision: AssignmentDecisionModel,
) -> None:
    child_assignment_id = decision.staged_child_assignment_id
    child_attempt_id = decision.staged_child_attempt_id
    if child_assignment_id is None or child_attempt_id is None:
        raise _conflict("staged-child decision is missing its exact child identity")
    child = await session.scalar(
        select(AssignmentModel).where(
            AssignmentModel.assignment_id == child_assignment_id,
            AssignmentModel.task_id == authority.task_id,
            AssignmentModel.flow_id == authority.flow_id,
            AssignmentModel.flow_revision_id == authority.flow_revision_id,
            AssignmentModel.parent_assignment_id == authority.assignment_id,
            AssignmentModel.created_by_dispatch_id == authority.dispatch_id,
            AssignmentModel.current_attempt_id == child_attempt_id,
            AssignmentModel.superseded_at.is_(None),
        )
    )
    if child is None:
        raise _conflict("staged child no longer matches its accepted source decision")
    await _change_node_state(
        session,
        flow_node_id=authority.flow_node.flow_node_id,
        assignment_id=authority.assignment_id,
        from_state="running",
        to_state="waiting",
    )
    await _change_node_state(
        session,
        flow_node_id=child.flow_node_id,
        assignment_id=child.assignment_id,
        from_state="waiting",
        to_state="running",
    )
    activated = await session.scalar(
        update(AttemptModel)
        .where(
            AttemptModel.attempt_id == child_attempt_id,
            AttemptModel.assignment_id == child_assignment_id,
            AttemptModel.task_id == authority.task_id,
            AttemptModel.flow_id == authority.flow_id,
            AttemptModel.node_key == child.node_key,
            AttemptModel.status == "pending",
        )
        .values(status="running")
        .returning(AttemptModel.attempt_id)
    )
    if activated is None:
        raise _conflict("staged child attempt is no longer pending")


async def _complete_source_attempt(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    outcome: str,
    transitioned_at: datetime,
) -> None:
    completed = await session.scalar(
        update(AttemptModel)
        .where(
            AttemptModel.attempt_id == authority.attempt_id,
            AttemptModel.assignment_id == authority.assignment_id,
            AttemptModel.task_id == authority.task_id,
            AttemptModel.flow_id == authority.flow_id,
            AttemptModel.node_key == authority.node_key,
            AttemptModel.status.in_(("pending", "running")),
        )
        .values(
            status="completed",
            terminal_outcome=outcome,
            closed_at=transitioned_at,
        )
        .returning(AttemptModel.attempt_id)
    )
    if completed is None:
        raise _conflict("source attempt is no longer active")


async def _read_source_assignment(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> AssignmentModel:
    source = await session.scalar(
        select(AssignmentModel).where(
            AssignmentModel.assignment_id == authority.assignment_id,
            AssignmentModel.task_id == authority.task_id,
            AssignmentModel.flow_id == authority.flow_id,
            AssignmentModel.flow_revision_id == authority.flow_revision_id,
            AssignmentModel.flow_node_id == authority.flow_node.flow_node_id,
            AssignmentModel.node_key == authority.node_key,
            AssignmentModel.current_attempt_id == authority.attempt_id,
            AssignmentModel.superseded_at.is_(None),
        )
    )
    if source is None:
        raise _conflict("source assignment is no longer current")
    return source


async def _start_semantic_retry(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    source_assignment: AssignmentModel,
    transitioned_at: datetime,
) -> None:
    if source_assignment.retries_remaining is not None and source_assignment.retries_remaining <= 0:
        raise budget_exhausted_error("the current assignment has no semantic retries remaining")
    retry_attempt_id = f"attempt.{authority.task_id}.{authority.node_key}.{uuid4().hex}"
    session.add(
        AttemptModel(
            attempt_id=retry_attempt_id,
            assignment_id=authority.assignment_id,
            task_id=authority.task_id,
            flow_id=authority.flow_id,
            node_key=authority.node_key,
            retry_of_attempt_id=authority.attempt_id,
            latest_checkpoint_id=None,
            status="running",
            opened_at=transitioned_at,
        )
    )
    await session.flush()
    changed = await session.scalar(
        update(AssignmentModel)
        .where(
            AssignmentModel.assignment_id == authority.assignment_id,
            AssignmentModel.task_id == authority.task_id,
            AssignmentModel.flow_id == authority.flow_id,
            AssignmentModel.flow_revision_id == authority.flow_revision_id,
            AssignmentModel.current_attempt_id == authority.attempt_id,
            AssignmentModel.superseded_at.is_(None),
            (AssignmentModel.retries_remaining.is_(None)) | (AssignmentModel.retries_remaining > 0),
        )
        .values(
            current_attempt_id=retry_attempt_id,
            retries_remaining=case(
                (
                    AssignmentModel.retries_remaining.is_not(None),
                    AssignmentModel.retries_remaining - 1,
                ),
                else_=None,
            ),
        )
        .returning(AssignmentModel.assignment_id)
    )
    if changed is None:
        raise _conflict("another transition changed semantic retry authority")


async def _finish_source_node(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    outcome: str,
) -> None:
    await _change_node_state(
        session,
        flow_node_id=authority.flow_node.flow_node_id,
        assignment_id=authority.assignment_id,
        from_state="running",
        to_state="done" if outcome == "green" else "failed",
    )


async def _resume_parent(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    parent_assignment_id: str,
) -> None:
    parent = await session.scalar(
        select(AssignmentModel).where(
            AssignmentModel.assignment_id == parent_assignment_id,
            AssignmentModel.task_id == authority.task_id,
            AssignmentModel.flow_id == authority.flow_id,
            AssignmentModel.flow_revision_id == authority.flow_revision_id,
            AssignmentModel.superseded_at.is_(None),
        )
    )
    if parent is None or parent.current_attempt_id is None:
        raise _conflict("child return is missing its current parent assignment")
    parent_attempt_is_active = await session.scalar(
        select(AttemptModel.attempt_id).where(
            AttemptModel.attempt_id == parent.current_attempt_id,
            AttemptModel.assignment_id == parent.assignment_id,
            AttemptModel.task_id == authority.task_id,
            AttemptModel.flow_id == authority.flow_id,
            AttemptModel.status.in_(("pending", "running")),
        )
    )
    if parent_attempt_is_active is None:
        raise _conflict("child return parent attempt is no longer active")
    resumed = await session.scalar(
        update(FlowNodeModel)
        .where(
            FlowNodeModel.flow_node_id == parent.flow_node_id,
            FlowNodeModel.flow_id == authority.flow_id,
            FlowNodeModel.flow_revision_id == authority.flow_revision_id,
            FlowNodeModel.current_assignment_id == parent.assignment_id,
            FlowNodeModel.state.in_(("waiting", "running")),
        )
        .values(state="running")
        .returning(FlowNodeModel.flow_node_id)
    )
    if resumed is None:
        raise _conflict("parent node is no longer eligible for child return")


async def _complete_root_flow(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    outcome: str,
    transitioned_at: datetime,
) -> None:
    completed = await session.scalar(
        update(FlowModel)
        .where(
            FlowModel.flow_id == authority.flow_id,
            FlowModel.task_id == authority.task_id,
            FlowModel.status == "running",
            FlowModel.active_flow_revision_id == authority.flow_revision_id,
            FlowModel.current_dispatch_id.is_(None),
            FlowModel.waiting_cause == "none",
        )
        .values(
            status="completed",
            terminal_outcome=outcome,
            updated_at=transitioned_at,
        )
        .returning(FlowModel.flow_id)
    )
    if completed is None:
        raise _conflict("root flow is no longer eligible for terminal completion")


async def _change_node_state(
    session: AsyncSession,
    *,
    flow_node_id: str,
    assignment_id: str,
    from_state: str,
    to_state: str,
) -> None:
    changed = await session.scalar(
        update(FlowNodeModel)
        .where(
            FlowNodeModel.flow_node_id == flow_node_id,
            FlowNodeModel.current_assignment_id == assignment_id,
            FlowNodeModel.state == from_state,
        )
        .values(state=to_state)
        .returning(FlowNodeModel.flow_node_id)
    )
    if changed is None:
        raise _conflict(f"runtime node is no longer {from_state}")


def _conflict(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary=summary,
        is_retryable=False,
    )


__all__ = ["advance_accepted_boundary_state"]
