from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload
from sqlalchemy.sql.elements import ColumnElement

from banksia.persistence.models import (
    AssignmentModel,
    AttemptModel,
    MemberConfigurationModel,
    TaskModel,
    TaskStartSourceModel,
    TeamRevisionMemberModel,
    WorkflowRevisionModel,
    WorkspaceBindingModel,
)
from banksia.runtime.assignment import read_assignment_file_references
from banksia.runtime.capabilities import resolve_effective_capabilities_for_member_configuration
from banksia.runtime.contracts.capabilities import EffectiveCapabilitySet
from banksia.runtime.contracts.primitives import TaskRootPaths
from banksia.runtime.contracts.prompt import (
    OperatorContinueResult,
    OperatorContinueSource,
    OperatorContinueTrigger,
)
from banksia.runtime.contracts.provider_resolution import ProviderResolution
from banksia.runtime.contracts.refs import FileReference
from banksia.runtime.contracts.team_read import DirectTeamMemberRead
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.dispatch.prompt_snapshot import RootPromptSnapshot, RootPromptTrigger
from banksia.runtime.providers import narrow_provider_capabilities, resolve_member_provider_route
from banksia.runtime.task_root import read_task_root_paths
from banksia.runtime.team.reads import read_direct_team_members
from banksia.runtime.work_plan import WorkPlanRead, read_assignment_work_plan

type RootSourceTaskStatus = Literal["running", "paused"]


@dataclass(frozen=True, slots=True)
class RootOpeningSnapshot:
    source_committed_at: datetime
    task_control_revision: int
    task_root_path: str
    workspace_root_path: str
    assignment_work_plan_revision: int
    prompt: RootPromptSnapshot
    provider: ProviderResolution
    capabilities: EffectiveCapabilitySet
    paths: TaskRootPaths
    expected_task_status: RootSourceTaskStatus
    expected_pause_reason: str | None
    opened_reason: Literal["root", "operator_continue"]
    trigger: RootPromptTrigger | None


@dataclass(frozen=True, slots=True)
class _TaskStartState:
    source: TaskStartSourceModel
    task: TaskModel


@dataclass(frozen=True, slots=True)
class _RootRuntimeContext:
    workspace: WorkspaceBindingModel
    workflow: WorkflowRevisionModel
    selection: TeamRevisionMemberModel
    configuration: MemberConfigurationModel
    assignment: AssignmentModel
    attempt: AttemptModel


async def read_root_opening_snapshot(
    session: AsyncSession,
    *,
    task_id: str,
    dispatch_id: str,
    dependencies: DispatchOpeningDependencies,
    expected_task_status: RootSourceTaskStatus,
    expected_team_revision_id: str | None,
    expected_control_revision: int | None,
) -> RootOpeningSnapshot | None:
    """Read one exact unconsumed Task-start source and its pinned root truth."""

    state = await _read_task_start_state(
        session,
        task_id=task_id,
        expected_task_status=expected_task_status,
        expected_team_revision_id=expected_team_revision_id,
        expected_control_revision=expected_control_revision,
    )
    if state is None:
        return None
    context = await _read_root_runtime_context(session, state)
    children = tuple(
        await session.scalars(
            select(TeamRevisionMemberModel)
            .options(raiseload("*"))
            .where(
                TeamRevisionMemberModel.task_id == task_id,
                TeamRevisionMemberModel.team_revision_id == context.selection.team_revision_id,
                TeamRevisionMemberModel.parent_member_id == context.selection.member_id,
            )
            .order_by(TeamRevisionMemberModel.sibling_order)
        )
    )
    work_plan = await read_assignment_work_plan(
        session,
        assignment_id=context.assignment.assignment_id,
    )
    assignment_files = await read_assignment_file_references(
        session,
        assignment_id=context.assignment.assignment_id,
    )
    capabilities = await resolve_effective_capabilities_for_member_configuration(
        session,
        task_id=task_id,
        member_configuration_id=context.selection.member_configuration_id,
    )
    provider = await resolve_member_provider_route(
        session,
        task_id=task_id,
        member_configuration_id=context.selection.member_configuration_id,
        settings=dependencies.settings,
        available_adapter_kinds=dependencies.available_adapter_kinds,
    )
    capabilities = narrow_provider_capabilities(
        route=provider.route,
        sandbox=provider.sandbox,
        capabilities=capabilities,
    )
    paths = await read_task_root_paths(session, task_id)
    direct_team = await read_direct_team_members(
        session,
        children=children,
        dependencies=dependencies,
    )
    trigger, opened_reason = _root_trigger(state.task, expected_task_status)
    prompt = _build_root_prompt_snapshot(
        state.task,
        context,
        dispatch_id=dispatch_id,
        work_plan=work_plan,
        capabilities=capabilities,
        provider=provider,
        direct_team=direct_team,
        paths=paths,
        assignment_files=assignment_files,
    )
    return RootOpeningSnapshot(
        source_committed_at=state.source.committed_at,
        task_control_revision=state.task.control_revision,
        task_root_path=state.task.task_root_path,
        workspace_root_path=context.workspace.normalized_root_path,
        assignment_work_plan_revision=context.assignment.work_plan_revision,
        prompt=prompt,
        provider=provider,
        capabilities=capabilities,
        paths=paths,
        expected_task_status=expected_task_status,
        expected_pause_reason=state.task.pause_reason,
        opened_reason=opened_reason,
        trigger=trigger,
    )


