from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload
from sqlalchemy.sql.elements import ColumnElement

from banksia.persistence.models import (
    AssignmentModel,
    AttemptModel,
    DispatchTurnModel,
    MemberConfigurationModel,
    TaskModel,
    TeamRevisionMemberModel,
    WorkflowRevisionModel,
    WorkspaceBindingModel,
)
from banksia.runtime.assignment import read_assignment_file_references
from banksia.runtime.capabilities import resolve_effective_capabilities_for_member_configuration
from banksia.runtime.contracts.capabilities import EffectiveCapabilitySet
from banksia.runtime.contracts.primitives import TaskRootPaths
from banksia.runtime.contracts.prompt import PromptSteer
from banksia.runtime.contracts.provider_resolution import ProviderResolution
from banksia.runtime.contracts.refs import FileReference
from banksia.runtime.contracts.team_read import DirectTeamMemberRead
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.dispatch.prompt_snapshot import OrdinaryPromptSnapshot, OrdinaryPromptTrigger
from banksia.runtime.providers import narrow_provider_capabilities, resolve_member_provider_route
from banksia.runtime.steering import read_assignment_prompt_steers
from banksia.runtime.task_root import read_task_root_paths
from banksia.runtime.team.reads import read_direct_team_members
from banksia.runtime.work_plan import WorkPlanRead, read_assignment_work_plan

type OrdinaryExpectedTaskStatus = Literal["running", "paused"]


@dataclass(frozen=True, slots=True)
class OrdinaryContinuationBasis:
    task_id: str
    assignment_id: str
    attempt_id: str
    source_dispatch_id: str
    source_dispatch_closed_reason: str
    opened_reason: str
    trigger: OrdinaryPromptTrigger
    continuation_source_id: str | None = None


@dataclass(frozen=True, slots=True)
class OrdinaryDispatchSnapshot:
    basis: OrdinaryContinuationBasis
    expected_task_status: OrdinaryExpectedTaskStatus
    expected_pause_reason: str | None
    task_control_revision: int
    task_root_path: str
    workspace_root_path: str
    assignment_work_plan_revision: int
    prompt: OrdinaryPromptSnapshot
    provider: ProviderResolution
    capabilities: EffectiveCapabilitySet
    paths: TaskRootPaths


@dataclass(frozen=True, slots=True)
class OrdinaryRuntimeContext:
    task: TaskModel
    workspace: WorkspaceBindingModel
    source_dispatch: DispatchTurnModel
    selection: TeamRevisionMemberModel
    configuration: MemberConfigurationModel
    assignment: AssignmentModel
    attempt: AttemptModel


async def read_ordinary_dispatch_snapshot(
    session: AsyncSession,
    *,
    basis: OrdinaryContinuationBasis,
    dispatch_id: str,
    dependencies: DispatchOpeningDependencies,
    expected_task_status: OrdinaryExpectedTaskStatus,
    expected_control_revision: int | None = None,
) -> OrdinaryDispatchSnapshot | None:
    context = await _read_ordinary_runtime_context(
        session,
        basis=basis,
        expected_task_status=expected_task_status,
        expected_control_revision=expected_control_revision,
    )
    if context is None:
        return None
    _validate_ordinary_runtime_context(context, basis=basis)
    workflow = await read_pinned_workflow_revision(session, context.task)
    children = await read_current_child_members(session, context)
    work_plan, assignment_files = await _read_assignment_context(
        session,
        assignment_id=context.assignment.assignment_id,
    )
    steering = await read_assignment_prompt_steers(
        session,
        assignment_id=context.assignment.assignment_id,
    )
    capabilities = await resolve_effective_capabilities_for_member_configuration(
        session,
        task_id=context.task.task_id,
        member_configuration_id=context.selection.member_configuration_id,
    )
    provider = await resolve_member_provider_route(
        session,
        task_id=context.task.task_id,
        member_configuration_id=context.selection.member_configuration_id,
        settings=dependencies.settings,
        available_adapter_kinds=dependencies.available_adapter_kinds,
    )
    capabilities = narrow_provider_capabilities(
        route=provider.route,
        sandbox=provider.sandbox,
        capabilities=capabilities,
    )
    paths = await read_task_root_paths(session, context.task.task_id)
    workflow_note = workflow.content_json.get("note")
    if workflow_note is not None and not isinstance(workflow_note, str):
        raise ValueError("ordinary continuation workflow note must be text")
    direct_team = await read_direct_team_members(
        session,
        children=children,
        dependencies=dependencies,
    )
    prompt = build_ordinary_prompt_snapshot(
        context,
        basis=basis,
        dispatch_id=dispatch_id,
        workflow_note=workflow_note,
        capabilities=capabilities,
        work_plan=work_plan,
        provider=provider,
        direct_team=direct_team,
        paths=paths,
        assignment_files=assignment_files,
        steering=steering,
    )
    return OrdinaryDispatchSnapshot(
        basis=basis,
        expected_task_status=expected_task_status,
        expected_pause_reason=context.task.pause_reason,
        task_control_revision=context.task.control_revision,
        task_root_path=context.task.task_root_path,
        workspace_root_path=context.workspace.normalized_root_path,
        assignment_work_plan_revision=context.assignment.work_plan_revision,
        prompt=prompt,
        provider=provider,
        capabilities=capabilities,
        paths=paths,
    )


