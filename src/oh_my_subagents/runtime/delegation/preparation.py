from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from oh_my_subagents.persistence.models import (
    AssignmentModel,
    AttemptModel,
    MemberConfigurationModel,
    TaskModel,
    TeamRevisionMemberModel,
    WorkflowRevisionModel,
)
from oh_my_subagents.runtime.assignment import AssignmentBudgetSnapshot
from oh_my_subagents.runtime.assignment.budget import snapshot_assignment_budget
from oh_my_subagents.runtime.capabilities import (
    resolve_effective_capabilities_for_member_configuration,
)
from oh_my_subagents.runtime.contracts import (
    DelegatedAssignment,
    DelegateRequest,
    FileReference,
    TaskRootPaths,
)
from oh_my_subagents.runtime.contracts.capabilities import EffectiveCapabilitySet
from oh_my_subagents.runtime.contracts.operation_failure import OperationFailureCode
from oh_my_subagents.runtime.contracts.provider_resolution import ProviderResolution
from oh_my_subagents.runtime.contracts.team_read import DirectTeamMemberRead
from oh_my_subagents.runtime.dispatch.authority import (
    NodeOperationAuthority,
    exact_node_operation_authority_exists,
)
from oh_my_subagents.runtime.dispatch.preparation import (
    DispatchOpeningDependencies,
    PreparedDispatchRequest,
    prepare_dispatch_request,
)
from oh_my_subagents.runtime.dispatch.prompt_snapshot import (
    RootPromptSnapshot,
    build_delegated_child_dispatch_request,
)
from oh_my_subagents.runtime.errors import RuntimeOperationError, budget_exhausted_error
from oh_my_subagents.runtime.file_references import validate_file_references
from oh_my_subagents.runtime.providers import (
    ProviderResolutionError,
    narrow_provider_capabilities,
    resolve_member_provider_route,
)
from oh_my_subagents.runtime.team.reads import read_direct_team_members

PUBLIC_MAX_WAVE_MEMBERS = 8


@dataclass(frozen=True, slots=True)
class DelegationContext:
    task: TaskModel
    workflow: WorkflowRevisionModel
    parent_selection: TeamRevisionMemberModel
    budget: AssignmentBudgetSnapshot


@dataclass(frozen=True, slots=True)
class DelegationTarget:
    selection: TeamRevisionMemberModel
    configuration: MemberConfigurationModel


@dataclass(frozen=True, slots=True)
class PreparedWaveMember:
    authored: DelegatedAssignment
    target: DelegationTarget
    assignment: AssignmentModel
    attempt: AttemptModel
    files: tuple[FileReference, ...]
    dispatch: PreparedDispatchRequest


async def read_delegation_context(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> DelegationContext:
    row = (
        await session.execute(
            select(TaskModel, WorkflowRevisionModel, TeamRevisionMemberModel)
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
            .where(
                TaskModel.task_id == authority.task_id,
                TaskModel.status == "running",
                exact_node_operation_authority_exists(authority),
            )
        )
    ).one_or_none()
    if row is None:
        raise delegation_conflict("another transition changed exact delegation authority")
    task, workflow, parent_selection = row
    return DelegationContext(
        task=task,
        workflow=workflow,
        parent_selection=parent_selection,
        budget=snapshot_assignment_budget(
            child_assignment_limit=task.max_child_assignments_per_assignment,
            retry_limit=task.max_retries_per_assignment,
        ),
    )


def require_wave_size(task: TaskModel, member_count: int) -> None:
    limit = min(task.max_wave_members, PUBLIC_MAX_WAVE_MEMBERS)
    if member_count > limit:
        raise budget_exhausted_error(
            f"delegate requested {member_count} members but this Task allows at most {limit}"
        )


async def read_direct_targets(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    request: DelegateRequest,
    *,
    team_revision_id: str,
) -> dict[str, DelegationTarget]:
    child_ids = tuple(assignment.child_id for assignment in request.assignments)
    rows = tuple(
        (
            await session.execute(
                select(TeamRevisionMemberModel, MemberConfigurationModel)
                .options(raiseload("*"))
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
                    TeamRevisionMemberModel.task_id == authority.task_id,
                    TeamRevisionMemberModel.team_revision_id == team_revision_id,
                    TeamRevisionMemberModel.parent_member_id == authority.member_id,
                    TeamRevisionMemberModel.member_id.in_(child_ids),
                )
            )
        ).all()
    )
    targets = {
        selection.member_id: DelegationTarget(selection, configuration)
        for selection, configuration in rows
    }
    missing = tuple(child_id for child_id in child_ids if child_id not in targets)
    if missing:
        raise RuntimeOperationError(
            code=OperationFailureCode.ILLEGAL_TARGET_RELATION,
            summary=(
                "delegate may target only current direct children; unknown or indirect: "
                f"{', '.join(missing)}"
            ),
            is_retryable=False,
        )
    return targets


