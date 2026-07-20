from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.definitions.compiler import NormalizedCompiledNode
from autoclaw.persistence.models import (
    CompiledPlanEdgeModel,
    CompiledPlanModel,
    CompiledPlanNodeModel,
    FlowNodeModel,
    FlowRevisionModel,
    FlowStartSourceModel,
    TaskComposeModel,
    TaskEventStreamHeadModel,
    TaskModel,
    WorkspaceBindingModel,
)
from autoclaw.runtime.contracts import (
    RuntimeBootstrapInput,
    RuntimeBootstrapResult,
)
from autoclaw.runtime.ids import (
    compiled_plan_edge_id,
    compiled_plan_node_id,
    task_compose_id_for_task,
)
from autoclaw.runtime.launch.bootstrap.context import LaunchBootstrapPersistenceContext
from autoclaw.runtime.launch.bootstrap.criteria import build_node_criteria_json
from autoclaw.runtime.launch.bootstrap.revisions import resolve_pinned_role_policy
from autoclaw.runtime.launch.persistence.flows import (
    build_flow_edge_row,
    build_flow_node_row,
    build_flow_revision_row,
    build_flow_row,
    build_node_plan_revision_row,
)

type NodePlanRevisionInput = tuple[
    NormalizedCompiledNode,
    str,
    str | None,
    str,
    str | None,
]


async def stage_launch_bootstrap_rows(
    session: AsyncSession,
    *,
    bootstrap_input: RuntimeBootstrapInput,
    result: RuntimeBootstrapResult,
    context: LaunchBootstrapPersistenceContext,
) -> None:
    await _stage_task_root_rows(
        session,
        bootstrap_input=bootstrap_input,
        result=result,
        context=context,
    )
    await _stage_compiled_plan_graph_rows(
        session,
        bootstrap_input=bootstrap_input,
        context=context,
    )
    await _stage_flow_rows(
        session,
        bootstrap_input=bootstrap_input,
        result=result,
        context=context,
    )


async def _stage_task_root_rows(
    session: AsyncSession,
    *,
    bootstrap_input: RuntimeBootstrapInput,
    result: RuntimeBootstrapResult,
    context: LaunchBootstrapPersistenceContext,
) -> None:
    session.add(
        TaskModel(
            task_id=bootstrap_input.task_id,
            task_key=bootstrap_input.task_compose.task.key,
            title=bootstrap_input.task_compose.task.title,
            summary=bootstrap_input.task_compose.task.summary,
            instruction=bootstrap_input.task_compose.task.instruction,
            workflow_key=bootstrap_input.workflow_definition.id,
            task_root_path=str(result.paths.task_root),
        )
    )
    await session.flush()

    session.add(TaskEventStreamHeadModel(task_id=bootstrap_input.task_id))
    session.add(
        WorkspaceBindingModel(
            workspace_binding_id=f"workspace-binding.{bootstrap_input.task_id}",
            task_id=bootstrap_input.task_id,
            binding_mode=_workspace_binding_mode(context.workspace_binding_mode),
            normalized_root_path=str(result.paths.workspace_path.resolve()),
        )
    )
    session.add(
        TaskComposeModel(
            task_compose_id=task_compose_id_for_task(bootstrap_input.task_id),
            task_id=bootstrap_input.task_id,
            workflow_key=bootstrap_input.task_compose.workflow.key,
            workflow_revision_no=bootstrap_input.compiled_plan.definition_revision_no,
            compiled_plan_id=context.compiled_plan_id,
            compose_payload=bootstrap_input.task_compose.model_dump(mode="json"),
        )
    )
    session.add(
        CompiledPlanModel(
            compiled_plan_id=context.compiled_plan_id,
            task_id=bootstrap_input.task_id,
            workflow_key=bootstrap_input.compiled_plan.workflow_key,
            definition_revision_no=bootstrap_input.compiled_plan.definition_revision_no,
            compiler_version=bootstrap_input.compiled_plan.compiler_version,
            snapshot_json=bootstrap_input.compiled_plan.model_dump(mode="json"),
        )
    )
    await session.flush()


def _workspace_binding_mode(binding_mode: str) -> str:
    if binding_mode == "ensure_task_default":
        return "controller_owned"
    if binding_mode in {"ensure_host_path", "use_existing_host"}:
        return "external"
    raise ValueError(f"unknown workspace binding mode: {binding_mode}")


