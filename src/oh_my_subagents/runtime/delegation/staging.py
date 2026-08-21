from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, update
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.persistence.models import (
    AssignmentModel,
    AttemptWaitModel,
    DelegationWaveMemberModel,
    DelegationWaveModel,
)
from oh_my_subagents.runtime.assignment import stage_assignment_file_references
from oh_my_subagents.runtime.dispatch.authority import (
    NodeOperationAuthority,
    exact_node_operation_authority_exists,
)
from oh_my_subagents.runtime.dispatch.currentness import (
    AttemptDispatchConflictError,
    AttemptDispatchIdentity,
    suspend_current_attempt_on_wait,
)
from oh_my_subagents.runtime.dispatch.opening import StartingDispatchBasis, stage_starting_dispatch
from oh_my_subagents.runtime.errors import budget_exhausted_error

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
            parent_assignment_id=authority.assignment_id,
            parent_attempt_id=authority.attempt_id,
            source_dispatch_id=authority.dispatch_id,
            team_revision_id=authority.team_revision_id,
            parent_member_id=authority.member_id,
            parent_member_configuration_id=authority.dispatch.member_configuration_id,
            parent_member_branch_basis_id=authority.dispatch.member_branch_basis_id,
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
    selection = member.target.selection
    session.add_all(
        (
            member.assignment,
            member.attempt,
            DelegationWaveMemberModel(
                delegation_wave_id=wave_id,
                order_index=order_index,
                task_id=authority.task_id,
                parent_assignment_id=authority.assignment_id,
                parent_attempt_id=authority.attempt_id,
                source_dispatch_id=authority.dispatch_id,
                team_revision_id=authority.team_revision_id,
                parent_member_id=authority.member_id,
                parent_member_configuration_id=authority.dispatch.member_configuration_id,
                parent_member_branch_basis_id=authority.dispatch.member_branch_basis_id,
                child_assignment_id=member.assignment.assignment_id,
                child_member_id=selection.member_id,
                child_member_configuration_id=selection.member_configuration_id,
                child_member_branch_basis_id=selection.member_branch_basis_id,
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
            AssignmentModel.member_id == authority.member_id,
            AssignmentModel.current_attempt_id == authority.attempt_id,
            AssignmentModel.closed_at.is_(None),
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


def _starting_dispatch_basis(
    authority: NodeOperationAuthority,
    member: PreparedWaveMember,
) -> StartingDispatchBasis:
    selection = member.target.selection
    return StartingDispatchBasis(
        task_id=authority.task_id,
        assignment_id=member.assignment.assignment_id,
        team_revision_id=selection.team_revision_id,
        member_id=selection.member_id,
        member_configuration_id=selection.member_configuration_id,
        member_branch_basis_id=selection.member_branch_basis_id,
        attempt_id=member.attempt.attempt_id,
        opened_reason="delegation",
        predecessor_dispatch_id=None,
        task_start_source_task_id=None,
    )


async def _select_parent_wait(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    wave_id: str,
    wait_id: str,
    committed_at: datetime,
) -> None:
    session.add(
        AttemptWaitModel(
            wait_id=wait_id,
            task_id=authority.task_id,
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
            assignment_id=authority.assignment_id,
            attempt_id=authority.attempt_id,
            dispatch_id=authority.dispatch_id,
        ),
        wait_id=wait_id,
        expected_team_revision_id=authority.team_revision_id,
        closed_at=committed_at,
        closed_reason="delegation",
    )
    if not suspended:
        raise delegation_conflict("another transition changed parent delegation authority")


__all__ = ["stage_delegation_wave"]
