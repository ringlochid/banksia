from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import AssignmentModel, ReplanTransitionModel, TaskModel
from banksia.runtime.capabilities import resolve_effective_capabilities_from_member_request
from banksia.runtime.clock import utc_now
from banksia.runtime.contracts import (
    ReplanOperation,
    ReplanSuccess,
    TaskEventSource,
    TaskEventType,
)
from banksia.runtime.contracts.capabilities import EffectiveCapabilitySet
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.contracts.provider_resolution import ProviderResolution
from banksia.runtime.contracts.team_read import (
    DirectTeamMemberRead,
    MemberAvailability,
    MemberBehavior,
    MemberParticipation,
)
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.node_operations.source_transitions import close_source_dispatch
from banksia.runtime.providers import (
    ProviderResolutionError,
    narrow_provider_capabilities,
    provider_selection_from_mapping,
    resolve_provider_route,
    validate_provider_execution_configuration,
)
from banksia.runtime.replan.context import (
    ReplanCommitContext,
    read_replan_context,
    require_replan_admission,
)
from banksia.runtime.replan.planning import (
    PlannedMember,
    ReplanMutation,
    ReplanRequest,
    build_replan_mutation,
)
from banksia.runtime.replan.staging import stage_replan_successor_rows
from banksia.runtime.task_events import append_task_event
from banksia.runtime.team.participation import read_accepted_green_participation
from banksia.runtime.team.reads import (
    available_member_actions,
    effective_capabilities_read,
    resolved_provider_read,
)


@dataclass(frozen=True, slots=True)
class ReplanCommit:
    """Committed public result and durable transition identity."""

    result: ReplanSuccess
    transition_id: str


@dataclass(frozen=True, slots=True)
class _ResolvedMemberExecution:
    provider: ProviderResolution
    capabilities: EffectiveCapabilitySet


async def commit_replan_rows(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    operation: ReplanOperation,
    request: ReplanRequest,
    *,
    dependencies: DispatchOpeningDependencies,
) -> ReplanCommit:
    """Commit one complete immutable Team successor behind the Task CAS."""

    context = await read_replan_context(session, authority)
    mutation = build_replan_mutation(
        loaded=context.members,
        root_member_id=context.team_revision.root_member_id,
        caller_member_id=authority.assignment.member_id,
        request=request,
    )
    await require_replan_admission(session, authority, mutation)
    result = await _build_result(
        session,
        mutation,
        authority.assignment.member_id,
        operation,
        task_id=authority.task_id,
        dependencies=dependencies,
    )
    successor_team_id = f"team-revision.{uuid4().hex}"
    transition_id = f"replan-transition.{uuid4().hex}"
    await _claim_replan_heads(
        session,
        authority,
        context,
        successor_team_id=successor_team_id,
    )
    stage_replan_successor_rows(
        session,
        authority,
        context,
        mutation,
        successor_team_id=successor_team_id,
    )
    await session.flush()
    await _stage_transition_and_event(
        session,
        authority,
        context,
        request=request,
        result=result,
        operation=operation,
        transition_id=transition_id,
        successor_team_id=successor_team_id,
    )
    await session.commit()
    return ReplanCommit(result=result, transition_id=transition_id)


async def _claim_replan_heads(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    context: ReplanCommitContext,
    *,
    successor_team_id: str,
) -> None:
    transitioned_at = utc_now()
    await close_source_dispatch(
        session,
        authority,
        now=transitioned_at,
        closed_reason="structural_replan",
    )
    task_id = await session.scalar(
        update(TaskModel)
        .where(
            TaskModel.task_id == authority.task_id,
            TaskModel.status == "running",
            TaskModel.control_revision == authority.task_control_revision,
            TaskModel.current_team_revision_id == context.team_revision.team_revision_id,
        )
        .values(
            current_team_revision_id=successor_team_id,
            updated_at=transitioned_at,
        )
        .returning(TaskModel.task_id)
    )
    if task_id is None:
        raise _conflict("another replan or Task transition won the current Team pointer")


async def _stage_transition_and_event(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    context: ReplanCommitContext,
    *,
    request: ReplanRequest,
    result: ReplanSuccess,
    operation: ReplanOperation,
    transition_id: str,
    successor_team_id: str,
) -> None:
    session.add(
        ReplanTransitionModel(
            replan_transition_id=transition_id,
            task_id=authority.task_id,
            assignment_id=authority.assignment_id,
            attempt_id=authority.attempt_id,
            source_dispatch_id=authority.dispatch_id,
            operation=operation,
            normalized_request_json=request.model_dump(mode="json", exclude_unset=True),
            committed_result_json=result.model_dump(mode="json", exclude_none=True),
            source_team_revision_id=context.team_revision.team_revision_id,
            successor_team_revision_id=successor_team_id,
            manifest_state="pending",
            successor_state="blocked",
        )
    )
    target_id = (
        result.created_ids[0]
        if result.created_ids
        else (result.updated_ids[0] if result.updated_ids else result.removed_ids[0])
    )
    await append_task_event(
        session,
        task_id=authority.task_id,
        event_type=TaskEventType.STRUCTURAL_REVISION_ADOPTED,
        event_source=TaskEventSource.NODE,
        team_revision_id=successor_team_id,
        dispatch_id=authority.dispatch_id,
        attempt_id=authority.attempt_id,
        member_id=authority.member_id,
        payload={
            "source_team_revision_id": context.team_revision.team_revision_id,
            "adopted_team_revision_id": successor_team_id,
            "operation": operation,
            "target_member_id": target_id,
            "cause": f"{operation} accepted from the exact current Dispatch.",
            "adopted_by_dispatch_id": authority.dispatch_id,
        },
    )


