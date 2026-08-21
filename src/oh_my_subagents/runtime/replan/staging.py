from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.persistence.models import (
    MemberBranchBasisModel,
    MemberConfigurationModel,
    MemberModel,
    TeamRevisionMemberModel,
    TeamRevisionModel,
)
from oh_my_subagents.runtime.dispatch.authority import NodeOperationAuthority
from oh_my_subagents.runtime.replan.context import ReplanCommitContext
from oh_my_subagents.runtime.replan.planning import (
    PlannedMember,
    ReplanMutation,
    successor_preorder,
)


def stage_replan_successor_rows(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    context: ReplanCommitContext,
    mutation: ReplanMutation,
    *,
    successor_team_id: str,
) -> None:
    """Stage one complete immutable successor Team."""

    ordered = successor_preorder(mutation)
    _stage_member_history(session, authority, ordered)
    session.add(
        TeamRevisionModel(
            team_revision_id=successor_team_id,
            task_id=authority.task_id,
            revision_no=context.team_revision.revision_no + 1,
            predecessor_team_revision_id=context.team_revision.team_revision_id,
            root_member_id=mutation.root_member_id,
            workflow_key=context.team_revision.workflow_key,
            workflow_revision_no=context.team_revision.workflow_revision_no,
            workflow_content_hash=context.team_revision.workflow_content_hash,
            provenance_json={
                "kind": "structural_replan",
                "source_dispatch_id": authority.dispatch_id,
            },
        )
    )
    _stage_team_selection(session, authority, ordered, successor_team_id)


def _stage_member_history(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    ordered: tuple[PlannedMember, ...],
) -> None:
    branch_basis_by_member_id = {member.member_id: member.branch_basis_id for member in ordered}
    for member in ordered:
        if member.is_new:
            session.add(MemberModel(task_id=authority.task_id, member_id=member.member_id))
        if member.has_configuration_change:
            session.add(
                MemberConfigurationModel(
                    member_configuration_id=member.configuration_id,
                    task_id=authority.task_id,
                    member_id=member.member_id,
                    predecessor_member_configuration_id=(
                        member.source_configuration.member_configuration_id
                        if member.source_configuration is not None
                        else None
                    ),
                    title=member.title,
                    description=member.description,
                    instruction=member.instruction,
                    requested_provider_json=member.provider_json,
                    requested_capabilities_json=member.capabilities_json,
                    basis_kind="structural_replan",
                    basis_id=authority.dispatch_id,
                )
            )
        if member.has_branch_change:
            parent_basis = (
                branch_basis_by_member_id[member.parent_member_id]
                if member.parent_member_id is not None
                else None
            )
            session.add(
                MemberBranchBasisModel(
                    member_branch_basis_id=member.branch_basis_id,
                    task_id=authority.task_id,
                    member_id=member.member_id,
                    member_configuration_id=member.configuration_id,
                    parent_member_id=member.parent_member_id,
                    parent_member_branch_basis_id=parent_basis,
                )
            )


def _stage_team_selection(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    ordered: tuple[PlannedMember, ...],
    successor_team_id: str,
) -> None:
    sibling_orders: dict[str, int] = {}
    for preorder_index, member in enumerate(ordered):
        sibling_order = sibling_orders.get(member.parent_member_id or "", 0)
        sibling_orders[member.parent_member_id or ""] = sibling_order + 1
        session.add(
            TeamRevisionMemberModel(
                task_id=authority.task_id,
                team_revision_id=successor_team_id,
                member_id=member.member_id,
                parent_member_id=member.parent_member_id,
                member_configuration_id=member.configuration_id,
                member_branch_basis_id=member.branch_basis_id,
                preorder_index=preorder_index,
                sibling_order=0 if member.parent_member_id is None else sibling_order,
            )
        )


__all__ = ["stage_replan_successor_rows"]
