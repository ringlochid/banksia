from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AssignmentModel,
    AttemptModel,
    AttemptWaitModel,
    DelegationWaveModel,
    TaskModel,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.errors import RuntimeOperationError, budget_exhausted_error


async def advance_terminal_checkpoint_state(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    outcome: str,
    boundary_id: str,
    transitioned_at: datetime,
    retry_attempt_id: str | None = None,
) -> None:
    """Apply the semantic transition owned by one accepted Boundary transaction."""

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
        raise _conflict("a non-retry Boundary cannot select a replacement Attempt")
    await _complete_source_assignment(
        session,
        authority,
        outcome=outcome,
        transitioned_at=transitioned_at,
    )
    if source_assignment.parent_assignment_id is not None:
        return
    if authority.node_kind.value != "root":
        raise _conflict("a non-root terminal Boundary is missing parent Assignment lineage")
    await _complete_root_task(
        session,
        authority,
        outcome=outcome,
        boundary_id=boundary_id,
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
        raise _conflict("source Attempt is no longer active")


async def _read_source_assignment(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> AssignmentModel:
    source = await session.scalar(
        select(AssignmentModel).where(
            AssignmentModel.assignment_id == authority.assignment_id,
            AssignmentModel.task_id == authority.task_id,
            AssignmentModel.member_id == authority.member_id,
            AssignmentModel.current_attempt_id == authority.attempt_id,
            AssignmentModel.closed_at.is_(None),
            AssignmentModel.superseded_at.is_(None),
        )
    )
    if source is None:
        raise _conflict("source Assignment is no longer current")
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
            AssignmentModel.member_id == authority.member_id,
            AssignmentModel.current_attempt_id == authority.attempt_id,
            AssignmentModel.closed_at.is_(None),
            AssignmentModel.superseded_at.is_(None),
        )
        .values(terminal_outcome=outcome, closed_at=transitioned_at)
        .returning(AssignmentModel.assignment_id)
    )
    if completed is None:
        raise _conflict("source Assignment is no longer active")


async def _start_semantic_retry(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    source_assignment: AssignmentModel,
    retry_attempt_id: str,
    transitioned_at: datetime,
) -> None:
    if source_assignment.retries_remaining is not None and source_assignment.retries_remaining <= 0:
        raise budget_exhausted_error("the current Assignment has no semantic retries remaining")
    session.add(
        AttemptModel(
            attempt_id=retry_attempt_id,
            assignment_id=authority.assignment_id,
            task_id=authority.task_id,
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
            AssignmentModel.member_id == authority.member_id,
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


async def _complete_root_task(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    outcome: str,
    boundary_id: str,
    transitioned_at: datetime,
) -> None:
    live_descendant_attempt = exists(
        select(AttemptModel.attempt_id)
        .join(
            AssignmentModel,
            (AssignmentModel.task_id == AttemptModel.task_id)
            & (AssignmentModel.assignment_id == AttemptModel.assignment_id),
        )
        .where(
            AttemptModel.task_id == authority.task_id,
            AttemptModel.status.in_(("pending", "running")),
            AssignmentModel.parent_assignment_id.is_not(None),
        )
    )
    live_wait = exists(
        select(AttemptWaitModel.wait_id).where(AttemptWaitModel.task_id == authority.task_id)
    )
    live_wave = exists(
        select(DelegationWaveModel.delegation_wave_id).where(
            DelegationWaveModel.task_id == authority.task_id,
            (DelegationWaveModel.status == "open")
            | (
                (DelegationWaveModel.status == "settled")
                & DelegationWaveModel.successor_dispatch_id.is_(None)
            ),
        )
    )
    completed = await session.scalar(
        update(TaskModel)
        .where(
            TaskModel.task_id == authority.task_id,
            TaskModel.status == "running",
            TaskModel.root_assignment_id == authority.assignment_id,
            TaskModel.current_team_revision_id == authority.team_revision_id,
            TaskModel.control_revision == authority.task_control_revision,
            TaskModel.result_boundary_id.is_(None),
            ~live_descendant_attempt,
            ~live_wait,
            ~live_wave,
        )
        .values(
            status="completed",
            terminal_outcome=outcome,
            result_boundary_id=boundary_id,
            updated_at=transitioned_at,
        )
        .returning(TaskModel.task_id)
    )
    if completed is None:
        raise _conflict("root Task is no longer eligible for terminal completion")


def _conflict(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary=summary,
        is_retryable=False,
    )


__all__ = ["advance_terminal_checkpoint_state"]
