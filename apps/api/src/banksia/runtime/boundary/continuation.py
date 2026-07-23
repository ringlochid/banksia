from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentModel,
    AttemptModel,
    CompiledPlanModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
    NodePlanRevisionModel,
    TaskModel,
    WorkflowRevisionModel,
    WorkspaceBindingModel,
)
from banksia.runtime.assignment import read_assignment_file_references
from banksia.runtime.boundary.opening_commit import (
    commit_boundary_dispatch_if_current,
    pause_failed_boundary_continuation,
)
from banksia.runtime.boundary.target_resolution import (
    BoundaryTarget,
    require_consistent_target_runtime_context,
    resolve_boundary_target,
)
from banksia.runtime.capabilities import resolve_effective_capabilities_for_node
from banksia.runtime.contracts.capabilities import EffectiveCapabilitySet
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.contracts.primitives import TaskRootPaths
from banksia.runtime.contracts.provider_resolution import ProviderResolution
from banksia.runtime.contracts.refs import FileReference
from banksia.runtime.dispatch.opening import TaskResumeEventBasis
from banksia.runtime.dispatch.ordinary_continuation import publish_dispatch_start_due
from banksia.runtime.dispatch.preparation import (
    DispatchOpeningDependencies,
    PreparedDispatchRequest,
    prepare_dispatch_request,
)
from banksia.runtime.dispatch.prompt_snapshot import (
    BoundaryPromptSnapshot,
    RootPromptChildSnapshot,
    build_boundary_dispatch_request,
)
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.post_commit import BoundaryAccepted
from banksia.runtime.providers import (
    ProviderResolutionError,
    narrow_provider_capabilities,
    resolve_member_provider_route,
)
from banksia.runtime.task_root import read_task_root_paths
from banksia.runtime.work_plan import WorkPlanRead, read_assignment_work_plan

type BoundaryAcceptedHandler = Callable[[AsyncSession, BoundaryAccepted], Awaitable[None]]
type BoundaryOpeningOutcome = Literal["opened", "skipped", "terminal", "paused"]


@dataclass(frozen=True, slots=True)
class BoundaryOpeningResult:
    outcome: BoundaryOpeningOutcome
    dispatch_id: str | None = None


@dataclass(frozen=True, slots=True)
class _TargetRuntimeContext:
    task: TaskModel
    workspace: WorkspaceBindingModel
    compiled_plan: CompiledPlanModel
    node: FlowNodeModel
    node_plan: NodePlanRevisionModel
    assignment: AssignmentModel
    attempt: AttemptModel


@dataclass(frozen=True, slots=True)
class _BoundaryOpeningSnapshot:
    source_committed_at: datetime
    flow_control_revision: int
    task_root_path: str
    workspace_root_path: str
    compiled_plan_id: str
    node_plan_revision_id: str
    assignment_work_plan_revision: int
    source_outcome: str
    raw_provider_kind: str | None
    opened_reason: str
    prompt: BoundaryPromptSnapshot
    provider: ProviderResolution
    capabilities: EffectiveCapabilitySet
    paths: TaskRootPaths
    expected_flow_status: Literal["running", "paused"]
    expected_pause_reason: str | None


@dataclass(frozen=True, slots=True)
class _TerminalBoundary:
    pass


_TERMINAL_BOUNDARY = _TerminalBoundary()


def create_boundary_accepted_handler(
    dependencies: DispatchOpeningDependencies,
) -> BoundaryAcceptedHandler:
    async def handle(session: AsyncSession, signal: BoundaryAccepted) -> None:
        await open_boundary_successor(session, signal=signal, dependencies=dependencies)

    return handle


