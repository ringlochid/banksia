from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AssignmentModel,
    AttemptModel,
    AttemptWaitModel,
    DelegationWaveModel,
    FlowModel,
    FlowNodeModel,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.errors import RuntimeOperationError, budget_exhausted_error


async def advance_terminal_checkpoint_state(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    outcome: str,
    transitioned_at: datetime,
    retry_attempt_id: str | None = None,
) -> None:
    """Apply the semantic transition owned by one accepted boundary transaction."""

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
        # Delegation Wave settlement owns the parent join and continuation.
        return
    if authority.node_kind.value != "root":
        raise _conflict("a non-root terminal boundary is missing parent assignment lineage")
    await _complete_root_flow(
        session,
        authority,
        outcome=outcome,
        transitioned_at=transitioned_at,
    )


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
        task_id=authority.task_id,
        flow_id=authority.flow_id,
        node_key=authority.node_key,
        assignment_id=authority.assignment_id,
        from_state="running",
        to_state="done" if outcome == "green" else "failed",
    )


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
    live_wait = exists(
        select(AttemptWaitModel.wait_id).where(
            AttemptWaitModel.task_id == authority.task_id,
            AttemptWaitModel.flow_id == authority.flow_id,
        )
    )
    live_wave = exists(
        select(DelegationWaveModel.delegation_wave_id).where(
            DelegationWaveModel.task_id == authority.task_id,
            DelegationWaveModel.flow_id == authority.flow_id,
            (DelegationWaveModel.status == "open")
            | (
                (DelegationWaveModel.status == "settled")
                & DelegationWaveModel.successor_dispatch_id.is_(None)
            ),
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
            ~live_wait,
            ~live_wave,
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
    task_id: str,
    flow_id: str,
    node_key: str,
    assignment_id: str,
    from_state: str,
    to_state: str,
) -> None:
    changed_node_ids = tuple(
        await session.scalars(
            update(FlowNodeModel)
            .where(
                FlowNodeModel.task_id == task_id,
                FlowNodeModel.flow_id == flow_id,
                FlowNodeModel.node_key == node_key,
                FlowNodeModel.current_assignment_id == assignment_id,
                FlowNodeModel.state == from_state,
            )
            .values(state=to_state)
            .returning(FlowNodeModel.flow_node_id)
        )
    )
    if not changed_node_ids:
        raise _conflict(f"runtime node is no longer {from_state}")


def _conflict(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary=summary,
        is_retryable=False,
    )


__all__ = ["advance_terminal_checkpoint_state"]
