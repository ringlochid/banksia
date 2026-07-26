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
    DispatchTurnModel,
    HumanRequestModel,
    MemberConfigurationModel,
    TaskModel,
    TeamRevisionMemberModel,
    WorkspaceBindingModel,
)
from banksia.runtime.assignment import read_assignment_file_references
from banksia.runtime.capabilities import (
    resolve_effective_capabilities_for_member_configuration,
)
from banksia.runtime.contracts.prompt import (
    WatchdogRecoveryResult,
    WatchdogRecoverySource,
    WatchdogRecoveryTrigger,
)
from banksia.runtime.dispatch.ordinary_context import (
    OrdinaryContinuationBasis,
    OrdinaryDispatchSnapshot,
    OrdinaryRuntimeContext,
    build_ordinary_prompt_snapshot,
    read_current_child_members,
    read_pinned_workflow_revision,
)
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.post_commit import WatchdogDue
from banksia.runtime.providers import narrow_provider_capabilities, resolve_member_provider_route
from banksia.runtime.task_root import read_task_root_paths
from banksia.runtime.team.reads import read_direct_team_members
from banksia.runtime.watchdog.deadline import calculate_watchdog_due_at
from banksia.runtime.work_plan import read_assignment_work_plan


@dataclass(frozen=True, slots=True)
class WatchdogRecoverySnapshot:
    dispatch: OrdinaryDispatchSnapshot
    source_team_revision_id: str
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
    """Read the exact stale Dispatch and render its replacement request."""

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
        source_team_revision_id=source.team_revision_id,
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
    """Return whether any human or command source remains bound to a Dispatch."""

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
            DispatchTurnModel.task_id == source_dispatch.task_id,
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
    workflow = await read_pinned_workflow_revision(session, context.task)
    children = await read_current_child_members(session, context)
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
    workflow_note = _read_workflow_note(workflow.content_json)
    direct_team = await read_direct_team_members(
        session,
        children=children,
        dependencies=dependencies,
    )
    basis = OrdinaryContinuationBasis(
        task_id=source.task_id,
        assignment_id=source.assignment_id,
        attempt_id=source.attempt_id,
        source_dispatch_id=source.dispatch_id,
        source_dispatch_closed_reason="watchdog_superseded",
        opened_reason="watchdog_recovery",
        trigger=WatchdogRecoveryTrigger(
            source=WatchdogRecoverySource(source_dispatch_id=source.dispatch_id),
            result=WatchdogRecoveryResult(recovery_count=replacement_count + 1),
        ),
    )
    prompt = build_ordinary_prompt_snapshot(
        context,
        basis=basis,
        dispatch_id=candidate_dispatch_id,
        workflow_note=workflow_note,
        capabilities=capabilities,
        work_plan=work_plan,
        provider=provider,
        direct_team=direct_team,
        paths=paths,
        assignment_files=assignment_files,
    )
    return OrdinaryDispatchSnapshot(
        basis=basis,
        expected_task_status="running",
        expected_pause_reason=None,
        task_control_revision=context.task.control_revision,
        task_root_path=context.task.task_root_path,
        workspace_root_path=context.workspace.normalized_root_path,
        assignment_work_plan_revision=context.assignment.work_plan_revision,
        prompt=prompt,
        provider=provider,
        capabilities=capabilities,
        paths=paths,
    )


async def _read_watchdog_runtime_context(
    session: AsyncSession,
    dispatch_id: str,
) -> OrdinaryRuntimeContext | None:
    row = (
        await session.execute(
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
            .select_from(DispatchTurnModel)
            .join(TaskModel, TaskModel.task_id == DispatchTurnModel.task_id)
            .join(WorkspaceBindingModel, WorkspaceBindingModel.task_id == TaskModel.task_id)
            .join(
                TeamRevisionMemberModel,
                (TeamRevisionMemberModel.task_id == DispatchTurnModel.task_id)
                & (TeamRevisionMemberModel.team_revision_id == TaskModel.current_team_revision_id)
                & (TeamRevisionMemberModel.member_id == DispatchTurnModel.member_id)
                & (
                    TeamRevisionMemberModel.member_configuration_id
                    == DispatchTurnModel.member_configuration_id
                )
                & (
                    TeamRevisionMemberModel.member_branch_basis_id
                    == DispatchTurnModel.member_branch_basis_id
                ),
            )
            .join(
                MemberConfigurationModel,
                (MemberConfigurationModel.task_id == TeamRevisionMemberModel.task_id)
                & (MemberConfigurationModel.member_id == TeamRevisionMemberModel.member_id)
                & (
                    MemberConfigurationModel.member_configuration_id
                    == TeamRevisionMemberModel.member_configuration_id
                ),
            )
            .join(
                AssignmentModel,
                (AssignmentModel.assignment_id == DispatchTurnModel.assignment_id)
                & (AssignmentModel.task_id == DispatchTurnModel.task_id)
                & (AssignmentModel.member_id == DispatchTurnModel.member_id),
            )
            .join(
                AttemptModel,
                (AttemptModel.task_id == AssignmentModel.task_id)
                & (AttemptModel.assignment_id == AssignmentModel.assignment_id)
                & (AttemptModel.attempt_id == DispatchTurnModel.attempt_id),
            )
            .where(
                DispatchTurnModel.dispatch_id == dispatch_id,
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
    assignment = context.assignment
    attempt = context.attempt
    selection = context.selection
    return (
        source.status == "open"
        and source.adapter_started_at is not None
        and source.node_activity_revision == signal.activity_revision
        and context.task.status == "running"
        and source.task_id == assignment.task_id
        and source.assignment_id == assignment.assignment_id
        and source.attempt_id == attempt.attempt_id
        and assignment.current_attempt_id == attempt.attempt_id
        and assignment.terminal_outcome is None
        and attempt.status == "running"
        and attempt.current_dispatch_id == source.dispatch_id
        and attempt.current_wait_id is None
        and assignment.member_id == selection.member_id
        and source.member_id == selection.member_id
        and source.member_configuration_id == selection.member_configuration_id
        and source.member_branch_basis_id == selection.member_branch_basis_id
        and context.task.current_team_revision_id == selection.team_revision_id
    )


def _read_workflow_note(content: dict[str, object]) -> str | None:
    note = content.get("note")
    if note is not None and not isinstance(note, str):
        raise ValueError("watchdog continuation workflow note must be text")
    return note


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "WatchdogRecoverySnapshot",
    "dispatch_owns_external_source",
    "read_watchdog_recovery_snapshot",
]