async def open_boundary_successor(
    session: AsyncSession,
    *,
    signal: BoundaryAccepted,
    dependencies: DispatchOpeningDependencies,
) -> BoundaryOpeningResult:
    due_at = dependencies.clock()
    try:
        candidate = await _prepare_boundary_successor(
            session,
            source_dispatch_id=signal.source_dispatch_id,
            dependencies=dependencies,
            due_at=due_at,
            expected_flow_status="running",
            expected_active_flow_revision_id=None,
            expected_control_revision=None,
        )
        if candidate is None:
            return BoundaryOpeningResult(outcome="skipped")
        if isinstance(candidate, _TerminalBoundary):
            return BoundaryOpeningResult(outcome="terminal")
        snapshot, prepared = candidate
    except (ProviderResolutionError, ValueError, OSError) as exc:
        await session.rollback()
        failure_code = getattr(exc, "code", "boundary_dispatch_preparation_failed")
        await pause_failed_boundary_continuation(
            session,
            source_dispatch_id=signal.source_dispatch_id,
            paused_at=due_at,
            failure_code=str(failure_code),
        )
        return BoundaryOpeningResult(outcome="paused")

    if not await commit_boundary_dispatch_if_current(
        session,
        snapshot=snapshot,
        prepared=prepared,
    ):
        return BoundaryOpeningResult(outcome="skipped")
    publish_dispatch_start_due(dependencies, prepared)
    return BoundaryOpeningResult(outcome="opened", dispatch_id=prepared.dispatch_id)


async def continue_paused_boundary(
    session: AsyncSession,
    *,
    source_dispatch_id: str,
    expected_active_flow_revision_id: str,
    expected_control_revision: int,
    dependencies: DispatchOpeningDependencies,
    resume_event: TaskResumeEventBasis,
) -> BoundaryOpeningResult:
    """Directly consume one repaired boundary retained by an exact paused flow."""
    try:
        candidate = await _prepare_boundary_successor(
            session,
            source_dispatch_id=source_dispatch_id,
            dependencies=dependencies,
            due_at=dependencies.clock(),
            expected_flow_status="paused",
            expected_active_flow_revision_id=expected_active_flow_revision_id,
            expected_control_revision=expected_control_revision,
        )
        if candidate is None or isinstance(candidate, _TerminalBoundary):
            raise _boundary_continue_conflict("paused boundary source is no longer current")
        snapshot, prepared = candidate
    except RuntimeOperationError:
        await session.rollback()
        raise
    except (ProviderResolutionError, ValueError, OSError) as exc:
        await session.rollback()
        raise _boundary_continue_preparation_error(exc) from exc

    if not await commit_boundary_dispatch_if_current(
        session,
        snapshot=snapshot,
        prepared=prepared,
        resume_event=resume_event,
    ):
        raise _boundary_continue_conflict("another controller transition won during continue")
    publish_dispatch_start_due(dependencies, prepared)
    return BoundaryOpeningResult(outcome="opened", dispatch_id=prepared.dispatch_id)


async def _prepare_boundary_successor(
    session: AsyncSession,
    *,
    source_dispatch_id: str,
    dependencies: DispatchOpeningDependencies,
    due_at: datetime,
    expected_flow_status: Literal["running", "paused"],
    expected_active_flow_revision_id: str | None,
    expected_control_revision: int | None,
) -> tuple[_BoundaryOpeningSnapshot, PreparedDispatchRequest] | _TerminalBoundary | None:
    dispatch_id = f"dispatch.{uuid4().hex}"
    snapshot = await _read_boundary_opening_snapshot(
        session,
        source_dispatch_id=source_dispatch_id,
        dispatch_id=dispatch_id,
        dependencies=dependencies,
        expected_flow_status=expected_flow_status,
        expected_active_flow_revision_id=expected_active_flow_revision_id,
        expected_control_revision=expected_control_revision,
    )
    if snapshot is None or isinstance(snapshot, _TerminalBoundary):
        await session.rollback()
        return snapshot
    request = build_boundary_dispatch_request(snapshot.prompt)
    await session.rollback()
    prepared = prepare_dispatch_request(
        dependencies=dependencies,
        paths=snapshot.paths,
        dispatch_id=dispatch_id,
        due_at=due_at,
        provider=snapshot.provider,
        capabilities=snapshot.capabilities,
        request=request,
    )
    return snapshot, prepared


