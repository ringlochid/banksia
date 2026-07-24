from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, delete, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AssignmentDecisionModel,
    AssignmentModel,
    AttemptModel,
    AttemptWaitModel,
    FlowModel,
    FlowNodeModel,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.dispatch.currentness import (
    AttemptWaitIdentity,
    clear_current_attempt_wait,
)
from banksia.runtime.errors import RuntimeOperationError, budget_exhausted_error


async def advance_accepted_boundary_state(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    outcome: str,
    decision: AssignmentDecisionModel | None,
    transitioned_at: datetime,
    retry_attempt_id: str | None = None,
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
        if retry_attempt_id is None:
            raise _conflict("semantic retry is missing its replacement Attempt identity")
        await _start_semantic_retry(
            session,
            authority,
            source_assignment=source_assignment,
            retry_attempt_id=retry_attempt_id,
            transitioned_at=transitioned_at,
        )
        return
    if retry_attempt_id is not None:
        raise _conflict("a non-retry boundary cannot select a replacement Attempt")
    await _complete_source_assignment(
        session,
        authority,
        outcome=outcome,
        transitioned_at=transitioned_at,
    )
    await _finish_source_node(
        session,
        authority,
        outcome=outcome,
    )
    if source_assignment.parent_assignment_id is not None:
        await _resume_parent(
            session,
            authority,
            source_assignment=source_assignment,
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
            AssignmentModel.parent_assignment_id == authority.assignment_id,
            AssignmentModel.created_by_dispatch_id == authority.dispatch_id,
            AssignmentModel.current_attempt_id == child_attempt_id,
            AssignmentModel.superseded_at.is_(None),
        )
    )
    if child is None:
        raise _conflict("staged child no longer matches its accepted source decision")
    child_node = await session.scalar(
        select(FlowNodeModel).where(
            FlowNodeModel.flow_id == authority.flow_id,
            FlowNodeModel.flow_revision_id == authority.flow_revision_id,
            FlowNodeModel.node_key == child.node_key,
            FlowNodeModel.member_id == child.member_id,
            FlowNodeModel.current_assignment_id == child.assignment_id,
        )
    )
    if child_node is None:
        raise _conflict("staged child is missing its current Flow node")
    await _change_node_state(
        session,
        flow_node_id=authority.flow_node.flow_node_id,
        assignment_id=authority.assignment_id,
        from_state="running",
        to_state="waiting",
    )
    await _change_node_state(
        session,
        flow_node_id=child_node.flow_node_id,
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
            AttemptModel.current_dispatch_id.is_(None),
            AttemptModel.current_wait_id.is_(None),
        )
        .values(
            status="completed",
            terminal_outcome=outcome,
            closed_at=transitioned_at,
            current_dispatch_id=None,
            current_wait_id=None,
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
            AssignmentModel.member_id == authority.flow_node.member_id,
            AssignmentModel.node_key == authority.node_key,
            AssignmentModel.current_attempt_id == authority.attempt_id,
            AssignmentModel.closed_at.is_(None),
            AssignmentModel.superseded_at.is_(None),
        )
    )
    if source is None:
        raise _conflict("source assignment is no longer current")
    return source


async def _complete_source_assignment(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    outcome: str,
    transitioned_at: datetime,
) -> None:
    completed = await session.scalar(
        update(AssignmentModel)
        .where(
            AssignmentModel.assignment_id == authority.assignment_id,
            AssignmentModel.task_id == authority.task_id,
            AssignmentModel.flow_id == authority.flow_id,
            AssignmentModel.member_id == authority.flow_node.member_id,
            AssignmentModel.current_attempt_id == authority.attempt_id,
            AssignmentModel.closed_at.is_(None),
            AssignmentModel.superseded_at.is_(None),
        )
        .values(
            terminal_outcome=outcome,
            closed_at=transitioned_at,
        )
        .returning(AssignmentModel.assignment_id)
    )
    if completed is None:
        raise _conflict("source assignment is no longer active")