async def _build_result(
    session: AsyncSession,
    mutation: ReplanMutation,
    caller_member_id: str,
    operation: ReplanOperation,
    *,
    task_id: str,
    dependencies: DispatchOpeningDependencies,
) -> ReplanSuccess:
    resolved: dict[str, _ResolvedMemberExecution] = {}
    for member in mutation.members.values():
        if member.has_configuration_change:
            resolved[member.member_id] = _resolve_member_execution(
                member,
                dependencies=dependencies,
            )

    caller = mutation.members[caller_member_id]
    caller_execution = _cached_member_execution(
        caller,
        resolved=resolved,
        dependencies=dependencies,
    )
    direct_team_members: list[DirectTeamMemberRead] = []
    for child_id in caller.children:
        child = mutation.members[child_id]
        direct_team_members.append(
            await _direct_team_member_read(
                session,
                child,
                task_id=task_id,
                execution=_cached_member_execution(
                    child,
                    resolved=resolved,
                    dependencies=dependencies,
                ),
            )
        )
    direct_team = tuple(direct_team_members)
    effective_capabilities = effective_capabilities_read(caller_execution.capabilities)
    return ReplanSuccess(
        operation=operation,
        created_ids=mutation.created_ids,
        updated_ids=mutation.updated_ids,
        removed_ids=mutation.removed_ids,
        direct_team=direct_team,
        behavior=(MemberBehavior.MANAGER if direct_team else MemberBehavior.CONTRIBUTOR),
        effective_capabilities=effective_capabilities,
        available_actions=available_member_actions(
            direct_team=direct_team,
            capabilities=effective_capabilities,
            is_task_lead=caller.parent_member_id is None,
        ),
        must_stop=True,
    )


async def _direct_team_member_read(
    session: AsyncSession,
    member: PlannedMember,
    *,
    task_id: str,
    execution: _ResolvedMemberExecution,
) -> DirectTeamMemberRead:
    participation_is_current = await read_accepted_green_participation(
        session,
        task_id=task_id,
        member_id=member.member_id,
        member_configuration_id=member.configuration_id,
        member_branch_basis_id=member.branch_basis_id,
    )
    is_busy = bool(
        await session.scalar(
            select(
                exists().where(
                    AssignmentModel.task_id == task_id,
                    AssignmentModel.member_id == member.member_id,
                    AssignmentModel.terminal_outcome.is_(None),
                    AssignmentModel.superseded_at.is_(None),
                )
            )
        )
    )
    return DirectTeamMemberRead(
        id=member.member_id,
        title=member.title,
        description=member.description,
        instruction=member.instruction,
        provider=resolved_provider_read(execution.provider),
        capabilities=effective_capabilities_read(execution.capabilities),
        participation=(
            MemberParticipation.SATISFIED
            if participation_is_current
            else MemberParticipation.REQUIRED
        ),
        availability=(MemberAvailability.BUSY if is_busy else MemberAvailability.AVAILABLE),
    )


def _resolve_member_execution(
    member: PlannedMember,
    *,
    dependencies: DispatchOpeningDependencies,
) -> _ResolvedMemberExecution:
    try:
        provider = resolve_provider_route(
            provider=provider_selection_from_mapping(member.provider_json),
            settings=dependencies.settings,
            available_adapter_kinds=dependencies.available_adapter_kinds,
        )
        capabilities = resolve_effective_capabilities_from_member_request(member.capabilities_json)
        capabilities = narrow_provider_capabilities(
            route=provider.route,
            sandbox=provider.sandbox,
            capabilities=capabilities,
        )
        validate_provider_execution_configuration(
            route=provider.route,
            provider_native_access=capabilities.provider_native_access.effective,
            network_access=capabilities.network_access.effective,
            sandbox_mode=(
                provider.sandbox.effective_mode if provider.sandbox is not None else None
            ),
        )
    except ProviderResolutionError as exc:
        raise RuntimeOperationError(
            code=OperationFailureCode.ILLEGAL_STATE,
            summary=f"Replan Member {member.member_id!r} cannot execute: {exc}",
            is_retryable=False,
            suggested_next_step=(
                "Configure an enabled available provider or update this Member provider "
                "selection, then retry the replan."
            ),
            status_code_override=422,
        ) from exc
    return _ResolvedMemberExecution(
        provider=provider,
        capabilities=capabilities,
    )


def _cached_member_execution(
    member: PlannedMember,
    *,
    resolved: dict[str, _ResolvedMemberExecution],
    dependencies: DispatchOpeningDependencies,
) -> _ResolvedMemberExecution:
    execution = resolved.get(member.member_id)
    if execution is None:
        execution = _resolve_member_execution(member, dependencies=dependencies)
        resolved[member.member_id] = execution
    return execution


def _conflict(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary=summary,
        is_retryable=False,
    )


__all__ = ["ReplanCommit", "commit_replan_rows"]