async def _read_boundary_opening_snapshot(
    session: AsyncSession,
    *,
    source_dispatch_id: str,
    dispatch_id: str,
    dependencies: DispatchOpeningDependencies,
    expected_flow_status: Literal["running", "paused"],
    expected_active_flow_revision_id: str | None,
    expected_control_revision: int | None,
) -> _BoundaryOpeningSnapshot | _TerminalBoundary | None:
    source_row = (
        await session.execute(
            select(AcceptedBoundaryModel, DispatchTurnModel, FlowModel)
            .options(raiseload("*"))
            .join(
                DispatchTurnModel,
                DispatchTurnModel.dispatch_id == AcceptedBoundaryModel.source_dispatch_id,
            )
            .join(FlowModel, FlowModel.flow_id == AcceptedBoundaryModel.flow_id)
            .where(AcceptedBoundaryModel.source_dispatch_id == source_dispatch_id)
        )
    ).one_or_none()
    if source_row is None:
        return None
    boundary, source_dispatch, flow = source_row
    if boundary.successor_dispatch_id is not None:
        return None
    if source_dispatch.status != "closed" or source_dispatch.closed_reason != "boundary":
        raise ValueError("accepted boundary source dispatch is not closed by its boundary")
    source_assignment = await session.scalar(
        select(AssignmentModel)
        .options(raiseload("*"))
        .where(
            AssignmentModel.assignment_id == boundary.assignment_id,
            AssignmentModel.task_id == boundary.task_id,
            AssignmentModel.flow_id == boundary.flow_id,
        )
    )
    if source_assignment is None:
        raise ValueError("accepted boundary is missing its source assignment")
    if source_assignment.parent_assignment_id is None and boundary.outcome in {
        "green",
        "blocked",
    }:
        if flow.status == "completed" and flow.terminal_outcome == boundary.outcome:
            return _TERMINAL_BOUNDARY
        raise ValueError("root terminal boundary did not complete its flow")
    if (
        flow.status != expected_flow_status
        or flow.active_flow_revision_id is None
        or (
            expected_active_flow_revision_id is not None
            and flow.active_flow_revision_id != expected_active_flow_revision_id
        )
        or (
            expected_control_revision is not None
            and flow.control_revision != expected_control_revision
        )
        or flow.current_dispatch_id is not None
        or flow.waiting_cause != "none"
        or (expected_flow_status == "paused" and flow.pause_reason is None)
    ):
        return None

    target = await resolve_boundary_target(
        session,
        boundary=boundary,
        source_assignment=source_assignment,
    )
    return await _read_target_snapshot(
        session,
        boundary=boundary,
        flow=flow,
        target=target,
        dispatch_id=dispatch_id,
        dependencies=dependencies,
        expected_flow_status=expected_flow_status,
    )


