from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from banksia.persistence.models import (
    AssignmentModel,
    AttemptModel,
    CommandRunModel,
    CompiledPlanModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
    HumanRequestModel,
    NodePlanRevisionModel,
    TaskModel,
    WorkspaceBindingModel,
)
from banksia.runtime.assignment import read_assignment_prompt_criteria
from banksia.runtime.capabilities import resolve_effective_capabilities_for_node
from banksia.runtime.contracts.prompt import WatchdogRecoveryTrigger
from banksia.runtime.dispatch.ordinary_context import (
    OrdinaryContinuationBasis,
    OrdinaryDispatchSnapshot,
    OrdinaryRuntimeContext,
    build_ordinary_prompt_snapshot,
    read_current_child_nodes,
    read_pinned_workflow_revision,
)
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.post_commit import WatchdogDue
from banksia.runtime.providers import (
    narrow_provider_capabilities,
    resolve_member_provider_route,
)
from banksia.runtime.task_root import read_task_root_paths
from banksia.runtime.watchdog.deadline import calculate_watchdog_due_at
from banksia.runtime.work_plan import read_assignment_work_plan


@dataclass(frozen=True, slots=True)
class WatchdogRecoverySnapshot:
    dispatch: OrdinaryDispatchSnapshot
    adapter_started_at: datetime
    last_node_activity_at: datetime | None
    activity_revision: int
    authoritative_due_at: datetime
    same_attempt_replacement_count: int


@dataclass(frozen=True, slots=True)
class _WatchdogRecoveryCandidate:
    context: OrdinaryRuntimeContext
    authoritative_due_at: datetime


async def read_watchdog_recovery_snapshot(
    session: AsyncSession,
    *,
    signal: WatchdogDue,
    candidate_dispatch_id: str,
    dependencies: DispatchOpeningDependencies,
    now: datetime,
    inactivity_timeout_seconds: int,
) -> WatchdogRecoverySnapshot | None:
    """Read the exact stale dispatch and only the rows needed to render its D2."""

    candidate = await _read_watchdog_recovery_candidate(
        session,
        signal=signal,
        now=now,
        inactivity_timeout_seconds=inactivity_timeout_seconds,
    )
    if candidate is None:
        return None
    context = candidate.context
    source = context.source_dispatch
    assert source.adapter_started_at is not None
    if await dispatch_owns_external_source(session, dispatch_id=source.dispatch_id):
        return None

    replacement_count = await _read_same_attempt_replacement_count(
        session,
        source_dispatch=source,
    )
    dispatch = await _build_watchdog_replacement_dispatch(
        session,
        context=context,
        candidate_dispatch_id=candidate_dispatch_id,
        replacement_count=replacement_count,
        dependencies=dependencies,
    )
    return WatchdogRecoverySnapshot(
        dispatch=dispatch,
        adapter_started_at=source.adapter_started_at,
        last_node_activity_at=source.last_node_activity_at,
        activity_revision=source.node_activity_revision,
        authoritative_due_at=candidate.authoritative_due_at,
        same_attempt_replacement_count=replacement_count,
    )


async def dispatch_owns_external_source(
    session: AsyncSession,
    *,
    dispatch_id: str,
) -> bool:
    """Return whether any human or command source remains bound to a dispatch."""

    owned_source = await session.scalar(
        select(
            exists().where(HumanRequestModel.source_dispatch_id == dispatch_id)
            | exists().where(CommandRunModel.source_dispatch_id == dispatch_id)
        )
    )
    return bool(owned_source)


async def _read_watchdog_recovery_candidate(
    session: AsyncSession,
    *,
    signal: WatchdogDue,
    now: datetime,
    inactivity_timeout_seconds: int,
) -> _WatchdogRecoveryCandidate | None:
    context = await _read_watchdog_runtime_context(session, signal.dispatch_id)
    if context is None or not _context_is_plausible(context, signal=signal):
        return None
    source = context.source_dispatch
    assert source.adapter_started_at is not None
    due_at = calculate_watchdog_due_at(
        adapter_started_at=source.adapter_started_at,
        last_node_activity_at=source.last_node_activity_at,
        inactivity_timeout_seconds=inactivity_timeout_seconds,
    )
    if due_at != _as_utc(signal.due_at) or _as_utc(now) < due_at:
        return None
    return _WatchdogRecoveryCandidate(
        context=context,
        authoritative_due_at=due_at,
    )


async def _read_same_attempt_replacement_count(
    session: AsyncSession,
    *,
    source_dispatch: DispatchTurnModel,
) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(DispatchTurnModel)
        .where(
            DispatchTurnModel.flow_id == source_dispatch.flow_id,
            DispatchTurnModel.assignment_id == source_dispatch.assignment_id,
            DispatchTurnModel.attempt_id == source_dispatch.attempt_id,
            DispatchTurnModel.opened_reason == "watchdog_recovery",
        )
    )
    return int(count or 0)


