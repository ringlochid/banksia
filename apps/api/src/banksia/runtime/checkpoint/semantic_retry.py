"""Prepare the first Dispatch of a semantic retry before its atomic commit."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from banksia.persistence.models import (
    CompiledPlanModel,
    FlowModel,
    FlowNodeModel,
    TaskModel,
    WorkflowRevisionModel,
)
from banksia.runtime.assignment import read_assignment_file_references
from banksia.runtime.capabilities import resolve_effective_capabilities_for_node
from banksia.runtime.contracts import CheckpointRequest, FileReference, TaskRootPaths
from banksia.runtime.contracts.capabilities import EffectiveCapabilitySet
from banksia.runtime.contracts.primitives import CheckpointOutcome
from banksia.runtime.contracts.prompt import (
    PromptCheckpointSummary,
    SemanticRetryResult,
    SemanticRetrySource,
    SemanticRetryTrigger,
)
from banksia.runtime.contracts.provider_resolution import ProviderResolution
from banksia.runtime.contracts.team_read import DirectTeamMemberRead
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.dispatch.opening import StartingDispatchBasis
from banksia.runtime.dispatch.preparation import (
    DispatchOpeningDependencies,
    PreparedDispatchRequest,
    prepare_dispatch_request,
)
from banksia.runtime.dispatch.prompt_snapshot import (
    SemanticRetryPromptSnapshot,
    build_semantic_retry_dispatch_request,
)
from banksia.runtime.providers import (
    narrow_provider_capabilities,
    resolve_member_provider_route,
)
from banksia.runtime.task_root import read_task_root_paths
from banksia.runtime.team.reads import read_direct_team_members
from banksia.runtime.work_plan import WorkPlanRead, read_assignment_work_plan


@dataclass(frozen=True, slots=True)
class PreparedSemanticRetry:
    """Prepared provider request and exact first-Dispatch persistence basis."""

    request: PreparedDispatchRequest
    basis: StartingDispatchBasis


@dataclass(frozen=True, slots=True)
class _SemanticRetryContext:
    """Fresh current structural selection for one retained Assignment."""

    flow: FlowModel
    compiled_plan: CompiledPlanModel
    workflow_note: str | None
    node: FlowNodeModel
    children: tuple[FlowNodeModel, ...]


async def prepare_semantic_retry(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    request: CheckpointRequest,
    *,
    files: tuple[FileReference, ...],
    checkpoint_id: str,
    accepted_boundary_id: str,
    retry_attempt_id: str,
    retry_dispatch_id: str,
    dependencies: DispatchOpeningDependencies,
) -> PreparedSemanticRetry:
    """Resolve and render a retry Dispatch while source authority is unchanged."""

    context = await _read_semantic_retry_context(session, authority)
    prepared = await _prepare_semantic_retry_request(
        session,
        authority,
        request,
        context=context,
        files=files,
        checkpoint_id=checkpoint_id,
        accepted_boundary_id=accepted_boundary_id,
        retry_attempt_id=retry_attempt_id,
        retry_dispatch_id=retry_dispatch_id,
        dependencies=dependencies,
    )
    flow_revision_id = context.flow.active_flow_revision_id
    assert flow_revision_id is not None
    return PreparedSemanticRetry(
        request=prepared,
        basis=StartingDispatchBasis(
            task_id=authority.task_id,
            flow_id=authority.flow_id,
            assignment_id=authority.assignment_id,
            flow_revision_id=flow_revision_id,
            flow_node_id=context.node.flow_node_id,
            team_revision_id=context.node.team_revision_id,
            member_id=context.node.member_id,
            member_configuration_id=context.node.member_configuration_id,
            member_branch_basis_id=context.node.member_branch_basis_id,
            attempt_id=retry_attempt_id,
            node_key=context.node.node_key,
            opened_reason="semantic_retry",
            predecessor_dispatch_id=None,
            flow_start_source_flow_id=None,
        ),
    )


async def _prepare_semantic_retry_request(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    request: CheckpointRequest,
    *,
    context: _SemanticRetryContext,
    files: tuple[FileReference, ...],
    checkpoint_id: str,
    accepted_boundary_id: str,
    retry_attempt_id: str,
    retry_dispatch_id: str,
    dependencies: DispatchOpeningDependencies,
) -> PreparedDispatchRequest:
    capabilities = await resolve_effective_capabilities_for_node(
        session,
        node=context.node,
    )
    provider = await resolve_member_provider_route(
        session,
        task_id=authority.task_id,
        member_configuration_id=context.node.member_configuration_id,
        settings=dependencies.settings,
        available_adapter_kinds=dependencies.available_adapter_kinds,
    )
    capabilities = narrow_provider_capabilities(
        route=provider.route,
        sandbox=provider.sandbox,
        capabilities=capabilities,
    )
    paths = await read_task_root_paths(session, authority.task_id)
    assignment_files = await read_assignment_file_references(
        session,
        assignment_id=authority.assignment_id,
    )
    work_plan = await read_assignment_work_plan(
        session,
        assignment_id=authority.assignment_id,
    )
    direct_team = await read_direct_team_members(
        session,
        children=context.children,
        dependencies=dependencies,
    )
    checkpoint = PromptCheckpointSummary(
        id=checkpoint_id,
        summary=request.summary,
        details=request.details,
        files=files,
        outcome=CheckpointOutcome.RETRY,
    )
    prompt = _build_semantic_retry_prompt(
        authority,
        context=context,
        dispatch_id=retry_dispatch_id,
        attempt_id=retry_attempt_id,
        accepted_boundary_id=accepted_boundary_id,
        checkpoint=checkpoint,
        assignment_files=assignment_files,
        work_plan=work_plan,
        capabilities=capabilities,
        provider=provider,
        direct_team=direct_team,
        paths=paths,
    )
    due_at = dependencies.clock()
    return prepare_dispatch_request(
        dependencies=dependencies,
        dispatch_id=retry_dispatch_id,
        due_at=due_at,
        provider=provider,
        capabilities=capabilities,
        request=build_semantic_retry_dispatch_request(prompt),
    )


async def _read_semantic_retry_context(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> _SemanticRetryContext:
    row = (
        await session.execute(
            select(
                FlowModel,
                CompiledPlanModel,
                WorkflowRevisionModel,
                FlowNodeModel,
            )
            .options(raiseload("*"))
            .select_from(FlowModel)
            .join(TaskModel, TaskModel.task_id == FlowModel.task_id)
            .join(
                CompiledPlanModel,
                CompiledPlanModel.compiled_plan_id == FlowModel.compiled_plan_id,
            )
            .join(
                WorkflowRevisionModel,
                (WorkflowRevisionModel.workflow_key == CompiledPlanModel.workflow_key)
                & (WorkflowRevisionModel.revision_no == CompiledPlanModel.workflow_revision_no),
            )
            .join(
                FlowNodeModel,
                (FlowNodeModel.task_id == TaskModel.task_id)
                & (FlowNodeModel.flow_id == FlowModel.flow_id)
                & (FlowNodeModel.flow_revision_id == FlowModel.active_flow_revision_id)
                & (FlowNodeModel.team_revision_id == TaskModel.current_team_revision_id)
                & (FlowNodeModel.node_key == authority.node_key)
                & (FlowNodeModel.member_id == authority.dispatch.member_id)
                & (
                    FlowNodeModel.member_configuration_id
                    == authority.dispatch.member_configuration_id
                )
                & (
                    FlowNodeModel.member_branch_basis_id
                    == authority.dispatch.member_branch_basis_id
                )
                & (FlowNodeModel.current_assignment_id == authority.assignment_id),
            )
            .where(
                FlowModel.flow_id == authority.flow_id,
                FlowModel.task_id == authority.task_id,
                FlowModel.status == "running",
                FlowModel.active_flow_revision_id.is_not(None),
                TaskModel.current_team_revision_id.is_not(None),
                FlowNodeModel.state == "running",
            )
        )
    ).one_or_none()
    if row is None:
        raise ValueError("semantic retry lost its current retained member selection")
    flow, compiled_plan, workflow, node = row
    assert flow.active_flow_revision_id is not None
    workflow_note = workflow.content_json.get("note")
    if workflow_note is not None and not isinstance(workflow_note, str):
        raise ValueError("pinned workflow note must be text")
    children = tuple(
        await session.scalars(
            select(FlowNodeModel)
            .options(raiseload("*"))
            .where(
                FlowNodeModel.flow_id == flow.flow_id,
                FlowNodeModel.flow_revision_id == flow.active_flow_revision_id,
                FlowNodeModel.parent_node_key == node.node_key,
            )
            .order_by(FlowNodeModel.order_index)
        )
    )
    return _SemanticRetryContext(
        flow=flow,
        compiled_plan=compiled_plan,
        workflow_note=workflow_note,
        node=node,
        children=children,
    )


def _build_semantic_retry_prompt(
    authority: NodeOperationAuthority,
    *,
    context: _SemanticRetryContext,
    dispatch_id: str,
    attempt_id: str,
    accepted_boundary_id: str,
    checkpoint: PromptCheckpointSummary,
    assignment_files: tuple[FileReference, ...],
    work_plan: WorkPlanRead | None,
    capabilities: EffectiveCapabilitySet,
    provider: ProviderResolution,
    direct_team: tuple[DirectTeamMemberRead, ...],
    paths: TaskRootPaths,
) -> SemanticRetryPromptSnapshot:
    node = context.node
    assert context.flow.active_flow_revision_id is not None
    return SemanticRetryPromptSnapshot(
        task_id=authority.task_id,
        workflow_key=context.compiled_plan.workflow_key,
        flow_id=authority.flow_id,
        flow_revision_id=context.flow.active_flow_revision_id,
        dispatch_id=dispatch_id,
        assignment_id=authority.assignment_id,
        attempt_id=attempt_id,
        retry_of_attempt_id=authority.attempt_id,
        node_key=node.node_key,
        flow_node_id=node.flow_node_id,
        team_revision_id=node.team_revision_id,
        member_id=node.member_id,
        member_configuration_id=node.member_configuration_id,
        member_branch_basis_id=node.member_branch_basis_id,
        member_title=node.member_title,
        member_description=node.description,
        member_instruction=node.node_instruction,
        workflow_note=context.workflow_note,
        assignment_prompt=authority.assignment.prompt,
        assignment_files=assignment_files,
        work_plan=work_plan,
        capabilities=capabilities,
        provider=provider,
        direct_team=direct_team,
        paths=paths,
        node_kind=node.structural_kind,
        parent_assignment_id=authority.assignment.parent_assignment_id,
        trigger=SemanticRetryTrigger(
            source=SemanticRetrySource(
                accepted_boundary_id=accepted_boundary_id,
                source_dispatch_id=authority.dispatch_id,
                previous_attempt_id=authority.attempt_id,
            ),
            result=SemanticRetryResult(checkpoint=checkpoint),
        ),
    )


__all__ = ["PreparedSemanticRetry", "prepare_semantic_retry"]
