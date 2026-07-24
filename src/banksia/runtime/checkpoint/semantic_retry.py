"""Prepare the first Dispatch of a semantic retry before its atomic commit."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from banksia.persistence.models import (
    MemberConfigurationModel,
    TaskModel,
    TeamRevisionMemberModel,
    WorkflowRevisionModel,
)
from banksia.runtime.assignment import read_assignment_file_references
from banksia.runtime.capabilities import resolve_effective_capabilities_for_member_configuration
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
from banksia.runtime.providers import narrow_provider_capabilities, resolve_member_provider_route
from banksia.runtime.task_root import read_task_root_paths
from banksia.runtime.team.reads import read_direct_team_members
from banksia.runtime.work_plan import WorkPlanRead, read_assignment_work_plan


@dataclass(frozen=True, slots=True)
class PreparedSemanticRetry:
    request: PreparedDispatchRequest
    basis: StartingDispatchBasis


@dataclass(frozen=True, slots=True)
class _SemanticRetryContext:
    task: TaskModel
    workflow_note: str | None
    selection: TeamRevisionMemberModel
    configuration: MemberConfigurationModel
    children: tuple[TeamRevisionMemberModel, ...]


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
    selection = context.selection
    return PreparedSemanticRetry(
        request=prepared,
        basis=StartingDispatchBasis(
            task_id=authority.task_id,
            assignment_id=authority.assignment_id,
            team_revision_id=selection.team_revision_id,
            member_id=selection.member_id,
            member_configuration_id=selection.member_configuration_id,
            member_branch_basis_id=selection.member_branch_basis_id,
            attempt_id=retry_attempt_id,
            opened_reason="semantic_retry",
            predecessor_dispatch_id=None,
            task_start_source_task_id=None,
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
    selection = context.selection
    capabilities = await resolve_effective_capabilities_for_member_configuration(
        session,
        task_id=authority.task_id,
        member_configuration_id=selection.member_configuration_id,
    )
    provider = await resolve_member_provider_route(
        session,
        task_id=authority.task_id,
        member_configuration_id=selection.member_configuration_id,
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
                TaskModel,
                WorkflowRevisionModel,
                TeamRevisionMemberModel,
                MemberConfigurationModel,
            )
            .options(raiseload("*"))
            .join(
                WorkflowRevisionModel,
                (WorkflowRevisionModel.workflow_key == TaskModel.workflow_key)
                & (WorkflowRevisionModel.revision_no == TaskModel.workflow_revision_no)
                & (WorkflowRevisionModel.content_hash == TaskModel.workflow_content_hash),
            )
            .join(
                TeamRevisionMemberModel,
                (TeamRevisionMemberModel.task_id == TaskModel.task_id)
                & (TeamRevisionMemberModel.team_revision_id == TaskModel.current_team_revision_id)
                & (TeamRevisionMemberModel.member_id == authority.member_id)
                & (
                    TeamRevisionMemberModel.member_configuration_id
                    == authority.dispatch.member_configuration_id
                )
                & (
                    TeamRevisionMemberModel.member_branch_basis_id
                    == authority.dispatch.member_branch_basis_id
                ),
            )
            .join(
                MemberConfigurationModel,
                (MemberConfigurationModel.task_id == TeamRevisionMemberModel.task_id)
                & (
                    MemberConfigurationModel.member_configuration_id
                    == TeamRevisionMemberModel.member_configuration_id
                )
                & (MemberConfigurationModel.member_id == TeamRevisionMemberModel.member_id),
            )
            .where(
                TaskModel.task_id == authority.task_id,
                TaskModel.status == "running",
            )
        )
    ).one_or_none()
    if row is None:
        raise ValueError("semantic retry lost its current retained Member selection")
    task, workflow, selection, configuration = row
    workflow_note = workflow.content_json.get("note")
    if workflow_note is not None and not isinstance(workflow_note, str):
        raise ValueError("pinned Workflow note must be text")
    children = tuple(
        await session.scalars(
            select(TeamRevisionMemberModel)
            .options(raiseload("*"))
            .where(
                TeamRevisionMemberModel.task_id == task.task_id,
                TeamRevisionMemberModel.team_revision_id == selection.team_revision_id,
                TeamRevisionMemberModel.parent_member_id == selection.member_id,
            )
            .order_by(TeamRevisionMemberModel.sibling_order)
        )
    )
    return _SemanticRetryContext(
        task=task,
        workflow_note=workflow_note,
        selection=selection,
        configuration=configuration,
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
    selection = context.selection
    configuration = context.configuration
    node_kind = (
        "root"
        if context.task.root_assignment_id == authority.assignment_id
        else "parent"
        if direct_team
        else "worker"
    )
    return SemanticRetryPromptSnapshot(
        task_id=authority.task_id,
        workflow_key=context.task.workflow_key,
        dispatch_id=dispatch_id,
        assignment_id=authority.assignment_id,
        attempt_id=attempt_id,
        retry_of_attempt_id=authority.attempt_id,
        team_revision_id=selection.team_revision_id,
        member_id=selection.member_id,
        member_configuration_id=selection.member_configuration_id,
        member_branch_basis_id=selection.member_branch_basis_id,
        member_title=configuration.title,
        member_description=configuration.description,
        member_instruction=configuration.instruction,
        workflow_note=context.workflow_note,
        assignment_prompt=authority.assignment.prompt,
        assignment_files=assignment_files,
        work_plan=work_plan,
        capabilities=capabilities,
        provider=provider,
        direct_team=direct_team,
        paths=paths,
        node_kind=node_kind,
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