async def prepare_wave_members(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    request: DelegateRequest,
    *,
    targets: dict[str, DelegationTarget],
    context: DelegationContext,
    workspace_path: Path,
    paths: TaskRootPaths,
    due_at: datetime,
    dependencies: DispatchOpeningDependencies,
) -> tuple[PreparedWaveMember, ...]:
    prepared: list[PreparedWaveMember] = []
    for authored in request.assignments:
        prepared.append(
            await _prepare_wave_member(
                session,
                authority,
                authored,
                target=targets[authored.child_id],
                context=context,
                workspace_path=workspace_path,
                paths=paths,
                due_at=due_at,
                dependencies=dependencies,
            )
        )
    return tuple(prepared)


def delegation_conflict(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary=summary,
        is_retryable=False,
    )


async def _prepare_wave_member(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    authored: DelegatedAssignment,
    *,
    target: DelegationTarget,
    context: DelegationContext,
    workspace_path: Path,
    paths: TaskRootPaths,
    due_at: datetime,
    dependencies: DispatchOpeningDependencies,
) -> PreparedWaveMember:
    await _require_available_child(session, authority, target.selection)
    files = validate_file_references(workspace_path, authored.files)
    assignment, attempt = _new_child_work(
        authority,
        authored,
        target=target.selection,
        budget=context.budget,
        opened_at=due_at,
    )
    children = tuple(
        await session.scalars(
            select(TeamRevisionMemberModel)
            .options(raiseload("*"))
            .where(
                TeamRevisionMemberModel.task_id == authority.task_id,
                TeamRevisionMemberModel.team_revision_id == target.selection.team_revision_id,
                TeamRevisionMemberModel.parent_member_id == target.selection.member_id,
            )
            .order_by(TeamRevisionMemberModel.sibling_order)
        )
    )
    prepared = await _prepare_child_dispatch(
        session,
        authority,
        authored,
        target=target,
        context=context,
        assignment=assignment,
        attempt=attempt,
        files=files,
        children=children,
        dispatch_id=f"dispatch.{uuid4().hex}",
        paths=paths,
        due_at=due_at,
        dependencies=dependencies,
    )
    return PreparedWaveMember(
        authored=authored,
        target=target,
        assignment=assignment,
        attempt=attempt,
        files=files,
        dispatch=prepared,
    )


async def _prepare_child_dispatch(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    authored: DelegatedAssignment,
    *,
    target: DelegationTarget,
    context: DelegationContext,
    assignment: AssignmentModel,
    attempt: AttemptModel,
    files: tuple[FileReference, ...],
    children: tuple[TeamRevisionMemberModel, ...],
    dispatch_id: str,
    paths: TaskRootPaths,
    due_at: datetime,
    dependencies: DispatchOpeningDependencies,
) -> PreparedDispatchRequest:
    selection = target.selection
    try:
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
        direct_team = await read_direct_team_members(
            session,
            children=children,
            dependencies=dependencies,
        )
        prompt = _build_delegated_child_prompt_snapshot(
            authority,
            authored,
            target=target,
            context=context,
            assignment=assignment,
            attempt=attempt,
            files=files,
            dispatch_id=dispatch_id,
            capabilities=capabilities,
            provider=provider,
            direct_team=direct_team,
            paths=paths,
        )
        return prepare_dispatch_request(
            dependencies=dependencies,
            dispatch_id=dispatch_id,
            due_at=due_at,
            provider=provider,
            capabilities=capabilities,
            request=build_delegated_child_dispatch_request(prompt),
        )
    except RuntimeOperationError:
        raise
    except (ProviderResolutionError, ValueError, OSError) as exc:
        raise RuntimeOperationError(
            code=OperationFailureCode.ILLEGAL_STATE,
            summary=f"could not prepare delegated child '{authored.child_id}'",
            is_retryable=False,
            suggested_next_step=(
                "Repair the selected child's provider or Workflow configuration and retry "
                "the complete delegation."
            ),
        ) from exc