async def _build_watchdog_replacement_dispatch(
    session: AsyncSession,
    *,
    context: OrdinaryRuntimeContext,
    candidate_dispatch_id: str,
    replacement_count: int,
    dependencies: DispatchOpeningDependencies,
) -> OrdinaryDispatchSnapshot:
    source = context.source_dispatch
    workflow = await read_pinned_workflow_revision(session, context.compiled_plan)
    children = await read_current_child_nodes(session, context)
    work_plan = await read_assignment_work_plan(
        session,
        assignment_id=context.assignment.assignment_id,
    )
    prompt_criteria = await read_assignment_prompt_criteria(
        session,
        flow_revision_id=context.node.flow_revision_id,
        criteria_refs=context.assignment.criteria_json,
    )
    capabilities = await resolve_effective_capabilities_for_node(session, node=context.node)
    provider = await resolve_member_provider_route(
        session,
        task_id=context.node.task_id,
        member_configuration_id=context.node.member_configuration_id,
        settings=dependencies.settings,
        available_adapter_kinds=dependencies.available_adapter_kinds,
    )
    capabilities = narrow_provider_capabilities(
        route=provider.route,
        sandbox=provider.sandbox,
        capabilities=capabilities,
    )
    paths = await read_task_root_paths(session, context.task.task_id)
    workflow_description = workflow.content_json.get("description")
    if workflow_description is not None and not isinstance(workflow_description, str):
        raise ValueError("watchdog continuation workflow description must be text")
    basis = OrdinaryContinuationBasis(
        task_id=source.task_id,
        flow_id=source.flow_id,
        assignment_id=source.assignment_id,
        attempt_id=source.attempt_id,
        source_dispatch_id=source.dispatch_id,
        source_dispatch_closed_reason="watchdog_superseded",
        opened_reason="watchdog_recovery",
        trigger=WatchdogRecoveryTrigger(
            source_dispatch_id=source.dispatch_id,
            recovery_count=replacement_count + 1,
        ),
    )
    prompt = build_ordinary_prompt_snapshot(
        context,
        basis=basis,
        dispatch_id=candidate_dispatch_id,
        workflow_description=workflow_description,
        capabilities=capabilities,
        work_plan=work_plan,
        children=children,
        criteria_json=prompt_criteria,
    )
    dispatch = OrdinaryDispatchSnapshot(
        basis=basis,
        expected_flow_status="running",
        expected_pause_reason=None,
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
    return dispatch


async def _read_watchdog_runtime_context(
    session: AsyncSession,
    dispatch_id: str,
) -> OrdinaryRuntimeContext | None:
    row = (
        await session.execute(
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
            .select_from(DispatchTurnModel)
            .join(TaskModel, TaskModel.task_id == DispatchTurnModel.task_id)
            .join(WorkspaceBindingModel, WorkspaceBindingModel.task_id == TaskModel.task_id)
            .join(FlowModel, FlowModel.flow_id == DispatchTurnModel.flow_id)
            .join(
                CompiledPlanModel,
                CompiledPlanModel.compiled_plan_id == FlowModel.compiled_plan_id,
            )
            .join(
                AssignmentModel,
                (AssignmentModel.assignment_id == DispatchTurnModel.assignment_id)
                & (AssignmentModel.task_id == DispatchTurnModel.task_id)
                & (AssignmentModel.flow_id == DispatchTurnModel.flow_id),
            )
            .join(
                FlowNodeModel,
                (FlowNodeModel.flow_id == DispatchTurnModel.flow_id)
                & (FlowNodeModel.flow_revision_id == DispatchTurnModel.flow_revision_id)
                & (FlowNodeModel.flow_node_id == DispatchTurnModel.flow_node_id),
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
                & (AttemptModel.attempt_id == DispatchTurnModel.attempt_id),
            )
            .where(
                DispatchTurnModel.dispatch_id == dispatch_id,
                TaskModel.current_team_revision_id == FlowNodeModel.team_revision_id,
            )
        )
    ).one_or_none()
    return OrdinaryRuntimeContext(*row) if row is not None else None


def _context_is_plausible(
    context: OrdinaryRuntimeContext,
    *,
    signal: WatchdogDue,
) -> bool:
    source = context.source_dispatch
    flow = context.flow
    assignment = context.assignment
    attempt = context.attempt
    node = context.node
    node_plan = context.node_plan
    return (
        source.status == "open"
        and source.adapter_started_at is not None
        and source.node_activity_revision == signal.activity_revision
        and flow.status == "running"
        and flow.current_dispatch_id == source.dispatch_id
        and flow.waiting_cause == "none"
        and flow.active_flow_revision_id == source.flow_revision_id
        and source.task_id == assignment.task_id
        and source.flow_id == assignment.flow_id
        and source.assignment_id == assignment.assignment_id
        and source.attempt_id == attempt.attempt_id
        and source.node_key == assignment.node_key
        and node.state == "running"
        and node.current_assignment_id == assignment.assignment_id
        and assignment.current_attempt_id == attempt.attempt_id
        and assignment.superseded_at is None
        and attempt.status == "running"
        and node_plan.task_id == node.task_id
        and node_plan.team_revision_id == node.team_revision_id
        and node_plan.member_id == node.member_id
        and node_plan.member_configuration_id == node.member_configuration_id
        and node_plan.member_branch_basis_id == node.member_branch_basis_id
        and assignment.member_id == node.member_id
        and assignment.node_key == node.node_key
        and source.team_revision_id == node.team_revision_id
        and source.member_configuration_id == node.member_configuration_id
        and source.member_branch_basis_id == node.member_branch_basis_id
        and node_plan.provider_kind == node.provider_kind
        and context.task.current_team_revision_id == node.team_revision_id
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "WatchdogRecoverySnapshot",
    "dispatch_owns_external_source",
    "read_watchdog_recovery_snapshot",
]
