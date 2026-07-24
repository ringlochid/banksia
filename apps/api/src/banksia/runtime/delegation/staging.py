from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, update
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AssignmentModel,
    AttemptWaitModel,
    DelegationWaveMemberModel,
    DelegationWaveModel,
    FlowNodeModel,
)
from banksia.runtime.assignment import stage_assignment_file_references
from banksia.runtime.dispatch.authority import (
    NodeOperationAuthority,
    exact_node_operation_authority_exists,
)
from banksia.runtime.dispatch.currentness import (
    AttemptDispatchConflictError,
    AttemptDispatchIdentity,
    suspend_current_attempt_on_wait,
)
from banksia.runtime.dispatch.opening import StartingDispatchBasis, stage_starting_dispatch
from banksia.runtime.errors import budget_exhausted_error

from .preparation import PreparedWaveMember, delegation_conflict


async def stage_delegation_wave(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    wave_id: str,
    wait_id: str,
    members: tuple[PreparedWaveMember, ...],
    committed_at: datetime,
) -> None:
    """Stage one all-or-none Wave, its child work, and the exact parent wait."""

    session.add(
        DelegationWaveModel(
            delegation_wave_id=wave_id,
            task_id=authority.task_id,
            flow_id=authority.flow_id,
            parent_assignment_id=authority.assignment_id,
            parent_attempt_id=authority.attempt_id,
            source_dispatch_id=authority.dispatch_id,
            flow_revision_id=authority.flow_revision_id,
            parent_node_key=authority.node_key,
            status="open",
            successor_dispatch_id=None,
            created_at=committed_at,
        )
    )
    for order_index, member in enumerate(members):
        _stage_wave_member(
            session,
            authority,
            wave_id=wave_id,
            order_index=order_index,
            member=member,
        )
    await session.flush()

    await _consume_assignment_budget(session, authority, count=len(members))
    for member in members:
        await _claim_child_node(session, authority, member)
        if member.previous_assignment is not None:
            await _supersede_previous_assignment(
                session,
                authority,
                member.previous_assignment,
                superseded_at=committed_at,
            )
        try:
            await stage_starting_dispatch(
                session,
                basis=_starting_dispatch_basis(authority, member),
                prepared=member.dispatch,
            )
        except AttemptDispatchConflictError as exc:
            raise delegation_conflict(
                "another transition changed a delegated child Attempt"
            ) from exc

    await _select_parent_wait(
        session,
        authority,
        wave_id=wave_id,
        wait_id=wait_id,
        committed_at=committed_at,
    )


def _stage_wave_member(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    wave_id: str,
    order_index: int,
    member: PreparedWaveMember,
) -> None:
    session.add_all(
        (
            member.assignment,
            member.attempt,
            DelegationWaveMemberModel(
                delegation_wave_id=wave_id,
                order_index=order_index,
                task_id=authority.task_id,
                flow_id=authority.flow_id,
                parent_assignment_id=authority.assignment_id,
                parent_attempt_id=authority.attempt_id,
                source_dispatch_id=authority.dispatch_id,
                flow_revision_id=authority.flow_revision_id,
                parent_node_key=authority.node_key,
                child_assignment_id=member.assignment.assignment_id,
                child_member_id=member.node.member_id,
                child_node_key=member.node.node_key,
                status="pending",
            ),
        )
    )
    stage_assignment_file_references(
        session,
        assignment_id=member.assignment.assignment_id,
        files=member.files,
    )


async def _consume_assignment_budget(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    count: int,
) -> None:
    consumed = await session.scalar(
        update(AssignmentModel)
        .where(
            AssignmentModel.assignment_id == authority.assignment_id,
            AssignmentModel.task_id == authority.task_id,
            AssignmentModel.flow_id == authority.flow_id,
            AssignmentModel.member_id == authority.flow_node.member_id,
            AssignmentModel.current_attempt_id == authority.attempt_id,
            AssignmentModel.closed_at.is_(None),
            AssignmentModel.superseded_at.is_(None),
            (AssignmentModel.child_assignments_remaining.is_(None))
            | (AssignmentModel.child_assignments_remaining >= count),
            exact_node_operation_authority_exists(authority),
        )
        .values(
            child_assignments_remaining=case(
                (
                    AssignmentModel.child_assignments_remaining.is_not(None),
                    AssignmentModel.child_assignments_remaining - count,
                ),
                else_=None,
            )
        )
        .returning(AssignmentModel.assignment_id)
    )
    if consumed is None:
        raise budget_exhausted_error(
            f"the current Assignment has fewer than {count} child-Assignment units remaining"
        )