async def _read_target_snapshot(
    session: AsyncSession,
    *,
    boundary: AcceptedBoundaryModel,
    flow: FlowModel,
    target: BoundaryTarget,
    dispatch_id: str,
    dependencies: DispatchOpeningDependencies,
    expected_flow_status: Literal["running", "paused"],
) -> _BoundaryOpeningSnapshot:
    context = await _read_target_context(
        session,
        boundary=boundary,
        flow=flow,
        target=target,
    )
    node = context.node
    assignment = context.assignment
    require_consistent_target_runtime_context(
        node,
        context.node_plan,
        assignment,
        context.attempt,
    )
    assert flow.active_flow_revision_id is not None
    workflow = await _read_pinned_workflow(session, context.compiled_plan)
    children = await _read_target_children(session, flow=flow, node=node)
    work_plan = await read_assignment_work_plan(session, assignment_id=assignment.assignment_id)
    assignment_files = await read_assignment_file_references(
        session,
        assignment_id=assignment.assignment_id,
    )
    capabilities = await resolve_effective_capabilities_for_node(session, node=node)
    provider = await resolve_member_provider_route(
        session,
        task_id=node.task_id,
        member_configuration_id=node.member_configuration_id,
        settings=dependencies.settings,
        available_adapter_kinds=dependencies.available_adapter_kinds,
    )
    capabilities = narrow_provider_capabilities(
        route=provider.route,
        sandbox=provider.sandbox,
        capabilities=capabilities,
    )
    paths = await read_task_root_paths(session, context.task.task_id)
    description = workflow.content_json.get("description")
    if description is not None and not isinstance(description, str):
        raise ValueError("pinned workflow description must be text")
    prompt = _build_boundary_prompt(
        context,
        boundary=boundary,
        flow=flow,
        target=target,
        dispatch_id=dispatch_id,
        workflow_description=description,
        capabilities=capabilities,
        work_plan=work_plan,
        children=children,
        assignment_files=assignment_files,
    )
    return _BoundaryOpeningSnapshot(
        source_committed_at=boundary.committed_at,
        flow_control_revision=flow.control_revision,
        task_root_path=context.task.task_root_path,
        workspace_root_path=context.workspace.normalized_root_path,
        compiled_plan_id=context.compiled_plan.compiled_plan_id,
        node_plan_revision_id=context.node_plan.node_plan_revision_id,
        assignment_work_plan_revision=assignment.work_plan_revision,
        source_outcome=boundary.outcome,
        raw_provider_kind=node.provider_kind,
        opened_reason=target.opened_reason,
        prompt=prompt,
        provider=provider,
        capabilities=capabilities,
        paths=paths,
        expected_flow_status=expected_flow_status,
        expected_pause_reason=flow.pause_reason,
    )


async def _read_pinned_workflow(
    session: AsyncSession,
    compiled_plan: CompiledPlanModel,
) -> WorkflowRevisionModel:
    workflow = await session.scalar(
        select(WorkflowRevisionModel)
        .options(raiseload("*"))
        .where(
            WorkflowRevisionModel.workflow_key == compiled_plan.workflow_key,
            WorkflowRevisionModel.revision_no == compiled_plan.workflow_revision_no,
        )
    )
    if workflow is None:
        raise ValueError("boundary target is missing its pinned workflow revision")
    return workflow