def ordinary_context_is_current(snapshot: OrdinaryDispatchSnapshot) -> ColumnElement[bool]:
    prompt = snapshot.prompt
    basis = snapshot.basis
    return (
        exists().where(
            DispatchTurnModel.dispatch_id == basis.source_dispatch_id,
            DispatchTurnModel.task_id == basis.task_id,
            DispatchTurnModel.assignment_id == basis.assignment_id,
            DispatchTurnModel.attempt_id == basis.attempt_id,
            DispatchTurnModel.status == "closed",
            DispatchTurnModel.closed_reason == basis.source_dispatch_closed_reason,
        )
        & exists().where(
            TeamRevisionMemberModel.task_id == prompt.task_id,
            TeamRevisionMemberModel.team_revision_id == prompt.team_revision_id,
            TeamRevisionMemberModel.member_id == prompt.member_id,
            TeamRevisionMemberModel.member_configuration_id == prompt.member_configuration_id,
            TeamRevisionMemberModel.member_branch_basis_id == prompt.member_branch_basis_id,
        )
        & exists().where(
            AssignmentModel.assignment_id == prompt.assignment_id,
            AssignmentModel.task_id == prompt.task_id,
            AssignmentModel.member_id == prompt.member_id,
            AssignmentModel.current_attempt_id == prompt.attempt_id,
            AssignmentModel.work_plan_revision == snapshot.assignment_work_plan_revision,
            AssignmentModel.terminal_outcome.is_(None),
        )
        & exists().where(
            AttemptModel.attempt_id == prompt.attempt_id,
            AttemptModel.assignment_id == prompt.assignment_id,
            AttemptModel.task_id == prompt.task_id,
            AttemptModel.status == "running",
            AttemptModel.current_dispatch_id.is_(None),
            AttemptModel.current_wait_id.is_(None),
        )
        & exists().where(
            TaskModel.task_id == prompt.task_id,
            TaskModel.task_root_path == snapshot.task_root_path,
            TaskModel.current_team_revision_id == prompt.team_revision_id,
        )
        & exists().where(
            WorkspaceBindingModel.task_id == prompt.task_id,
            WorkspaceBindingModel.normalized_root_path == snapshot.workspace_root_path,
        )
    )


async def read_pinned_workflow_revision(
    session: AsyncSession,
    task: TaskModel,
) -> WorkflowRevisionModel:
    workflow = await session.scalar(
        select(WorkflowRevisionModel)
        .options(raiseload("*"))
        .where(
            WorkflowRevisionModel.workflow_key == task.workflow_key,
            WorkflowRevisionModel.revision_no == task.workflow_revision_no,
            WorkflowRevisionModel.content_hash == task.workflow_content_hash,
        )
    )
    if workflow is None:
        raise ValueError("ordinary continuation is missing its pinned Workflow revision")
    return workflow


async def read_current_child_members(
    session: AsyncSession,
    context: OrdinaryRuntimeContext,
) -> tuple[TeamRevisionMemberModel, ...]:
    return tuple(
        await session.scalars(
            select(TeamRevisionMemberModel)
            .options(raiseload("*"))
            .where(
                TeamRevisionMemberModel.task_id == context.task.task_id,
                TeamRevisionMemberModel.team_revision_id == context.selection.team_revision_id,
                TeamRevisionMemberModel.parent_member_id == context.selection.member_id,
            )
            .order_by(TeamRevisionMemberModel.sibling_order)
        )
    )