async def _claim_child_node(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    member: PreparedWaveMember,
) -> None:
    previous_assignment_id = (
        member.previous_assignment.assignment_id if member.previous_assignment is not None else None
    )
    current_assignment_matches = (
        FlowNodeModel.current_assignment_id.is_(None)
        if previous_assignment_id is None
        else FlowNodeModel.current_assignment_id == previous_assignment_id
    )
    claimed = await session.scalar(
        update(FlowNodeModel)
        .where(
            FlowNodeModel.flow_node_id == member.node.flow_node_id,
            FlowNodeModel.task_id == authority.task_id,
            FlowNodeModel.flow_id == authority.flow_id,
            FlowNodeModel.flow_revision_id == member.node.flow_revision_id,
            FlowNodeModel.parent_node_key == authority.node_key,
            FlowNodeModel.member_id == member.authored.child_id,
            FlowNodeModel.state == member.node.state,
            current_assignment_matches,
            exact_node_operation_authority_exists(authority),
        )
        .values(
            current_assignment_id=member.assignment.assignment_id,
            state="running",
        )
        .returning(FlowNodeModel.flow_node_id)
    )
    if claimed is None:
        raise delegation_conflict(f"another transition changed child '{member.authored.child_id}'")


async def _supersede_previous_assignment(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    previous: AssignmentModel,
    *,
    superseded_at: datetime,
) -> None:
    superseded = await session.scalar(
        update(AssignmentModel)
        .where(
            AssignmentModel.assignment_id == previous.assignment_id,
            AssignmentModel.task_id == authority.task_id,
            AssignmentModel.flow_id == authority.flow_id,
            AssignmentModel.member_id == previous.member_id,
            AssignmentModel.current_attempt_id == previous.current_attempt_id,
            AssignmentModel.superseded_at.is_(None),
            exact_node_operation_authority_exists(authority),
        )
        .values(superseded_at=superseded_at)
        .returning(AssignmentModel.assignment_id)
    )
    if superseded is None:
        raise delegation_conflict("another transition changed a delegated child's prior Assignment")


def _starting_dispatch_basis(
    authority: NodeOperationAuthority,
    member: PreparedWaveMember,
) -> StartingDispatchBasis:
    node = member.node
    return StartingDispatchBasis(
        task_id=authority.task_id,
        flow_id=authority.flow_id,
        assignment_id=member.assignment.assignment_id,
        flow_revision_id=node.flow_revision_id,
        flow_node_id=node.flow_node_id,
        team_revision_id=node.team_revision_id,
        member_id=node.member_id,
        member_configuration_id=node.member_configuration_id,
        member_branch_basis_id=node.member_branch_basis_id,
        attempt_id=member.attempt.attempt_id,
        node_key=node.node_key,
        opened_reason="delegation",
        predecessor_dispatch_id=None,
        flow_start_source_flow_id=None,
    )


async def _select_parent_wait(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    wave_id: str,
    wait_id: str,
    committed_at: datetime,
) -> None:
    parent_waiting_node_ids = tuple(
        await session.scalars(
            update(FlowNodeModel)
            .where(
                FlowNodeModel.task_id == authority.task_id,
                FlowNodeModel.flow_id == authority.flow_id,
                FlowNodeModel.node_key == authority.node_key,
                FlowNodeModel.current_assignment_id == authority.assignment_id,
                FlowNodeModel.state == "running",
                exact_node_operation_authority_exists(authority),
            )
            .values(state="waiting")
            .returning(FlowNodeModel.flow_node_id)
        )
    )
    if not parent_waiting_node_ids:
        raise delegation_conflict("another transition changed the delegating parent")
    session.add(
        AttemptWaitModel(
            wait_id=wait_id,
            task_id=authority.task_id,
            flow_id=authority.flow_id,
            assignment_id=authority.assignment_id,
            attempt_id=authority.attempt_id,
            source_dispatch_id=authority.dispatch_id,
            delegation_wave_id=wave_id,
            human_request_id=None,
            command_run_id=None,
            created_at=committed_at,
        )
    )
    await session.flush()
    suspended = await suspend_current_attempt_on_wait(
        session,
        identity=AttemptDispatchIdentity(
            task_id=authority.task_id,
            flow_id=authority.flow_id,
            assignment_id=authority.assignment_id,
            attempt_id=authority.attempt_id,
            dispatch_id=authority.dispatch_id,
        ),
        wait_id=wait_id,
        expected_flow_revision_id=authority.flow_revision_id,
        closed_at=committed_at,
        closed_reason="delegation",
    )
    if not suspended:
        raise delegation_conflict("another transition changed parent delegation authority")


__all__ = ["stage_delegation_wave"]