def root_context_is_current(snapshot: RootOpeningSnapshot) -> ColumnElement[bool]:
    """Return final-transaction predicates for the prepared root context."""

    prompt = snapshot.prompt
    return (
        exists().where(
            TeamRevisionMemberModel.task_id == prompt.task_id,
            TeamRevisionMemberModel.team_revision_id == prompt.team_revision_id,
            TeamRevisionMemberModel.member_id == prompt.member_id,
            TeamRevisionMemberModel.parent_member_id.is_(None),
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
            AssignmentModel.superseded_at.is_(None),
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
            TaskModel.root_assignment_id == prompt.assignment_id,
            TaskModel.current_team_revision_id == prompt.team_revision_id,
        )
        & exists().where(
            WorkspaceBindingModel.task_id == prompt.task_id,
            WorkspaceBindingModel.normalized_root_path == snapshot.workspace_root_path,
        )
    )


async def _read_task_start_state(
    session: AsyncSession,
    *,
    task_id: str,
    expected_task_status: RootSourceTaskStatus,
    expected_team_revision_id: str | None,
    expected_control_revision: int | None,
) -> _TaskStartState | None:
    row = (
        await session.execute(
            select(TaskStartSourceModel, TaskModel)
            .options(raiseload("*"))
            .join(TaskModel, TaskModel.task_id == TaskStartSourceModel.task_id)
            .where(TaskStartSourceModel.task_id == task_id)
        )
    ).one_or_none()
    if row is None:
        return None
    source, task = row
    is_current = (
        source.successor_dispatch_id is None
        and task.status == expected_task_status
        and task.current_team_revision_id is not None
        and task.root_assignment_id == source.root_assignment_id
        and (
            expected_team_revision_id is None
            or task.current_team_revision_id == expected_team_revision_id
        )
        and (
            expected_control_revision is None or task.control_revision == expected_control_revision
        )
        and (expected_task_status != "paused" or task.pause_reason is not None)
    )
    return _TaskStartState(source, task) if is_current else None


async def _read_root_runtime_context(
    session: AsyncSession,
    state: _TaskStartState,
) -> _RootRuntimeContext:
    task = state.task
    assert task.current_team_revision_id is not None
    row = (
        await session.execute(
            select(
                WorkspaceBindingModel,
                WorkflowRevisionModel,
                TeamRevisionMemberModel,
                MemberConfigurationModel,
                AssignmentModel,
                AttemptModel,
            )
            .options(raiseload("*"))
            .select_from(TaskModel)
            .join(WorkspaceBindingModel, WorkspaceBindingModel.task_id == TaskModel.task_id)
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
                & (TeamRevisionMemberModel.parent_member_id.is_(None)),
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
                AssignmentModel,
                (AssignmentModel.task_id == TaskModel.task_id)
                & (AssignmentModel.assignment_id == state.source.root_assignment_id)
                & (AssignmentModel.member_id == TeamRevisionMemberModel.member_id),
            )
            .join(
                AttemptModel,
                (AttemptModel.task_id == TaskModel.task_id)
                & (AttemptModel.assignment_id == AssignmentModel.assignment_id)
                & (AttemptModel.attempt_id == state.source.root_attempt_id),
            )
            .where(TaskModel.task_id == task.task_id)
        )
    ).one_or_none()
    if row is None:
        raise ValueError("runnable Task start is missing its root runtime context")
    context = _RootRuntimeContext(*row)
    if (
        context.assignment.current_attempt_id != context.attempt.attempt_id
        or context.assignment.terminal_outcome is not None
        or context.assignment.superseded_at is not None
        or context.attempt.status != "running"
        or context.attempt.current_dispatch_id is not None
        or context.attempt.current_wait_id is not None
    ):
        raise ValueError("runnable Task start has inconsistent pinned root context")
    return context


def _build_root_prompt_snapshot(
    task: TaskModel,
    context: _RootRuntimeContext,
    *,
    dispatch_id: str,
    work_plan: WorkPlanRead | None,
    capabilities: EffectiveCapabilitySet,
    provider: ProviderResolution,
    direct_team: tuple[DirectTeamMemberRead, ...],
    paths: TaskRootPaths,
    assignment_files: tuple[FileReference, ...],
) -> RootPromptSnapshot:
    workflow_note = context.workflow.content_json.get("note")
    if workflow_note is not None and not isinstance(workflow_note, str):
        raise ValueError("pinned Workflow note must be text")
    selection = context.selection
    configuration = context.configuration
    assignment = context.assignment
    attempt = context.attempt
    return RootPromptSnapshot(
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
        work_plan=work_plan,
        capabilities=capabilities,
        provider=provider,
        direct_team=direct_team,
        paths=paths,
    )


def _root_trigger(
    task: TaskModel,
    expected_task_status: RootSourceTaskStatus,
) -> tuple[RootPromptTrigger | None, Literal["root", "operator_continue"]]:
    if expected_task_status == "running":
        return None, "root"
    if task.pause_reason is None:
        raise ValueError("paused Task start is missing its pause reason")
    return (
        OperatorContinueTrigger(
            source=OperatorContinueSource(source_task_id=task.task_id),
            result=OperatorContinueResult(
                control_revision=task.control_revision,
                pause_reason=task.pause_reason,
            ),
        ),
        "operator_continue",
    )


__all__ = [
    "RootOpeningSnapshot",
    "RootSourceTaskStatus",
    "read_root_opening_snapshot",
    "root_context_is_current",
]