async def _start_semantic_retry(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    source_assignment: AssignmentModel,
    retry_attempt_id: str,
    transitioned_at: datetime,
) -> None:
    if source_assignment.retries_remaining is not None and source_assignment.retries_remaining <= 0:
        raise budget_exhausted_error("the current assignment has no semantic retries remaining")
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
            AssignmentModel.member_id == authority.flow_node.member_id,
            AssignmentModel.current_attempt_id == authority.attempt_id,
            AssignmentModel.closed_at.is_(None),
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
    source_assignment: AssignmentModel,
) -> None:
    parent_assignment_id = source_assignment.parent_assignment_id
    if parent_assignment_id is None or source_assignment.created_by_dispatch_id is None:
        raise _conflict("child return is missing its sequential parent source")
    parent = await session.scalar(
        select(AssignmentModel).where(
            AssignmentModel.assignment_id == parent_assignment_id,
            AssignmentModel.task_id == authority.task_id,
            AssignmentModel.flow_id == authority.flow_id,
            AssignmentModel.superseded_at.is_(None),
            AssignmentModel.closed_at.is_(None),
        )
    )
    if parent is None or parent.current_attempt_id is None:
        raise _conflict("child return is missing its current parent assignment")
    parent_wait = await session.scalar(
        select(AttemptWaitModel).where(
            AttemptWaitModel.task_id == authority.task_id,
            AttemptWaitModel.flow_id == authority.flow_id,
            AttemptWaitModel.assignment_id == parent.assignment_id,
            AttemptWaitModel.attempt_id == parent.current_attempt_id,
            AttemptWaitModel.source_dispatch_id == source_assignment.created_by_dispatch_id,
            AttemptWaitModel.sequential_child_assignment_id == source_assignment.assignment_id,
            AttemptWaitModel.human_request_id.is_(None),
            AttemptWaitModel.command_run_id.is_(None),
            exists(
                select(AttemptModel.attempt_id).where(
                    AttemptModel.attempt_id == parent.current_attempt_id,
                    AttemptModel.assignment_id == parent.assignment_id,
                    AttemptModel.task_id == authority.task_id,
                    AttemptModel.flow_id == authority.flow_id,
                    AttemptModel.status == "running",
                    AttemptModel.current_dispatch_id.is_(None),
                    AttemptModel.current_wait_id == AttemptWaitModel.wait_id,
                )
            ),
        )
    )
    if parent_wait is None:
        raise _conflict("child return does not match the parent's exact sequential wait")
    wait_identity = AttemptWaitIdentity(
        task_id=parent_wait.task_id,
        flow_id=parent_wait.flow_id,
        assignment_id=parent_wait.assignment_id,
        attempt_id=parent_wait.attempt_id,
        wait_id=parent_wait.wait_id,
    )
    if not await clear_current_attempt_wait(session, identity=wait_identity):
        raise _conflict("another transition already consumed the parent sequential wait")
    deleted_wait_id = await session.scalar(
        delete(AttemptWaitModel)
        .where(
            AttemptWaitModel.wait_id == parent_wait.wait_id,
            AttemptWaitModel.task_id == parent_wait.task_id,
            AttemptWaitModel.flow_id == parent_wait.flow_id,
            AttemptWaitModel.assignment_id == parent_wait.assignment_id,
            AttemptWaitModel.attempt_id == parent_wait.attempt_id,
            AttemptWaitModel.source_dispatch_id == parent_wait.source_dispatch_id,
            AttemptWaitModel.sequential_child_assignment_id == source_assignment.assignment_id,
        )
        .returning(AttemptWaitModel.wait_id)
    )
    if deleted_wait_id is None:
        raise _conflict("another transition removed the parent sequential wait")
    resumed = await session.scalar(
        update(FlowNodeModel)
        .where(
            FlowNodeModel.flow_id == authority.flow_id,
            FlowNodeModel.flow_revision_id == authority.flow_revision_id,
            FlowNodeModel.member_id == parent.member_id,
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
    live_descendant_attempt = exists(
        select(AttemptModel.attempt_id)
        .join(
            AssignmentModel,
            (AssignmentModel.task_id == AttemptModel.task_id)
            & (AssignmentModel.flow_id == AttemptModel.flow_id)
            & (AssignmentModel.assignment_id == AttemptModel.assignment_id),
        )
        .where(
            AttemptModel.task_id == authority.task_id,
            AttemptModel.flow_id == authority.flow_id,
            AttemptModel.status.in_(("pending", "running")),
            AssignmentModel.parent_assignment_id.is_not(None),
        )
    )
    completed = await session.scalar(
        update(FlowModel)
        .where(
            FlowModel.flow_id == authority.flow_id,
            FlowModel.task_id == authority.task_id,
            FlowModel.status == "running",
            FlowModel.active_flow_revision_id == authority.flow_revision_id,
            ~live_descendant_attempt,
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
