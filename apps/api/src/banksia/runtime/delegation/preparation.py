from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentModel,
    AttemptCheckpointModel,
    AttemptModel,
    CompiledPlanModel,
    FlowModel,
    FlowNodeModel,
    TaskModel,
    WorkflowRevisionModel,
)
from banksia.runtime.assignment import AssignmentBudgetSnapshot
from banksia.runtime.assignment.budget import snapshot_assignment_budget
from banksia.runtime.capabilities import resolve_effective_capabilities_for_node
from banksia.runtime.contracts import (
    DelegatedAssignment,
    DelegateRequest,
    FileReference,
    TaskRootPaths,
)
from banksia.runtime.contracts.capabilities import EffectiveCapabilitySet
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.contracts.provider_resolution import ProviderResolution
from banksia.runtime.contracts.team_read import DirectTeamMemberRead
from banksia.runtime.dispatch.authority import (
    NodeOperationAuthority,
    exact_node_operation_authority_exists,
)
from banksia.runtime.dispatch.preparation import (
    DispatchOpeningDependencies,
    PreparedDispatchRequest,
    prepare_dispatch_request,
)
from banksia.runtime.dispatch.prompt_snapshot import (
    RootPromptSnapshot,
    build_delegated_child_dispatch_request,
)
from banksia.runtime.errors import RuntimeOperationError, budget_exhausted_error
from banksia.runtime.file_references import validate_file_references
from banksia.runtime.providers import (
    ProviderResolutionError,
    narrow_provider_capabilities,
    resolve_member_provider_route,
)
from banksia.runtime.team.reads import read_direct_team_members

PUBLIC_MAX_WAVE_MEMBERS = 8


@dataclass(frozen=True, slots=True)
class DelegationContext:
    task: TaskModel
    compiled_plan: CompiledPlanModel
    workflow: WorkflowRevisionModel
    flow_revision_id: str
    parent_node: FlowNodeModel
    budget: AssignmentBudgetSnapshot


@dataclass(frozen=True, slots=True)
class PreparedWaveMember:
    authored: DelegatedAssignment
    node: FlowNodeModel
    previous_assignment: AssignmentModel | None
    assignment: AssignmentModel
    attempt: AttemptModel
    files: tuple[FileReference, ...]
    dispatch: PreparedDispatchRequest


@dataclass(frozen=True, slots=True)
class _CurrentChildCompletion:
    assignment: AssignmentModel | None
    attempt: AttemptModel | None
    checkpoint: AttemptCheckpointModel | None
    boundary: AcceptedBoundaryModel | None
    historical_parent: AssignmentModel | None