def _build_delegated_child_prompt_snapshot(
    authority: NodeOperationAuthority,
    authored: DelegatedAssignment,
    *,
    target: DelegationTarget,
    context: DelegationContext,
    assignment: AssignmentModel,
    attempt: AttemptModel,
    files: tuple[FileReference, ...],
    dispatch_id: str,
    capabilities: EffectiveCapabilitySet,
    provider: ProviderResolution,
    direct_team: tuple[DirectTeamMemberRead, ...],
    paths: TaskRootPaths,
) -> RootPromptSnapshot:
    note = context.workflow.content_json.get("note")
    if note is not None and not isinstance(note, str):
        raise ValueError("pinned Workflow note must be text")
    selection = target.selection
    configuration = target.configuration
    return RootPromptSnapshot(
        task_id=authority.task_id,
        workflow_key=context.task.workflow_key,
        dispatch_id=dispatch_id,
        assignment_id=assignment.assignment_id,
        attempt_id=attempt.attempt_id,
        retry_of_attempt_id=None,
        team_revision_id=selection.team_revision_id,
        member_id=selection.member_id,
        member_configuration_id=selection.member_configuration_id,
        member_branch_basis_id=selection.member_branch_basis_id,
        member_title=configuration.title,
        member_description=configuration.description,
        member_instruction=configuration.instruction,
        workflow_note=note,
        assignment_prompt=authored.prompt,
        assignment_files=files,
        work_plan=None,
        capabilities=capabilities,
        provider=provider,
        direct_team=direct_team,
        paths=paths,
    )


async def _require_available_child(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    target: TeamRevisionMemberModel,
) -> None:
    is_busy = bool(
        await session.scalar(
            select(
                exists().where(
                    AssignmentModel.task_id == authority.task_id,
                    AssignmentModel.member_id == target.member_id,
                    AssignmentModel.terminal_outcome.is_(None),
                )
            )
        )
    )
    if is_busy:
        raise _delegation_illegal_state(
            f"direct child '{target.member_id}' already has active work"
        )


def _new_child_work(
    authority: NodeOperationAuthority,
    authored: DelegatedAssignment,
    *,
    target: TeamRevisionMemberModel,
    budget: AssignmentBudgetSnapshot,
    opened_at: datetime,
) -> tuple[AssignmentModel, AttemptModel]:
    suffix = uuid4().hex
    assignment_id = f"assignment.{authority.task_id}.{target.member_id}.{suffix}"
    attempt_id = f"attempt.{authority.task_id}.{target.member_id}.{suffix}"
    return (
        AssignmentModel(
            assignment_id=assignment_id,
            task_id=authority.task_id,
            member_id=target.member_id,
            parent_assignment_id=authority.assignment_id,
            prompt=authored.prompt,
            current_attempt_id=attempt_id,
            work_plan_revision=0,
            child_assignment_limit=budget.child_assignment_limit,
            child_assignments_remaining=budget.child_assignments_remaining,
            retry_limit=budget.retry_limit,
            retries_remaining=budget.retries_remaining,
            created_by_dispatch_id=authority.dispatch_id,
            created_at=opened_at,
        ),
        AttemptModel(
            attempt_id=attempt_id,
            assignment_id=assignment_id,
            task_id=authority.task_id,
            retry_of_attempt_id=None,
            latest_checkpoint_id=None,
            status="running",
            opened_at=opened_at,
        ),
    )


def _delegation_illegal_state(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.ILLEGAL_STATE,
        summary=summary,
        is_retryable=False,
    )


__all__ = [
    "DelegationContext",
    "DelegationTarget",
    "PreparedWaveMember",
    "delegation_conflict",
    "prepare_wave_members",
    "read_delegation_context",
    "read_direct_targets",
    "require_wave_size",
]