async def _stage_compiled_plan_graph_rows(
    session: AsyncSession,
    *,
    bootstrap_input: RuntimeBootstrapInput,
    context: LaunchBootstrapPersistenceContext,
) -> None:
    for node in bootstrap_input.compiled_plan.nodes:
        role, policy = resolve_pinned_role_policy(
            bootstrap_input.role_policy_lookup,
            role_key=node.role,
            role_revision_no=node.role_revision_no,
            policy_key=node.policy,
            policy_revision_no=node.policy_revision_no,
        )
        session.add(
            CompiledPlanNodeModel(
                compiled_plan_node_id=compiled_plan_node_id(
                    context.compiled_plan_id,
                    node.node_key,
                ),
                compiled_plan_id=context.compiled_plan_id,
                node_key=node.node_key,
                parent_node_key=node.parent_node_key,
                structural_kind=node.structural_kind.value,
                role_key=node.role,
                role_revision_no=node.role_revision_no,
                role_description=role.definition.description,
                role_instruction=role.definition.instruction,
                policy_key=node.policy,
                policy_revision_no=node.policy_revision_no,
                policy_description=policy.definition.description,
                policy_instruction=policy.definition.instruction,
                provider_kind=node.provider.kind.value if node.provider is not None else None,
                description=node.description,
                node_instruction=node.node_instruction,
                child_node_keys_json=list(node.child_node_keys),
                consumes_json=(node.consumes.model_dump(mode="json") if node.consumes else None),
                produces_json=(node.produces.model_dump(mode="json") if node.produces else None),
                criteria_json=build_node_criteria_json(node=node),
                child_defaults_json=node.child_defaults.model_dump(mode="json")
                if node.child_defaults
                else None,
                order_index=node.order_index,
            )
        )
    for edge in bootstrap_input.compiled_plan.dependency_edges:
        session.add(
            CompiledPlanEdgeModel(
                compiled_plan_edge_id=compiled_plan_edge_id(
                    context.compiled_plan_id,
                    edge.consumer_node_key,
                    edge.kind.value,
                    edge.slot,
                ),
                compiled_plan_id=context.compiled_plan_id,
                provider_node_key=edge.provider_node_key,
                consumer_node_key=edge.consumer_node_key,
                kind=edge.kind.value,
                slot=edge.slot,
                description=edge.description,
                order_index=edge.order_index,
            )
        )
    await session.flush()


async def _stage_flow_rows(
    session: AsyncSession,
    *,
    bootstrap_input: RuntimeBootstrapInput,
    result: RuntimeBootstrapResult,
    context: LaunchBootstrapPersistenceContext,
) -> None:
    session.add(
        build_flow_row(
            bootstrap_input=bootstrap_input,
            context=context,
        )
    )
    await session.flush()

    flow_revision = build_flow_revision_row(
        bootstrap_input=bootstrap_input,
        context=context,
    )
    session.add(flow_revision)
    session.add(
        FlowStartSourceModel(
            flow_id=context.flow_id,
            task_id=bootstrap_input.task_id,
            successor_dispatch_id=None,
        )
    )
    await session.flush()
    flow_node_rows, node_plan_revision_inputs = _stage_flow_node_rows(
        session,
        bootstrap_input=bootstrap_input,
        result=result,
        context=context,
        flow_revision=flow_revision,
    )
    await session.flush()

    _stage_node_plan_revision_rows(
        session,
        bootstrap_input=bootstrap_input,
        flow_revision=flow_revision,
        flow_node_rows=flow_node_rows,
        node_plan_revision_inputs=node_plan_revision_inputs,
    )
    await session.flush()

    for edge in bootstrap_input.compiled_plan.dependency_edges:
        session.add(build_flow_edge_row(bootstrap_input=bootstrap_input, edge=edge))
    await session.flush()


def _stage_flow_node_rows(
    session: AsyncSession,
    *,
    bootstrap_input: RuntimeBootstrapInput,
    result: RuntimeBootstrapResult,
    context: LaunchBootstrapPersistenceContext,
    flow_revision: FlowRevisionModel,
) -> tuple[list[FlowNodeModel], list[NodePlanRevisionInput]]:
    flow_node_rows: list[FlowNodeModel] = []
    node_plan_revision_inputs: list[NodePlanRevisionInput] = []
    for node in bootstrap_input.compiled_plan.nodes:
        role, policy = resolve_pinned_role_policy(
            bootstrap_input.role_policy_lookup,
            role_key=node.role,
            role_revision_no=node.role_revision_no,
            policy_key=node.policy,
            policy_revision_no=node.policy_revision_no,
        )
        flow_node = build_flow_node_row(
            result=result,
            flow_revision=flow_revision,
            context=context,
            bootstrap_input=bootstrap_input,
            node=node,
            role_description=role.definition.description,
            role_instruction=role.definition.instruction,
            policy_description=policy.definition.description,
            policy_instruction=policy.definition.instruction,
        )
        session.add(flow_node)
        flow_node_rows.append(flow_node)
        node_plan_revision_inputs.append(
            (
                node,
                role.definition.description,
                role.definition.instruction,
                policy.definition.description,
                policy.definition.instruction,
            )
        )
    return flow_node_rows, node_plan_revision_inputs


def _stage_node_plan_revision_rows(
    session: AsyncSession,
    *,
    bootstrap_input: RuntimeBootstrapInput,
    flow_revision: FlowRevisionModel,
    flow_node_rows: list[FlowNodeModel],
    node_plan_revision_inputs: list[NodePlanRevisionInput],
) -> None:
    for (
        flow_node,
        (
            node,
            role_description,
            role_instruction,
            policy_description,
            policy_instruction,
        ),
    ) in zip(flow_node_rows, node_plan_revision_inputs, strict=True):
        session.add(
            build_node_plan_revision_row(
                flow_revision=flow_revision,
                flow_node=flow_node,
                bootstrap_input=bootstrap_input,
                node=node,
                role_description=role_description,
                role_instruction=role_instruction,
                policy_description=policy_description,
                policy_instruction=policy_instruction,
            )
        )