async def read_delegation_context(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> DelegationContext:
    row = (
        await session.execute(
            select(
                TaskModel,
                FlowModel,
                FlowNodeModel,
                CompiledPlanModel,
                WorkflowRevisionModel,
            )
            .options(raiseload("*"))
            .join(FlowModel, FlowModel.task_id == TaskModel.task_id)
            .join(
                FlowNodeModel,
                (FlowNodeModel.task_id == TaskModel.task_id)
                & (FlowNodeModel.flow_id == FlowModel.flow_id)
                & (FlowNodeModel.flow_revision_id == FlowModel.active_flow_revision_id)
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
            .join(
                CompiledPlanModel,
                CompiledPlanModel.compiled_plan_id == FlowModel.compiled_plan_id,
            )
            .join(
                WorkflowRevisionModel,
                (WorkflowRevisionModel.workflow_key == CompiledPlanModel.workflow_key)
                & (WorkflowRevisionModel.revision_no == CompiledPlanModel.workflow_revision_no),
            )
            .where(
                TaskModel.task_id == authority.task_id,
                FlowModel.flow_id == authority.flow_id,
                FlowModel.status == "running",
                FlowModel.active_flow_revision_id.is_not(None),
                exact_node_operation_authority_exists(authority),
            )
        )
    ).one_or_none()
    if row is None:
        raise delegation_conflict("another transition changed exact delegation authority")
    task, flow, parent_node, compiled_plan, workflow = row
    assert flow.active_flow_revision_id is not None
    return DelegationContext(
        task=task,
        compiled_plan=compiled_plan,
        workflow=workflow,
        flow_revision_id=flow.active_flow_revision_id,
        parent_node=parent_node,
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
    flow_revision_id: str,
) -> dict[str, FlowNodeModel]:
    child_ids = tuple(assignment.child_id for assignment in request.assignments)
    rows = tuple(
        await session.scalars(
            select(FlowNodeModel)
            .options(raiseload("*"))
            .where(
                FlowNodeModel.task_id == authority.task_id,
                FlowNodeModel.flow_id == authority.flow_id,
                FlowNodeModel.flow_revision_id == flow_revision_id,
                FlowNodeModel.parent_node_key == authority.node_key,
                FlowNodeModel.member_id.in_(child_ids),
            )
        )
    )
    targets = {node.member_id: node for node in rows}
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
    targets: dict[str, FlowNodeModel],
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
    target: FlowNodeModel,
    context: DelegationContext,
    workspace_path: Path,
    paths: TaskRootPaths,
    due_at: datetime,
    dependencies: DispatchOpeningDependencies,
) -> PreparedWaveMember:
    previous_assignment = await _read_available_child(session, authority, target)
    files = validate_file_references(workspace_path, authored.files)
    assignment, attempt = _new_child_work(
        authority,
        authored,
        target=target,
        budget=context.budget,
        opened_at=due_at,
    )
    dispatch_id = f"dispatch.{uuid4().hex}"
    children = tuple(
        await session.scalars(
            select(FlowNodeModel)
            .options(raiseload("*"))
            .where(
                FlowNodeModel.task_id == authority.task_id,
                FlowNodeModel.flow_id == authority.flow_id,
                FlowNodeModel.flow_revision_id == target.flow_revision_id,
                FlowNodeModel.parent_node_key == target.node_key,
            )
            .order_by(FlowNodeModel.order_index)
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
        dispatch_id=dispatch_id,
        paths=paths,
        due_at=due_at,
        dependencies=dependencies,
    )
    return PreparedWaveMember(
        authored=authored,
        node=target,
        previous_assignment=previous_assignment,
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
    target: FlowNodeModel,
    context: DelegationContext,
    assignment: AssignmentModel,
    attempt: AttemptModel,
    files: tuple[FileReference, ...],
    children: tuple[FlowNodeModel, ...],
    dispatch_id: str,
    paths: TaskRootPaths,
    due_at: datetime,
    dependencies: DispatchOpeningDependencies,
) -> PreparedDispatchRequest:
    try:
        capabilities = await resolve_effective_capabilities_for_node(session, node=target)
        provider = await resolve_member_provider_route(
            session,
            task_id=authority.task_id,
            member_configuration_id=target.member_configuration_id,
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
    target: FlowNodeModel,
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
    return RootPromptSnapshot(
        task_id=authority.task_id,
        workflow_key=context.compiled_plan.workflow_key,
        flow_id=authority.flow_id,
        flow_revision_id=target.flow_revision_id,
        dispatch_id=dispatch_id,
        assignment_id=assignment.assignment_id,
        attempt_id=attempt.attempt_id,
        retry_of_attempt_id=None,
        node_key=target.node_key,
        flow_node_id=target.flow_node_id,
        team_revision_id=target.team_revision_id,
        member_id=target.member_id,
        member_configuration_id=target.member_configuration_id,
        member_branch_basis_id=target.member_branch_basis_id,
        member_title=target.member_title,
        member_description=target.description,
        member_instruction=target.node_instruction,
        workflow_note=note,
        assignment_prompt=authored.prompt,
        assignment_files=files,
        work_plan=None,
        capabilities=capabilities,
        provider=provider,
        direct_team=direct_team,
        paths=paths,
    )


async def _read_available_child(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    target: FlowNodeModel,
) -> AssignmentModel | None:
    if target.current_assignment_id is None:
        if target.state != "ready":
            raise _delegation_illegal_state(f"direct child '{target.member_id}' is not available")
        return None

    completion = await _read_child_completion(session, authority, target)
    if not _child_completion_is_available(authority, target, completion):
        raise _delegation_illegal_state(
            f"direct child '{target.member_id}' has active or inconsistent current work"
        )
    return completion.assignment


async def _read_child_completion(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    target: FlowNodeModel,
) -> _CurrentChildCompletion:
    previous = await session.get(AssignmentModel, target.current_assignment_id)
    attempt = (
        await session.get(AttemptModel, previous.current_attempt_id)
        if previous is not None and previous.current_attempt_id is not None
        else None
    )
    checkpoint = (
        await session.get(AttemptCheckpointModel, attempt.latest_checkpoint_id)
        if attempt is not None and attempt.latest_checkpoint_id is not None
        else None
    )
    boundary = (
        await session.scalar(
            select(AcceptedBoundaryModel).where(
                AcceptedBoundaryModel.task_id == authority.task_id,
                AcceptedBoundaryModel.flow_id == authority.flow_id,
                AcceptedBoundaryModel.assignment_id == previous.assignment_id,
                AcceptedBoundaryModel.attempt_id == attempt.attempt_id,
                AcceptedBoundaryModel.checkpoint_id == checkpoint.checkpoint_id,
                AcceptedBoundaryModel.outcome.in_(("green", "blocked")),
            )
        )
        if previous is not None and attempt is not None and checkpoint is not None
        else None
    )
    parent_is_current = (
        previous is not None and previous.parent_assignment_id == authority.assignment_id
    )
    historical_parent = (
        await session.get(AssignmentModel, previous.parent_assignment_id)
        if previous is not None
        and previous.parent_assignment_id is not None
        and not parent_is_current
        else None
    )
    return _CurrentChildCompletion(
        assignment=previous,
        attempt=attempt,
        checkpoint=checkpoint,
        boundary=boundary,
        historical_parent=historical_parent,
    )


def _child_completion_is_available(
    authority: NodeOperationAuthority,
    target: FlowNodeModel,
    completion: _CurrentChildCompletion,
) -> bool:
    previous = completion.assignment
    attempt = completion.attempt
    checkpoint = completion.checkpoint
    boundary = completion.boundary
    historical_parent = completion.historical_parent
    parent_is_current = (
        previous is not None and previous.parent_assignment_id == authority.assignment_id
    )
    parent_is_same_member = parent_is_current or (
        historical_parent is not None
        and historical_parent.task_id == authority.task_id
        and historical_parent.flow_id == authority.flow_id
        and historical_parent.member_id == authority.assignment.member_id
        and historical_parent.node_key == authority.node_key
        and historical_parent.superseded_at is not None
    )
    expected_state = (
        "done" if previous is not None and previous.terminal_outcome == "green" else "failed"
    )
    return (
        previous is not None
        and previous.task_id == authority.task_id
        and previous.flow_id == authority.flow_id
        and previous.member_id == target.member_id
        and previous.node_key == target.node_key
        and parent_is_same_member
        and previous.superseded_at is None
        and previous.closed_at is not None
        and previous.terminal_outcome in {"green", "blocked"}
        and attempt is not None
        and attempt.task_id == authority.task_id
        and attempt.flow_id == authority.flow_id
        and attempt.assignment_id == previous.assignment_id
        and attempt.node_key == target.node_key
        and attempt.status == "completed"
        and attempt.terminal_outcome == previous.terminal_outcome
        and checkpoint is not None
        and checkpoint.task_id == authority.task_id
        and checkpoint.flow_id == authority.flow_id
        and checkpoint.assignment_id == previous.assignment_id
        and checkpoint.attempt_id == attempt.attempt_id
        and checkpoint.outcome == previous.terminal_outcome
        and boundary is not None
        and target.state == expected_state
    )


def _new_child_work(
    authority: NodeOperationAuthority,
    authored: DelegatedAssignment,
    *,
    target: FlowNodeModel,
    budget: AssignmentBudgetSnapshot,
    opened_at: datetime,
) -> tuple[AssignmentModel, AttemptModel]:
    suffix = uuid4().hex
    assignment_id = f"assignment.{authority.task_id}.{target.node_key}.{suffix}"
    attempt_id = f"attempt.{authority.task_id}.{target.node_key}.{suffix}"
    return (
        AssignmentModel(
            assignment_id=assignment_id,
            task_id=authority.task_id,
            member_id=target.member_id,
            flow_id=authority.flow_id,
            assignment_key=f"{authority.task_id}.{target.node_key}.{suffix}",
            node_key=target.node_key,
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
            flow_id=authority.flow_id,
            node_key=target.node_key,
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
    "PreparedWaveMember",
    "delegation_conflict",
    "prepare_wave_members",
    "read_delegation_context",
    "read_direct_targets",
    "require_wave_size",
]