async def _read_target_children(
    session: AsyncSession,
    *,
    flow: FlowModel,
    node: FlowNodeModel,
) -> tuple[FlowNodeModel, ...]:
    assert flow.active_flow_revision_id is not None
    return tuple(
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


async def _read_target_context(
    session: AsyncSession,
    *,
    boundary: AcceptedBoundaryModel,
    flow: FlowModel,
    target: BoundaryTarget,
) -> _TargetRuntimeContext:
    row = (
        await session.execute(
            select(
                TaskModel,
                WorkspaceBindingModel,
                CompiledPlanModel,
                FlowNodeModel,
                NodePlanRevisionModel,
                AssignmentModel,
                AttemptModel,
            )
            .options(raiseload("*"))
            .select_from(AssignmentModel)
            .join(TaskModel, TaskModel.task_id == AssignmentModel.task_id)
            .join(WorkspaceBindingModel, WorkspaceBindingModel.task_id == TaskModel.task_id)
            .join(CompiledPlanModel, CompiledPlanModel.compiled_plan_id == flow.compiled_plan_id)
            .join(
                FlowNodeModel,
                (FlowNodeModel.flow_id == AssignmentModel.flow_id)
                & (FlowNodeModel.flow_revision_id == flow.active_flow_revision_id)
                & (FlowNodeModel.member_id == AssignmentModel.member_id),
            )
            .join(
                NodePlanRevisionModel,
                (NodePlanRevisionModel.flow_id == FlowNodeModel.flow_id)
                & (NodePlanRevisionModel.flow_revision_id == FlowNodeModel.flow_revision_id)
                & (NodePlanRevisionModel.flow_node_id == FlowNodeModel.flow_node_id),
            )
            .join(
                AttemptModel,
                (AttemptModel.assignment_id == AssignmentModel.assignment_id)
                & (AttemptModel.attempt_id == target.attempt_id),
            )
            .where(
                AssignmentModel.assignment_id == target.assignment_id,
                AssignmentModel.task_id == boundary.task_id,
                AssignmentModel.flow_id == boundary.flow_id,
                TaskModel.current_team_revision_id == FlowNodeModel.team_revision_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise ValueError("boundary continuation is missing its exact target context")
    return _TargetRuntimeContext(*row)


def _build_boundary_prompt(
    context: _TargetRuntimeContext,
    *,
    boundary: AcceptedBoundaryModel,
    flow: FlowModel,
    target: BoundaryTarget,
    dispatch_id: str,
    workflow_description: str | None,
    capabilities: EffectiveCapabilitySet,
    work_plan: WorkPlanRead | None,
    children: tuple[FlowNodeModel, ...],
    assignment_files: tuple[FileReference, ...],
) -> BoundaryPromptSnapshot:
    task = context.task
    compiled_plan = context.compiled_plan
    node = context.node
    assignment = context.assignment
    attempt = context.attempt
    assert flow.active_flow_revision_id is not None
    return BoundaryPromptSnapshot(
        task_id=task.task_id,
        workflow_key=compiled_plan.workflow_key,
        workflow_revision_no=compiled_plan.workflow_revision_no,
        workflow_description=workflow_description,
        flow_id=flow.flow_id,
        flow_revision_id=flow.active_flow_revision_id,
        dispatch_id=dispatch_id,
        assignment_id=assignment.assignment_id,
        attempt_id=attempt.attempt_id,
        retry_of_attempt_id=attempt.retry_of_attempt_id,
        node_key=node.node_key,
        flow_node_id=node.flow_node_id,
        team_revision_id=node.team_revision_id,
        member_id=node.member_id,
        member_configuration_id=node.member_configuration_id,
        member_branch_basis_id=node.member_branch_basis_id,
        member_title=node.member_title,
        node_description=node.description,
        node_instruction=node.node_instruction,
        assignment_prompt=assignment.prompt,
        assignment_files=assignment_files,
        child_assignment_limit=assignment.child_assignment_limit,
        child_assignments_remaining=assignment.child_assignments_remaining,
        retry_limit=assignment.retry_limit,
        retries_remaining=assignment.retries_remaining,
        work_plan=work_plan,
        capabilities=capabilities,
        children=tuple(
            RootPromptChildSnapshot(
                node_key=child.node_key,
                node_kind=child.structural_kind,
                assignment_id=child.current_assignment_id,
            )
            for child in children
        ),
        node_kind=node.structural_kind,
        parent_assignment_id=assignment.parent_assignment_id,
        predecessor_dispatch_id=boundary.source_dispatch_id,
        trigger=target.trigger,
    )


def _boundary_continue_preparation_error(exc: Exception) -> RuntimeOperationError:
    code = str(getattr(exc, "code", "operator_continue_preparation_failed"))
    return RuntimeOperationError(
        code=OperationFailureCode.ILLEGAL_STATE,
        summary=f"operator continue preparation failed: {code}",
        is_retryable=False,
        suggested_next_step="Repair the exact source or provider route, then retry continue.",
    )


def _boundary_continue_conflict(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary=summary,
        is_retryable=False,
        suggested_next_step="Reread the flow and retry only from the same paused revision.",
        status_code_override=409,
    )


__all__ = [
    "BoundaryAcceptedHandler",
    "BoundaryOpeningOutcome",
    "BoundaryOpeningResult",
    "continue_paused_boundary",
    "create_boundary_accepted_handler",
    "open_boundary_successor",
]
