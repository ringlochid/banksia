from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload
from sqlalchemy.sql.elements import ColumnElement

from autoclaw.definitions.contracts.workflow import NodeKind
from autoclaw.persistence.models import (
    AssignmentModel,
    AttemptModel,
    CompiledPlanModel,
    FlowModel,
    FlowNodeModel,
    FlowStartSourceModel,
    NodePlanRevisionModel,
    TaskModel,
    WorkflowRevisionModel,
    WorkspaceBindingModel,
)
from autoclaw.runtime.capabilities import resolve_effective_capabilities_for_node
from autoclaw.runtime.contracts.capabilities import EffectiveCapabilitySet
from autoclaw.runtime.contracts.primitives import TaskRootPaths
from autoclaw.runtime.contracts.prompt import OperatorContinueTrigger, RootStartTrigger
from autoclaw.runtime.contracts.provider_resolution import ProviderResolution
from autoclaw.runtime.dispatch.preparation import DispatchOpeningDependencies
from autoclaw.runtime.dispatch.prompt_snapshot import (
    RootPromptChildSnapshot,
    RootPromptSnapshot,
    RootPromptTrigger,
)
from autoclaw.runtime.providers import (
    narrow_provider_capabilities,
    provider_selection_from_kind,
    resolve_provider_route,
)
from autoclaw.runtime.task_root import read_task_root_paths
from autoclaw.runtime.work_plan import WorkPlanRead, read_assignment_work_plan

type RootSourceFlowStatus = Literal["running", "paused"]


@dataclass(frozen=True, slots=True)
class RootOpeningSnapshot:
    source_committed_at: datetime
    flow_control_revision: int
    task_root_path: str
    workspace_root_path: str
    compiled_plan_id: str
    node_plan_revision_id: str
    assignment_work_plan_revision: int
    prompt: RootPromptSnapshot
    provider: ProviderResolution
    capabilities: EffectiveCapabilitySet
    paths: TaskRootPaths
    expected_flow_status: RootSourceFlowStatus
    expected_pause_reason: str | None
    opened_reason: Literal["root", "operator_continue"]
    trigger: RootPromptTrigger


@dataclass(frozen=True, slots=True)
class _FlowStartState:
    source: FlowStartSourceModel
    flow: FlowModel


@dataclass(frozen=True, slots=True)
class _RootRuntimeContext:
    task: TaskModel
    workspace: WorkspaceBindingModel
    compiled_plan: CompiledPlanModel
    workflow: WorkflowRevisionModel
    node: FlowNodeModel
    node_plan: NodePlanRevisionModel
    assignment: AssignmentModel
    attempt: AttemptModel


async def read_root_opening_snapshot(
    session: AsyncSession,
    *,
    flow_id: str,
    dispatch_id: str,
    dependencies: DispatchOpeningDependencies,
    expected_flow_status: RootSourceFlowStatus,
    expected_active_flow_revision_id: str | None,
    expected_control_revision: int | None,
) -> RootOpeningSnapshot | None:
    """Read one exact unconsumed flow-start source and its pinned root truth."""

    state = await _read_flow_start_state(
        session,
        flow_id=flow_id,
        expected_flow_status=expected_flow_status,
        expected_active_flow_revision_id=expected_active_flow_revision_id,
        expected_control_revision=expected_control_revision,
    )
    if state is None:
        return None
    context = await _read_root_runtime_context(session, state.flow)
    children = tuple(
        await session.scalars(
            select(FlowNodeModel)
            .options(raiseload("*"))
            .where(
                FlowNodeModel.flow_id == state.flow.flow_id,
                FlowNodeModel.flow_revision_id == state.flow.active_flow_revision_id,
                FlowNodeModel.parent_node_key == context.node.node_key,
            )
            .order_by(FlowNodeModel.order_index)
        )
    )
    work_plan = await read_assignment_work_plan(
        session,
        assignment_id=context.assignment.assignment_id,
    )
    capabilities = await resolve_effective_capabilities_for_node(session, node=context.node)
    provider = resolve_provider_route(
        provider=provider_selection_from_kind(context.node.provider_kind),
        settings=dependencies.settings,
        available_adapter_kinds=dependencies.available_adapter_kinds,
    )
    capabilities = narrow_provider_capabilities(
        route=provider.route,
        capabilities=capabilities,
    )
    paths = await read_task_root_paths(session, context.task.task_id)
    trigger, opened_reason = _root_trigger(state.flow, expected_flow_status)
    prompt = _build_root_prompt_snapshot(
        state.flow,
        context,
        dispatch_id=dispatch_id,
        work_plan=work_plan,
        capabilities=capabilities,
        children=children,
    )
    return RootOpeningSnapshot(
        source_committed_at=state.source.committed_at,
        flow_control_revision=state.flow.control_revision,
        task_root_path=context.task.task_root_path,
        workspace_root_path=context.workspace.normalized_root_path,
        compiled_plan_id=context.compiled_plan.compiled_plan_id,
        node_plan_revision_id=context.node_plan.node_plan_revision_id,
        assignment_work_plan_revision=context.assignment.work_plan_revision,
        prompt=prompt,
        provider=provider,
        capabilities=capabilities,
        paths=paths,
        expected_flow_status=expected_flow_status,
        expected_pause_reason=state.flow.pause_reason,
        opened_reason=opened_reason,
        trigger=trigger,
    )