def build_ordinary_prompt_snapshot(
    context: OrdinaryRuntimeContext,
    *,
    basis: OrdinaryContinuationBasis,
    dispatch_id: str,
    workflow_note: str | None,
    capabilities: EffectiveCapabilitySet,
    work_plan: WorkPlanRead | None,
    provider: ProviderResolution,
    direct_team: tuple[DirectTeamMemberRead, ...],
    paths: TaskRootPaths,
    assignment_files: tuple[FileReference, ...],
    steering: tuple[PromptSteer, ...] = (),
) -> OrdinaryPromptSnapshot:
    task = context.task
    selection = context.selection
    configuration = context.configuration
    assignment = context.assignment
    attempt = context.attempt
    return OrdinaryPromptSnapshot(
        task_id=task.task_id,
        workflow_key=task.workflow_key,
        dispatch_id=dispatch_id,
        assignment_id=assignment.assignment_id,
        attempt_id=attempt.attempt_id,
        retry_of_attempt_id=attempt.retry_of_attempt_id,
        team_revision_id=selection.team_revision_id,
        member_id=selection.member_id,
        member_configuration_id=selection.member_configuration_id,
        member_branch_basis_id=selection.member_branch_basis_id,
        member_title=configuration.title,
        member_description=configuration.description,
        member_instruction=configuration.instruction,
        workflow_note=workflow_note,
        assignment_prompt=assignment.prompt,
        assignment_files=assignment_files,
        steering=steering,
        work_plan=work_plan,
        capabilities=capabilities,
        provider=provider,
        direct_team=direct_team,
        paths=paths,
        is_task_lead=task.root_assignment_id == assignment.assignment_id,
        predecessor_dispatch_id=basis.source_dispatch_id,
        trigger=basis.trigger,
    )


async def _read_assignment_context(
    session: AsyncSession,
    *,
    assignment_id: str,
) -> tuple[WorkPlanRead | None, tuple[FileReference, ...]]:
    work_plan = await read_assignment_work_plan(session, assignment_id=assignment_id)
    files = await read_assignment_file_references(session, assignment_id=assignment_id)
    return work_plan, files


async def _read_ordinary_runtime_context(
    session: AsyncSession,
    *,
    basis: OrdinaryContinuationBasis,
    expected_task_status: OrdinaryExpectedTaskStatus,
    expected_control_revision: int | None,
) -> OrdinaryRuntimeContext | None:
    statement = (
        select(
            TaskModel,
            WorkspaceBindingModel,
            DispatchTurnModel,
            TeamRevisionMemberModel,
            MemberConfigurationModel,
            AssignmentModel,
            AttemptModel,
        )
        .options(raiseload("*"))
        .select_from(AssignmentModel)
        .join(TaskModel, TaskModel.task_id == AssignmentModel.task_id)
        .join(WorkspaceBindingModel, WorkspaceBindingModel.task_id == TaskModel.task_id)
        .join(
            DispatchTurnModel,
            (DispatchTurnModel.dispatch_id == basis.source_dispatch_id)
            & (DispatchTurnModel.task_id == TaskModel.task_id),
        )
        .join(
            TeamRevisionMemberModel,
            (TeamRevisionMemberModel.task_id == TaskModel.task_id)
            & (TeamRevisionMemberModel.team_revision_id == TaskModel.current_team_revision_id)
            & (TeamRevisionMemberModel.member_id == AssignmentModel.member_id),
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
        .join(
            AttemptModel,
            (AttemptModel.task_id == AssignmentModel.task_id)
            & (AttemptModel.assignment_id == AssignmentModel.assignment_id)
            & (AttemptModel.attempt_id == basis.attempt_id),
        )
        .where(
            AssignmentModel.assignment_id == basis.assignment_id,
            AssignmentModel.task_id == basis.task_id,
            TaskModel.status == expected_task_status,
            AttemptModel.status == "running",
            AttemptModel.current_dispatch_id.is_(None),
            AttemptModel.current_wait_id.is_(None),
        )
    )
    if expected_control_revision is not None:
        statement = statement.where(TaskModel.control_revision == expected_control_revision)
    row = (await session.execute(statement)).one_or_none()
    return OrdinaryRuntimeContext(*row) if row is not None else None


def _validate_ordinary_runtime_context(
    context: OrdinaryRuntimeContext,
    *,
    basis: OrdinaryContinuationBasis,
) -> None:
    assignment = context.assignment
    attempt = context.attempt
    source_dispatch = context.source_dispatch
    selection = context.selection
    if (
        source_dispatch.task_id != basis.task_id
        or source_dispatch.assignment_id != basis.assignment_id
        or source_dispatch.attempt_id != basis.attempt_id
        or source_dispatch.status != "closed"
        or source_dispatch.closed_reason != basis.source_dispatch_closed_reason
        or assignment.current_attempt_id != attempt.attempt_id
        or assignment.terminal_outcome is not None
        or attempt.status != "running"
        or attempt.current_dispatch_id is not None
        or attempt.current_wait_id is not None
        or assignment.member_id != selection.member_id
        or context.task.current_team_revision_id != selection.team_revision_id
    ):
        raise ValueError("ordinary continuation has inconsistent exact runtime context")


__all__ = [
    "OrdinaryContinuationBasis",
    "OrdinaryDispatchSnapshot",
    "OrdinaryExpectedTaskStatus",
    "OrdinaryRuntimeContext",
    "build_ordinary_prompt_snapshot",
    "ordinary_context_is_current",
    "read_current_child_members",
    "read_ordinary_dispatch_snapshot",
    "read_pinned_workflow_revision",
]
