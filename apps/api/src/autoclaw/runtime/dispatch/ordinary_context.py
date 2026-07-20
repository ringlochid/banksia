from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload
from sqlalchemy.sql.elements import ColumnElement

from autoclaw.persistence.models import (
    AssignmentModel,
    AttemptModel,
    CommandRunModel,
    CompiledPlanModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
    FlowWaitModel,
    HumanRequestModel,
    NodePlanRevisionModel,
    TaskModel,
    WorkflowRevisionModel,
    WorkspaceBindingModel,
)
from autoclaw.persistence.models.runtime.common import COMMAND_RUN_TERMINAL_STATE_VALUES
from autoclaw.runtime.assignment import read_assignment_prompt_criteria
from autoclaw.runtime.capabilities import resolve_effective_capabilities_for_node
from autoclaw.runtime.contracts.capabilities import EffectiveCapabilitySet
from autoclaw.runtime.contracts.primitives import TaskRootPaths
from autoclaw.runtime.contracts.provider_resolution import ProviderResolution
from autoclaw.runtime.dispatch.preparation import DispatchOpeningDependencies
from autoclaw.runtime.dispatch.prompt_snapshot import (
    OrdinaryPromptSnapshot,
    OrdinaryPromptTrigger,
    RootPromptChildSnapshot,
)
from autoclaw.runtime.providers import (
    narrow_provider_capabilities,
    provider_selection_from_kind,
    resolve_provider_route,
)
from autoclaw.runtime.task_root import read_task_root_paths
from autoclaw.runtime.work_plan import WorkPlanRead, read_assignment_work_plan

type OrdinaryExpectedFlowStatus = Literal["running", "paused"]


@dataclass(frozen=True, slots=True)
class OrdinaryContinuationBasis:
    task_id: str
    flow_id: str
    assignment_id: str
    attempt_id: str
    source_dispatch_id: str
    source_dispatch_closed_reason: str
    opened_reason: str
    trigger: OrdinaryPromptTrigger


@dataclass(frozen=True, slots=True)
class OrdinaryDispatchSnapshot:
    basis: OrdinaryContinuationBasis
    expected_flow_status: OrdinaryExpectedFlowStatus
    expected_pause_reason: str | None
    flow_control_revision: int
    task_root_path: str
    workspace_root_path: str
    compiled_plan_id: str
    node_plan_revision_id: str
    assignment_work_plan_revision: int
    raw_provider_kind: str | None
    prompt: OrdinaryPromptSnapshot
    provider: ProviderResolution
    capabilities: EffectiveCapabilitySet
    paths: TaskRootPaths


@dataclass(frozen=True, slots=True)
class OrdinaryRuntimeContext:
    task: TaskModel
    workspace: WorkspaceBindingModel
    flow: FlowModel
    compiled_plan: CompiledPlanModel
    source_dispatch: DispatchTurnModel
    node: FlowNodeModel
    node_plan: NodePlanRevisionModel
    assignment: AssignmentModel
    attempt: AttemptModel


