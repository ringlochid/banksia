from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    FlowEdgeModel,
    FlowNodeModel,
    FlowRevisionModel,
    MemberBranchBasisModel,
    MemberConfigurationModel,
    MemberModel,
    NodePlanRevisionModel,
    TeamRevisionMemberModel,
    TeamRevisionModel,
)
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.ids import flow_edge_id, flow_node_id, node_plan_revision_id
from banksia.runtime.replan.context import ReplanCommitContext
from banksia.runtime.replan.planning import PlannedMember, ReplanMutation, successor_preorder


def stage_replan_successor_rows(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    context: ReplanCommitContext,
    mutation: ReplanMutation,
    *,
    operation: str,
    successor_team_id: str,
    successor_flow_id: str,
) -> None:
    """Stage one complete immutable Team and matching Flow successor."""

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
    _stage_flow_successor(
        session,
        authority,
        context,
        ordered,
        operation=operation,
        successor_team_id=successor_team_id,
        successor_flow_id=successor_flow_id,
    )


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


def _stage_flow_successor(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    context: ReplanCommitContext,
    ordered: tuple[PlannedMember, ...],
    *,
    operation: str,
    successor_team_id: str,
    successor_flow_id: str,
) -> None:
    session.add(
        FlowRevisionModel(
            flow_revision_id=successor_flow_id,
            flow_id=authority.flow_id,
            revision_index=context.flow_revision.revision_index + 1,
            parent_flow_revision_id=context.flow_revision.flow_revision_id,
            source_compiled_plan_id=context.flow_revision.source_compiled_plan_id,
            cause=operation,
            created_by_dispatch_id=authority.dispatch_id,
            snapshot_json={
                "kind": "structural_replan",
                "source_flow_revision_id": context.flow_revision.flow_revision_id,
            },
        )
    )
    surviving_ids = {member.member_id for member in ordered}
    for index, member in enumerate(ordered):
        _stage_flow_member(
            session,
            authority,
            member,
            index=index,
            successor_team_id=successor_team_id,
            successor_flow_id=successor_flow_id,
        )
    for edge in context.edges:
        if edge.provider_node_key in surviving_ids and edge.consumer_node_key in surviving_ids:
            session.add(
                FlowEdgeModel(
                    flow_edge_id=flow_edge_id(
                        successor_flow_id,
                        edge.consumer_node_key,
                        edge.kind,
                        edge.slot,
                    ),
                    flow_revision_id=successor_flow_id,
                    provider_node_key=edge.provider_node_key,
                    consumer_node_key=edge.consumer_node_key,
                    kind=edge.kind,
                    slot=edge.slot,
                    description=edge.description,
                    order_index=edge.order_index,
                )
            )


def _stage_flow_member(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    member: PlannedMember,
    *,
    index: int,
    successor_team_id: str,
    successor_flow_id: str,
) -> None:
    source = member.source_node
    current_assignment_id = source.current_assignment_id if source is not None else None
    state = source.state if source is not None else "ready"
    node_id = flow_node_id(successor_flow_id, member.member_id)
    provider_kind = (
        str(member.provider_json["kind"])
        if member.provider_json is not None and "kind" in member.provider_json
        else None
    )
    session.add(
        FlowNodeModel(
            flow_node_id=node_id,
            task_id=authority.task_id,
            flow_id=authority.flow_id,
            flow_revision_id=successor_flow_id,
            team_revision_id=successor_team_id,
            member_id=member.member_id,
            member_configuration_id=member.configuration_id,
            member_branch_basis_id=member.branch_basis_id,
            member_title=member.title,
            node_key=member.member_id,
            parent_node_key=member.parent_member_id,
            structural_kind=_node_kind(member),
            provider_kind=provider_kind,
            description=member.description or "",
            node_instruction=member.instruction,
            child_node_keys_json=list(member.children),
            consumes_json=source.consumes_json if source is not None else None,
            produces_json=source.produces_json if source is not None else None,
            criteria_json=source.criteria_json if source is not None else [],
            child_defaults_json=source.child_defaults_json if source is not None else None,
            state=state,
            current_assignment_id=current_assignment_id,
            order_index=index,
        )
    )
    session.add(
        NodePlanRevisionModel(
            node_plan_revision_id=node_plan_revision_id(successor_flow_id, member.member_id),
            task_id=authority.task_id,
            flow_id=authority.flow_id,
            flow_revision_id=successor_flow_id,
            flow_node_id=node_id,
            team_revision_id=successor_team_id,
            member_id=member.member_id,
            member_configuration_id=member.configuration_id,
            member_branch_basis_id=member.branch_basis_id,
            member_title=member.title,
            provider_kind=provider_kind,
        )
    )


def _node_kind(member: PlannedMember) -> str:
    if member.parent_member_id is None:
        return "root"
    return "parent" if member.children else "worker"


__all__ = ["stage_replan_successor_rows"]