def root_context_is_current(snapshot: RootOpeningSnapshot) -> ColumnElement[bool]:
    """Return final-transaction predicates for the prepared root context."""

    prompt = snapshot.prompt
    persisted_provider_kind = (
        snapshot.provider.requested_provider.value
        if snapshot.provider.selection_basis.value == "explicit"
        else None
    )
    return (
        exists().where(
            FlowNodeModel.flow_id == prompt.flow_id,
            FlowNodeModel.flow_revision_id == prompt.flow_revision_id,
            FlowNodeModel.node_key == prompt.node_key,
            FlowNodeModel.structural_kind == NodeKind.ROOT.value,
            FlowNodeModel.parent_node_key.is_(None),
            FlowNodeModel.state == "running",
            FlowNodeModel.current_assignment_id == prompt.assignment_id,
            FlowNodeModel.role_key == prompt.role_key,
            FlowNodeModel.provider_kind == persisted_provider_kind,
        )
        & exists().where(
            NodePlanRevisionModel.node_plan_revision_id == snapshot.node_plan_revision_id,
            NodePlanRevisionModel.flow_id == prompt.flow_id,
            NodePlanRevisionModel.flow_revision_id == prompt.flow_revision_id,
            NodePlanRevisionModel.provider_kind == persisted_provider_kind,
        )
        & exists().where(
            AssignmentModel.assignment_id == prompt.assignment_id,
            AssignmentModel.task_id == prompt.task_id,
            AssignmentModel.flow_id == prompt.flow_id,
            AssignmentModel.flow_revision_id == prompt.flow_revision_id,
            AssignmentModel.node_key == prompt.node_key,
            AssignmentModel.current_attempt_id == prompt.attempt_id,
            AssignmentModel.work_plan_revision == snapshot.assignment_work_plan_revision,
            AssignmentModel.superseded_at.is_(None),
        )
        & exists().where(
            AttemptModel.attempt_id == prompt.attempt_id,
            AttemptModel.assignment_id == prompt.assignment_id,
            AttemptModel.task_id == prompt.task_id,
            AttemptModel.flow_id == prompt.flow_id,
            AttemptModel.node_key == prompt.node_key,
            AttemptModel.status == "running",
        )
        & exists().where(
            TaskModel.task_id == prompt.task_id,
            TaskModel.task_root_path == snapshot.task_root_path,
            TaskModel.title == prompt.task_title,
            TaskModel.summary == prompt.task_summary,
        )
        & exists().where(
            WorkspaceBindingModel.task_id == prompt.task_id,
            WorkspaceBindingModel.normalized_root_path == snapshot.workspace_root_path,
        )
    )


async def _read_flow_start_state(
    session: AsyncSession,
    *,
    flow_id: str,
    expected_flow_status: RootSourceFlowStatus,
    expected_active_flow_revision_id: str | None,
    expected_control_revision: int | None,
) -> _FlowStartState | None:
    row = (
        await session.execute(
            select(FlowStartSourceModel, FlowModel)
            .options(raiseload("*"))
            .join(FlowModel, FlowModel.flow_id == FlowStartSourceModel.flow_id)
            .where(FlowStartSourceModel.flow_id == flow_id)
        )
    ).one_or_none()
    if row is None:
        return None
    source, flow = row
    is_current = (
        source.successor_dispatch_id is None
        and flow.status == expected_flow_status
        and flow.active_flow_revision_id is not None
        and (
            expected_active_flow_revision_id is None
            or flow.active_flow_revision_id == expected_active_flow_revision_id
        )
        and (
            expected_control_revision is None or flow.control_revision == expected_control_revision
        )
        and flow.current_dispatch_id is None
        and flow.waiting_cause == "none"
        and (expected_flow_status != "paused" or flow.pause_reason is not None)
    )
    return _FlowStartState(source, flow) if is_current else None


