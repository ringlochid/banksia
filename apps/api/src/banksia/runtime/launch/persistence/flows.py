from __future__ import annotations

from banksia.persistence.models import (
    FlowEdgeModel,
    FlowModel,
    FlowNodeModel,
    FlowRevisionModel,
    NodePlanRevisionModel,
)
from banksia.runtime.contracts import (
    RuntimeBootstrapInput,
    RuntimeBootstrapResult,
)
from banksia.runtime.ids import assignment_id, flow_edge_id, flow_node_id, node_plan_revision_id
from banksia.runtime.launch.bootstrap.context import LaunchBootstrapPersistenceContext
from banksia.runtime.launch.bootstrap.criteria import build_node_criteria_json
from banksia.runtime.launch.legacy_team_adapter import LegacyDependencyEdge, LegacyTeamNode


def build_flow_row(
    *,
    bootstrap_input: RuntimeBootstrapInput,
    context: LaunchBootstrapPersistenceContext,
) -> FlowModel:
    return FlowModel(
        flow_id=context.flow_id,
        task_id=bootstrap_input.task_id,
        compiled_plan_id=context.compiled_plan_id,
        status="running",
        active_flow_revision_id=bootstrap_input.active_flow_revision_id,
        current_dispatch_id=None,
    )


def build_flow_revision_row(
    *,
    bootstrap_input: RuntimeBootstrapInput,
    context: LaunchBootstrapPersistenceContext,
) -> FlowRevisionModel:
    return FlowRevisionModel(
        flow_revision_id=bootstrap_input.active_flow_revision_id,
        flow_id=context.flow_id,
        revision_index=1,
        parent_flow_revision_id=None,
        source_compiled_plan_id=context.compiled_plan_id,
        cause="launch",
        snapshot_json=bootstrap_input.compiled_plan.model_dump(mode="json"),
    )


def build_flow_node_row(
    *,
    result: RuntimeBootstrapResult,
    flow_revision: FlowRevisionModel,
    context: LaunchBootstrapPersistenceContext,
    bootstrap_input: RuntimeBootstrapInput,
    node: LegacyTeamNode,
) -> FlowNodeModel:
    return FlowNodeModel(
        flow_node_id=flow_node_id(
            bootstrap_input.active_flow_revision_id,
            node.node_key,
        ),
        task_id=bootstrap_input.task_id,
        flow_id=context.flow_id,
        flow_revision_id=flow_revision.flow_revision_id,
        team_revision_id=bootstrap_input.initial_team.team_revision_id,
        member_id=node.member_id,
        member_configuration_id=node.member_configuration_id,
        member_branch_basis_id=node.member_branch_basis_id,
        member_title=node.title,
        node_key=node.node_key,
        parent_node_key=node.parent_node_key,
        structural_kind=node.structural_kind.value,
        provider_kind=node.provider.kind if node.provider is not None else None,
        description=node.description,
        node_instruction=node.node_instruction,
        child_node_keys_json=list(node.child_node_keys),
        consumes_json=(node.consumes.model_dump(mode="json") if node.consumes else None),
        produces_json=(node.produces.model_dump(mode="json") if node.produces else None),
        criteria_json=build_node_criteria_json(node=node),
        child_defaults_json=node.child_defaults.model_dump(mode="json")
        if node.child_defaults
        else None,
        current_assignment_id=assignment_id(result.assignment.assignment_key)
        if node.node_key == result.assignment.node_key
        else None,
        state="running" if node.node_key == result.assignment.node_key else "ready",
        order_index=node.order_index,
    )


def build_node_plan_revision_row(
    *,
    flow_revision: FlowRevisionModel,
    flow_node: FlowNodeModel,
    bootstrap_input: RuntimeBootstrapInput,
    node: LegacyTeamNode,
) -> NodePlanRevisionModel:
    return NodePlanRevisionModel(
        node_plan_revision_id=node_plan_revision_id(
            bootstrap_input.active_flow_revision_id,
            node.node_key,
        ),
        task_id=bootstrap_input.task_id,
        flow_id=flow_revision.flow_id,
        flow_revision_id=flow_revision.flow_revision_id,
        flow_node_id=flow_node.flow_node_id,
        team_revision_id=bootstrap_input.initial_team.team_revision_id,
        member_id=node.member_id,
        member_configuration_id=node.member_configuration_id,
        member_branch_basis_id=node.member_branch_basis_id,
        member_title=node.title,
        provider_kind=node.provider.kind if node.provider is not None else None,
    )


def build_flow_edge_row(
    *,
    bootstrap_input: RuntimeBootstrapInput,
    edge: LegacyDependencyEdge,
) -> FlowEdgeModel:
    return FlowEdgeModel(
        flow_edge_id=flow_edge_id(
            bootstrap_input.active_flow_revision_id,
            edge.consumer_node_key,
            edge.kind,
            edge.slot,
        ),
        flow_revision_id=bootstrap_input.active_flow_revision_id,
        provider_node_key=edge.provider_node_key,
        consumer_node_key=edge.consumer_node_key,
        kind=edge.kind,
        slot=edge.slot,
        description=edge.description,
        order_index=edge.order_index,
    )
