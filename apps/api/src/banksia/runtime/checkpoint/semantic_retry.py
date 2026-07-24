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
    WorkflowRevisionModel,
)
from banksia.runtime.assignment import read_assignment_file_references
from banksia.runtime.capabilities import resolve_effective_capabilities_for_node
from banksia.runtime.contracts import CheckpointRequest, FileReference
from banksia.runtime.contracts.primitives import CheckpointOutcome
from banksia.runtime.contracts.prompt import (
    PromptCheckpointSummary,
    SemanticRetryResult,
    SemanticRetrySource,
    SemanticRetryTrigger,
)
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.dispatch.opening import StartingDispatchBasis
from banksia.runtime.dispatch.preparation import (
    DispatchOpeningDependencies,
    PreparedDispatchRequest,
    prepare_dispatch_request,
)
from banksia.runtime.dispatch.prompt_snapshot import (
    BoundaryPromptSnapshot,
    build_boundary_dispatch_request,
)
from banksia.runtime.providers import (
    narrow_provider_capabilities,
    resolve_member_provider_route,
)
from banksia.runtime.task_root import read_task_root_paths
from banksia.runtime.team.reads import read_direct_team_members
from banksia.runtime.work_plan import read_assignment_work_plan


@dataclass(frozen=True, slots=True)
class PreparedSemanticRetry:
    """Prepared provider request and exact first-Dispatch persistence basis."""

    request: PreparedDispatchRequest
    basis: StartingDispatchBasis


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

    flow = await session.scalar(
        select(FlowModel)
        .options(raiseload("*"))
        .where(
            FlowModel.flow_id == authority.flow_id,
            FlowModel.task_id == authority.task_id,
            FlowModel.status == "running",
            FlowModel.active_flow_revision_id == authority.flow_revision_id,
        )
    )
    if flow is None:
        raise ValueError("semantic retry lost its exact running Flow")
    compiled_plan = await session.get(CompiledPlanModel, flow.compiled_plan_id)
    if compiled_plan is None:
        raise ValueError("semantic retry is missing its compiled plan")
    workflow = await session.scalar(
        select(WorkflowRevisionModel)
        .options(raiseload("*"))
        .where(
            WorkflowRevisionModel.workflow_key == compiled_plan.workflow_key,
            WorkflowRevisionModel.revision_no == compiled_plan.workflow_revision_no,
        )
    )
    if workflow is None:
        raise ValueError("semantic retry is missing its pinned workflow revision")
    workflow_note = workflow.content_json.get("note")
    if workflow_note is not None and not isinstance(workflow_note, str):
        raise ValueError("pinned workflow note must be text")

    node = authority.flow_node
    children = tuple(
        await session.scalars(
            select(FlowNodeModel)
            .options(raiseload("*"))
            .where(
                FlowNodeModel.flow_id == authority.flow_id,
                FlowNodeModel.flow_revision_id == authority.flow_revision_id,
                FlowNodeModel.parent_node_key == node.node_key,
            )
            .order_by(FlowNodeModel.order_index)
        )
    )
    capabilities = await resolve_effective_capabilities_for_node(session, node=node)
    provider = await resolve_member_provider_route(
        session,
        task_id=authority.task_id,
        member_configuration_id=node.member_configuration_id,
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
        children=children,
        dependencies=dependencies,
    )
    checkpoint = PromptCheckpointSummary(
        id=checkpoint_id,
        summary=request.summary,
        details=request.details,
        files=files,
        outcome=CheckpointOutcome.RETRY,
    )
    prompt = BoundaryPromptSnapshot(
        task_id=authority.task_id,
        workflow_key=compiled_plan.workflow_key,
        flow_id=authority.flow_id,
        flow_revision_id=authority.flow_revision_id,
        dispatch_id=retry_dispatch_id,
        assignment_id=authority.assignment_id,
        attempt_id=retry_attempt_id,
        retry_of_attempt_id=authority.attempt_id,
        node_key=authority.node_key,
        flow_node_id=node.flow_node_id,
        team_revision_id=node.team_revision_id,
        member_id=node.member_id,
        member_configuration_id=node.member_configuration_id,
        member_branch_basis_id=node.member_branch_basis_id,
        member_title=node.member_title,
        member_description=node.description,
        member_instruction=node.node_instruction,
        workflow_note=workflow_note,
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
    due_at = dependencies.clock()
    prepared = prepare_dispatch_request(
        dependencies=dependencies,
        dispatch_id=retry_dispatch_id,
        due_at=due_at,
        provider=provider,
        capabilities=capabilities,
        request=build_boundary_dispatch_request(prompt),
    )
    return PreparedSemanticRetry(
        request=prepared,
        basis=StartingDispatchBasis(
            task_id=authority.task_id,
            flow_id=authority.flow_id,
            assignment_id=authority.assignment_id,
            flow_revision_id=authority.flow_revision_id,
            flow_node_id=node.flow_node_id,
            team_revision_id=node.team_revision_id,
            member_id=node.member_id,
            member_configuration_id=node.member_configuration_id,
            member_branch_basis_id=node.member_branch_basis_id,
            attempt_id=retry_attempt_id,
            node_key=authority.node_key,
            opened_reason="semantic_retry",
            predecessor_dispatch_id=None,
            flow_start_source_flow_id=None,
        ),
    )


__all__ = ["PreparedSemanticRetry", "prepare_semantic_retry"]