async def read_ordinary_dispatch_snapshot(
    session: AsyncSession,
    *,
    basis: OrdinaryContinuationBasis,
    dispatch_id: str,
    dependencies: DispatchOpeningDependencies,
    expected_flow_status: OrdinaryExpectedFlowStatus,
    expected_control_revision: int | None = None,
) -> OrdinaryDispatchSnapshot | None:
    """Read only the exact source target and prompt-safe linked controller truth."""

    context = await _read_ordinary_runtime_context(
        session,
        basis=basis,
        expected_flow_status=expected_flow_status,
        expected_control_revision=expected_control_revision,
    )
    if context is None or await _has_active_external_wait(session, flow_id=basis.flow_id):
        return None
    _validate_ordinary_runtime_context(context, basis=basis)

    workflow = await read_pinned_workflow_revision(session, context.compiled_plan)
    children = await read_current_child_nodes(session, context)
    work_plan = await read_assignment_work_plan(
        session,
        assignment_id=context.assignment.assignment_id,
    )
    prompt_criteria = await read_assignment_prompt_criteria(
        session,
        flow_revision_id=context.assignment.flow_revision_id,
        criteria_refs=context.assignment.criteria_json,
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
    workflow_description = workflow.content_json.get("description")
    if workflow_description is not None and not isinstance(workflow_description, str):
        raise ValueError("ordinary continuation workflow description must be text")
    prompt = build_ordinary_prompt_snapshot(
        context,
        basis=basis,
        dispatch_id=dispatch_id,
        workflow_description=workflow_description,
        capabilities=capabilities,
        work_plan=work_plan,
        children=children,
        criteria_json=prompt_criteria,
    )
    return OrdinaryDispatchSnapshot(
        basis=basis,
        expected_flow_status=expected_flow_status,
        expected_pause_reason=context.flow.pause_reason,
        flow_control_revision=context.flow.control_revision,
        task_root_path=context.task.task_root_path,
        workspace_root_path=context.workspace.normalized_root_path,
        compiled_plan_id=context.compiled_plan.compiled_plan_id,
        node_plan_revision_id=context.node_plan.node_plan_revision_id,
        assignment_work_plan_revision=context.assignment.work_plan_revision,
        raw_provider_kind=context.node.provider_kind,
        prompt=prompt,
        provider=provider,
        capabilities=capabilities,
        paths=paths,
    )


def ordinary_context_is_current(snapshot: OrdinaryDispatchSnapshot) -> ColumnElement[bool]:
    """Return final-transaction predicates for the exact prepared runtime context."""

    prompt = snapshot.prompt
    basis = snapshot.basis
    return (
        exists().where(
            DispatchTurnModel.dispatch_id == basis.source_dispatch_id,
            DispatchTurnModel.task_id == basis.task_id,
            DispatchTurnModel.flow_id == basis.flow_id,
            DispatchTurnModel.assignment_id == basis.assignment_id,
            DispatchTurnModel.attempt_id == basis.attempt_id,
            DispatchTurnModel.status == "closed",
            DispatchTurnModel.closed_reason == basis.source_dispatch_closed_reason,
        )
        & exists().where(
            FlowNodeModel.flow_id == prompt.flow_id,
            FlowNodeModel.flow_revision_id == prompt.flow_revision_id,
            FlowNodeModel.node_key == prompt.node_key,
            FlowNodeModel.structural_kind == prompt.node_kind,
            FlowNodeModel.state == "running",
            FlowNodeModel.current_assignment_id == prompt.assignment_id,
            FlowNodeModel.provider_kind == snapshot.raw_provider_kind,
        )
        & exists().where(
            NodePlanRevisionModel.node_plan_revision_id == snapshot.node_plan_revision_id,
            NodePlanRevisionModel.flow_id == prompt.flow_id,
            NodePlanRevisionModel.flow_revision_id == prompt.flow_revision_id,
            NodePlanRevisionModel.provider_kind == snapshot.raw_provider_kind,
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
        & ~exists().where(FlowWaitModel.flow_id == prompt.flow_id)
        & ~exists().where(
            HumanRequestModel.flow_id == prompt.flow_id,
            HumanRequestModel.status == "open",
        )
        & ~exists().where(
            CommandRunModel.flow_id == prompt.flow_id,
            CommandRunModel.state.not_in(COMMAND_RUN_TERMINAL_STATE_VALUES),
        )
    )


async def read_pinned_workflow_revision(
    session: AsyncSession,
    compiled_plan: CompiledPlanModel,
) -> WorkflowRevisionModel:
    workflow = await session.scalar(
        select(WorkflowRevisionModel)
        .options(raiseload("*"))
        .where(
            WorkflowRevisionModel.workflow_key == compiled_plan.workflow_key,
            WorkflowRevisionModel.revision_no == compiled_plan.definition_revision_no,
        )
    )
    if workflow is None:
        raise ValueError("ordinary continuation is missing its pinned workflow revision")
    return workflow


async def read_current_child_nodes(
    session: AsyncSession,
    context: OrdinaryRuntimeContext,
) -> tuple[FlowNodeModel, ...]:
    return tuple(
        await session.scalars(
            select(FlowNodeModel)
            .options(raiseload("*"))
            .where(
                FlowNodeModel.flow_id == context.flow.flow_id,
                FlowNodeModel.flow_revision_id == context.flow.active_flow_revision_id,
                FlowNodeModel.parent_node_key == context.node.node_key,
            )
            .order_by(FlowNodeModel.order_index)
        )
    )


def build_ordinary_prompt_snapshot(
    context: OrdinaryRuntimeContext,
    *,
    basis: OrdinaryContinuationBasis,
    dispatch_id: str,
    workflow_description: str | None,
    capabilities: EffectiveCapabilitySet,
    work_plan: WorkPlanRead | None,
    children: tuple[FlowNodeModel, ...],
    criteria_json: tuple[dict[str, object], ...],
) -> OrdinaryPromptSnapshot:
    task = context.task
    flow = context.flow
    compiled_plan = context.compiled_plan
    node = context.node
    node_plan = context.node_plan
    assignment = context.assignment
    attempt = context.attempt
    assert flow.active_flow_revision_id is not None
    return OrdinaryPromptSnapshot(
        task_id=task.task_id,
        task_title=task.title,
        task_summary=task.summary,
        task_instruction=task.instruction,
        workflow_key=compiled_plan.workflow_key,
        workflow_revision_no=compiled_plan.definition_revision_no,
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
        criteria_json=criteria_json,
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
        node_kind=node.structural_kind,
        parent_assignment_id=assignment.parent_assignment_id,
        predecessor_dispatch_id=basis.source_dispatch_id,
        trigger=basis.trigger,
    )


async def _read_ordinary_runtime_context(
    session: AsyncSession,
    *,
    basis: OrdinaryContinuationBasis,
    expected_flow_status: OrdinaryExpectedFlowStatus,
    expected_control_revision: int | None,
) -> OrdinaryRuntimeContext | None:
    statement = (
        select(
            TaskModel,
            WorkspaceBindingModel,
            FlowModel,
            CompiledPlanModel,
            DispatchTurnModel,
            FlowNodeModel,
            NodePlanRevisionModel,
            AssignmentModel,
            AttemptModel,
        )
        .options(raiseload("*"))
        .select_from(AssignmentModel)
        .join(TaskModel, TaskModel.task_id == AssignmentModel.task_id)
        .join(WorkspaceBindingModel, WorkspaceBindingModel.task_id == TaskModel.task_id)
        .join(FlowModel, FlowModel.flow_id == AssignmentModel.flow_id)
        .join(CompiledPlanModel, CompiledPlanModel.compiled_plan_id == FlowModel.compiled_plan_id)
        .join(DispatchTurnModel, DispatchTurnModel.dispatch_id == basis.source_dispatch_id)
        .join(
            FlowNodeModel,
            (FlowNodeModel.flow_id == AssignmentModel.flow_id)
            & (FlowNodeModel.flow_revision_id == AssignmentModel.flow_revision_id)
            & (FlowNodeModel.flow_node_id == AssignmentModel.flow_node_id),
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
            & (AttemptModel.attempt_id == basis.attempt_id),
        )
        .where(
            AssignmentModel.assignment_id == basis.assignment_id,
            AssignmentModel.task_id == basis.task_id,
            AssignmentModel.flow_id == basis.flow_id,
            FlowModel.status == expected_flow_status,
            FlowModel.active_flow_revision_id == AssignmentModel.flow_revision_id,
            FlowModel.current_dispatch_id.is_(None),
            FlowModel.waiting_cause == "none",
        )
    )
    if expected_control_revision is not None:
        statement = statement.where(FlowModel.control_revision == expected_control_revision)
    row = (await session.execute(statement)).one_or_none()
    return OrdinaryRuntimeContext(*row) if row is not None else None


def _validate_ordinary_runtime_context(
    context: OrdinaryRuntimeContext,
    *,
    basis: OrdinaryContinuationBasis,
) -> None:
    node = context.node
    node_plan = context.node_plan
    assignment = context.assignment
    attempt = context.attempt
    source_dispatch = context.source_dispatch
    if (
        source_dispatch.task_id != basis.task_id
        or source_dispatch.flow_id != basis.flow_id
        or source_dispatch.assignment_id != basis.assignment_id
        or source_dispatch.attempt_id != basis.attempt_id
        or source_dispatch.status != "closed"
        or source_dispatch.closed_reason != basis.source_dispatch_closed_reason
        or node.state != "running"
        or node.current_assignment_id != assignment.assignment_id
        or assignment.current_attempt_id != attempt.attempt_id
        or assignment.superseded_at is not None
        or attempt.status != "running"
        or node_plan.role_key != node.role_key
        or node_plan.role_revision_no != node.role_revision_no
        or node_plan.policy_key != node.policy_key
        or node_plan.policy_revision_no != node.policy_revision_no
        or node_plan.provider_kind != node.provider_kind
    ):
        raise ValueError("ordinary continuation has inconsistent exact runtime context")


async def _has_active_external_wait(session: AsyncSession, *, flow_id: str) -> bool:
    active_wait = await session.scalar(
        select(
            exists().where(FlowWaitModel.flow_id == flow_id)
            | exists().where(
                HumanRequestModel.flow_id == flow_id,
                HumanRequestModel.status == "open",
            )
            | exists().where(
                CommandRunModel.flow_id == flow_id,
                CommandRunModel.state.not_in(COMMAND_RUN_TERMINAL_STATE_VALUES),
            )
        )
    )
    return bool(active_wait)


__all__ = [
    "OrdinaryContinuationBasis",
    "OrdinaryDispatchSnapshot",
    "OrdinaryExpectedFlowStatus",
    "OrdinaryRuntimeContext",
    "build_ordinary_prompt_snapshot",
    "ordinary_context_is_current",
    "read_current_child_nodes",
    "read_ordinary_dispatch_snapshot",
    "read_pinned_workflow_revision",
]
