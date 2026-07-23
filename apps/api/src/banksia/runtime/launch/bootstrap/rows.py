from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    CompiledPlanModel,
    CompiledPlanNodeModel,
    FlowNodeModel,
    FlowRevisionModel,
    FlowStartSourceModel,
    TaskEventStreamHeadModel,
    TaskModel,
    WorkspaceBindingModel,
)
from banksia.runtime.contracts import (
    RuntimeBootstrapInput,
    RuntimeBootstrapResult,
)
from banksia.runtime.ids import compiled_plan_node_id
from banksia.runtime.launch.bootstrap.context import LaunchBootstrapPersistenceContext
from banksia.runtime.launch.legacy_team_adapter import LegacyTeamNode
from banksia.runtime.launch.persistence.flows import (
    build_flow_node_row,
    build_flow_revision_row,
    build_flow_row,
    build_node_plan_revision_row,
)
from banksia.runtime.team import materialize_initial_task_team

type NodePlanRevisionInput = tuple[LegacyTeamNode,]


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
            workflow_key=bootstrap_input.workflow_revision.workflow_id,
            workflow_revision_no=bootstrap_input.workflow_revision.revision_no,
            workflow_content_hash=bootstrap_input.workflow_revision.content_hash,
            current_team_revision_id=None,
            max_child_assignments_per_assignment=(
                bootstrap_input.max_child_assignments_per_assignment
            ),
            max_retries_per_assignment=bootstrap_input.max_retries_per_assignment,
            max_wave_members=bootstrap_input.max_wave_members,
            task_root_path=str(result.paths.task_root),
        )
    )
    await session.flush()
    materialized = await materialize_initial_task_team(
        session,
        bootstrap_input.workflow_revision,
        task_id=bootstrap_input.task_id,
    )
    if materialized != bootstrap_input.initial_team:
        raise ValueError("initial Team materialization changed its admitted plan")

    session.add(TaskEventStreamHeadModel(task_id=bootstrap_input.task_id))
    session.add(
        WorkspaceBindingModel(
            workspace_binding_id=f"workspace-binding.{bootstrap_input.task_id}",
            task_id=bootstrap_input.task_id,
            binding_mode="external",
            normalized_root_path=str(bootstrap_input.workspace),
        )
    )
    session.add(
        CompiledPlanModel(
            compiled_plan_id=context.compiled_plan_id,
            task_id=bootstrap_input.task_id,
            workflow_key=bootstrap_input.compiled_plan.workflow_key,
            workflow_revision_no=bootstrap_input.compiled_plan.definition_revision_no,
            compiler_version=bootstrap_input.compiled_plan.compiler_version,
            snapshot_json=bootstrap_input.compiled_plan.model_dump(mode="json"),
        )
    )
    await session.flush()


async def _stage_compiled_plan_graph_rows(
    session: AsyncSession,
    *,
    bootstrap_input: RuntimeBootstrapInput,
    context: LaunchBootstrapPersistenceContext,
) -> None:
    for node in bootstrap_input.compiled_plan.nodes:
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
                task_id=bootstrap_input.task_id,
                team_revision_id=bootstrap_input.initial_team.team_revision_id,
                member_id=node.member_id,
                member_configuration_id=node.member_configuration_id,
                member_branch_basis_id=node.member_branch_basis_id,
                member_title=node.title,
                provider_kind=node.provider.kind if node.provider is not None else None,
                description=node.description,
                node_instruction=node.node_instruction,
                child_node_keys_json=list(node.child_node_keys),
                order_index=node.order_index,
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


def _stage_flow_node_rows(
    session: AsyncSession,
    *,
    bootstrap_input: RuntimeBootstrapInput,
    context: LaunchBootstrapPersistenceContext,
    flow_revision: FlowRevisionModel,
) -> tuple[list[FlowNodeModel], list[NodePlanRevisionInput]]:
    flow_node_rows: list[FlowNodeModel] = []
    node_plan_revision_inputs: list[NodePlanRevisionInput] = []
    for node in bootstrap_input.compiled_plan.nodes:
        flow_node = build_flow_node_row(
            flow_revision=flow_revision,
            context=context,
            bootstrap_input=bootstrap_input,
            node=node,
        )
        session.add(flow_node)
        flow_node_rows.append(flow_node)
        node_plan_revision_inputs.append((node,))
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
        (node,),
    ) in zip(flow_node_rows, node_plan_revision_inputs, strict=True):
        session.add(
            build_node_plan_revision_row(
                flow_revision=flow_revision,
                flow_node=flow_node,
                bootstrap_input=bootstrap_input,
                node=node,
            )
        )