async def _read_root_runtime_context(
    session: AsyncSession,
    flow: FlowModel,
) -> _RootRuntimeContext:
    row = (
        await session.execute(
            select(
                TaskModel,
                WorkspaceBindingModel,
                CompiledPlanModel,
                WorkflowRevisionModel,
                FlowNodeModel,
                NodePlanRevisionModel,
                AssignmentModel,
                AttemptModel,
            )
            .options(raiseload("*"))
            .select_from(TaskModel)
            .join(WorkspaceBindingModel, WorkspaceBindingModel.task_id == TaskModel.task_id)
            .join(CompiledPlanModel, CompiledPlanModel.compiled_plan_id == flow.compiled_plan_id)
            .join(
                WorkflowRevisionModel,
                (WorkflowRevisionModel.workflow_key == CompiledPlanModel.workflow_key)
                & (WorkflowRevisionModel.revision_no == CompiledPlanModel.definition_revision_no),
            )
            .join(
                FlowNodeModel,
                (FlowNodeModel.flow_id == flow.flow_id)
                & (FlowNodeModel.flow_revision_id == flow.active_flow_revision_id),
            )
            .join(
                NodePlanRevisionModel,
                (NodePlanRevisionModel.flow_id == FlowNodeModel.flow_id)
                & (NodePlanRevisionModel.flow_revision_id == FlowNodeModel.flow_revision_id)
                & (NodePlanRevisionModel.flow_node_id == FlowNodeModel.flow_node_id),
            )
            .join(
                AssignmentModel,
                AssignmentModel.assignment_id == FlowNodeModel.current_assignment_id,
            )
            .join(AttemptModel, AttemptModel.attempt_id == AssignmentModel.current_attempt_id)
            .where(
                TaskModel.task_id == flow.task_id,
                FlowNodeModel.structural_kind == NodeKind.ROOT.value,
                FlowNodeModel.parent_node_key.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise ValueError("runnable flow start is missing its root runtime context")
    context = _RootRuntimeContext(*row)
    node = context.node
    node_plan = context.node_plan
    assignment = context.assignment
    attempt = context.attempt
    if (
        node.state != "running"
        or assignment.superseded_at is not None
        or attempt.status != "running"
        or node_plan.role_key != node.role_key
        or node_plan.role_revision_no != node.role_revision_no
        or node_plan.policy_key != node.policy_key
        or node_plan.policy_revision_no != node.policy_revision_no
        or node_plan.provider_kind != node.provider_kind
    ):
        raise ValueError("runnable flow start has inconsistent pinned root context")
    return context


def _build_root_prompt_snapshot(
    flow: FlowModel,
    context: _RootRuntimeContext,
    *,
    dispatch_id: str,
    work_plan: WorkPlanRead | None,
    capabilities: EffectiveCapabilitySet,
    children: tuple[FlowNodeModel, ...],
) -> RootPromptSnapshot:
    workflow_description = context.workflow.content_json.get("description")
    if workflow_description is not None and not isinstance(workflow_description, str):
        raise ValueError("pinned workflow description must be text")
    task = context.task
    node = context.node
    node_plan = context.node_plan
    assignment = context.assignment
    attempt = context.attempt
    assert flow.active_flow_revision_id is not None
    return RootPromptSnapshot(
        task_id=task.task_id,
        task_title=task.title,
        task_summary=task.summary,
        task_instruction=task.instruction,
        workflow_key=context.compiled_plan.workflow_key,
        workflow_revision_no=context.compiled_plan.definition_revision_no,
        workflow_description=workflow_description,
        flow_id=flow.flow_id,
        flow_revision_id=flow.active_flow_revision_id,
        dispatch_id=dispatch_id,
        assignment_id=assignment.assignment_id,
        attempt_id=attempt.attempt_id,
        retry_of_attempt_id=attempt.retry_of_attempt_id,
        node_key=node.node_key,
        role_key=node.role_key,
        role_description=node_plan.role_description,
        role_instruction=node_plan.role_instruction,
        policy_description=node_plan.policy_description,
        policy_instruction=node_plan.policy_instruction,
        node_description=node.description,
        node_instruction=node.node_instruction,
        assignment_summary=assignment.summary,
        assignment_instruction=assignment.instruction,
        criteria_json=tuple(node.criteria_json),
        consumes_json=tuple(assignment.consumes_json),
        produces_json=tuple(assignment.produces_json),
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
    )


def _root_trigger(
    flow: FlowModel,
    expected_flow_status: RootSourceFlowStatus,
) -> tuple[RootPromptTrigger, Literal["root", "operator_continue"]]:
    if expected_flow_status == "running":
        return RootStartTrigger(flow_id=flow.flow_id), "root"
    if flow.pause_reason is None:
        raise ValueError("paused flow start is missing its pause reason")
    return (
        OperatorContinueTrigger(
            source_flow_id=flow.flow_id,
            control_revision=flow.control_revision,
            pause_reason=flow.pause_reason,
        ),
        "operator_continue",
    )


__all__ = [
    "RootOpeningSnapshot",
    "RootSourceFlowStatus",
    "read_root_opening_snapshot",
    "root_context_is_current",
]
