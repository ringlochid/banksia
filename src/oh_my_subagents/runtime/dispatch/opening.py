from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.persistence.models import (
    DispatchCapabilitySetModel,
    DispatchRequestModel,
    DispatchTurnModel,
)
from oh_my_subagents.runtime.contracts import TaskEventSource, TaskEventType
from oh_my_subagents.runtime.contracts.provider_resolution import (
    ClaudeProviderRoute,
    CodexProviderRoute,
)
from oh_my_subagents.runtime.dispatch.currentness import (
    AttemptDispatchConflictError,
    AttemptDispatchIdentity,
    select_starting_dispatch_for_attempt,
)
from oh_my_subagents.runtime.dispatch.preparation import PreparedDispatchRequest
from oh_my_subagents.runtime.task_events import append_task_event


@dataclass(frozen=True, slots=True)
class StartingDispatchBasis:
    task_id: str
    assignment_id: str
    team_revision_id: str
    member_id: str
    member_configuration_id: str
    member_branch_basis_id: str
    attempt_id: str
    opened_reason: str
    predecessor_dispatch_id: str | None
    task_start_source_task_id: str | None
    resume_event: TaskResumeEventBasis | None = None


@dataclass(frozen=True, slots=True)
class TaskResumeEventBasis:
    control_revision: int
    actor_ref: str | None
    event_source: TaskEventSource


async def stage_starting_dispatch(
    session: AsyncSession,
    *,
    basis: StartingDispatchBasis,
    prepared: PreparedDispatchRequest,
) -> None:
    identity = AttemptDispatchIdentity(
        task_id=basis.task_id,
        assignment_id=basis.assignment_id,
        attempt_id=basis.attempt_id,
        dispatch_id=prepared.dispatch_id,
    )
    if not await select_starting_dispatch_for_attempt(
        session,
        identity=identity,
        predecessor_dispatch_id=basis.predecessor_dispatch_id,
    ):
        raise AttemptDispatchConflictError(
            f"Attempt {basis.attempt_id!r} no longer accepts Dispatch {prepared.dispatch_id!r}"
        )
    session.add(_build_starting_dispatch_model(basis=basis, prepared=prepared))
    await _append_dispatch_opened_event(session, basis=basis, prepared=prepared)
    if basis.resume_event is not None:
        await _append_task_resumed_event(
            session,
            basis=basis,
            prepared=prepared,
            resume_event=basis.resume_event,
        )
    _add_dispatch_support_records(session, prepared=prepared)


def _build_starting_dispatch_model(
    *,
    basis: StartingDispatchBasis,
    prepared: PreparedDispatchRequest,
) -> DispatchTurnModel:
    model_override, effort_override = _provider_route_overrides(prepared)
    return DispatchTurnModel(
        dispatch_id=prepared.dispatch_id,
        task_id=basis.task_id,
        assignment_id=basis.assignment_id,
        team_revision_id=basis.team_revision_id,
        member_id=basis.member_id,
        member_configuration_id=basis.member_configuration_id,
        member_branch_basis_id=basis.member_branch_basis_id,
        attempt_id=basis.attempt_id,
        task_start_source_task_id=basis.task_start_source_task_id,
        predecessor_dispatch_id=basis.predecessor_dispatch_id,
        status="starting",
        opened_reason=basis.opened_reason,
        requested_provider=prepared.provider.requested_provider.value,
        resolved_provider=prepared.provider.resolved_provider.value,
        provider_selection_basis=prepared.provider.selection_basis.value,
        model_override=model_override,
        model_source=(
            prepared.provider.model_source.value if prepared.provider.model_source else None
        ),
        effort_override=effort_override,
        effort_source=(
            prepared.provider.effort_source.value if prepared.provider.effort_source else None
        ),
        requested_extension_mode=(
            prepared.provider.extensions.requested_mode.value
            if prepared.provider.extensions
            else None
        ),
        requested_extension_mode_source=(
            prepared.provider.extensions.requested_source.value
            if prepared.provider.extensions
            else None
        ),
        effective_extension_mode=(
            prepared.provider.extensions.effective_mode.value
            if prepared.provider.extensions
            else None
        ),
        effective_extension_mode_source=(
            prepared.provider.extensions.effective_source.value
            if prepared.provider.extensions
            else None
        ),
        extension_inventory_json=None,
        gateway_profile=None,
        gateway_profile_source=None,
        provider_start_revision=0,
        provider_start_attempt_count=0,
        next_provider_start_at=prepared.due_at,
        provider_start_retry_kind="initial",
        provider_start_last_error_code=None,
        created_at=prepared.due_at,
        adapter_started_at=None,
        last_node_activity_at=None,
        node_activity_revision=0,
        closed_at=None,
        closed_reason=None,
    )


def _provider_route_overrides(
    prepared: PreparedDispatchRequest,
) -> tuple[str | None, str | None]:
    route = prepared.provider.route
    assert isinstance(route, CodexProviderRoute | ClaudeProviderRoute)
    return route.model_override, route.effort_override


async def _append_dispatch_opened_event(
    session: AsyncSession,
    *,
    basis: StartingDispatchBasis,
    prepared: PreparedDispatchRequest,
) -> None:
    await append_task_event(
        session,
        task_id=basis.task_id,
        event_type=TaskEventType.DISPATCH_OPENED,
        event_source=TaskEventSource.CONTROLLER,
        occurred_at=prepared.due_at,
        dispatch_id=prepared.dispatch_id,
        attempt_id=basis.attempt_id,
        team_revision_id=basis.team_revision_id,
        member_id=basis.member_id,
        payload={
            "dispatch_id": prepared.dispatch_id,
            "predecessor_dispatch_id": basis.predecessor_dispatch_id,
            "assignment_id": basis.assignment_id,
            "attempt_id": basis.attempt_id,
            "member_id": basis.member_id,
            "status": "starting",
            "opened_reason": basis.opened_reason,
            "requested_provider": prepared.provider.requested_provider.value,
            "resolved_provider": prepared.provider.resolved_provider.value,
            "selection_basis": prepared.provider.selection_basis.value,
        },
    )


async def _append_task_resumed_event(
    session: AsyncSession,
    *,
    basis: StartingDispatchBasis,
    prepared: PreparedDispatchRequest,
    resume_event: TaskResumeEventBasis,
) -> None:
    await append_task_event(
        session,
        task_id=basis.task_id,
        event_type=TaskEventType.TASK_RESUMED,
        event_source=resume_event.event_source,
        occurred_at=prepared.due_at,
        dispatch_id=prepared.dispatch_id,
        attempt_id=basis.attempt_id,
        team_revision_id=basis.team_revision_id,
        member_id=basis.member_id,
        actor_ref=resume_event.actor_ref,
        payload={
            "control_revision": resume_event.control_revision,
            "actor_ref": resume_event.actor_ref,
            "summary": "Resumed by operator from the retained exact source.",
        },
    )


def _add_dispatch_support_records(
    session: AsyncSession,
    *,
    prepared: PreparedDispatchRequest,
) -> None:
    session.add(
        DispatchRequestModel(
            dispatch_id=prepared.dispatch_id,
            instructions=prepared.instructions,
            input=prepared.input,
            created_at=prepared.due_at,
        )
    )
    capabilities = prepared.capabilities
    sandbox = prepared.provider.sandbox
    session.add(
        DispatchCapabilitySetModel(
            dispatch_id=prepared.dispatch_id,
            provider_kind=prepared.provider.route.kind.value,
            provider_native_access=capabilities.provider_native_access.effective.value,
            provider_native_access_source=capabilities.provider_native_access.source.value,
            network_access=capabilities.network_access.effective.value,
            network_access_source=capabilities.network_access.source.value,
            requested_sandbox_mode=(sandbox.requested_mode.value if sandbox else None),
            requested_sandbox_network=(sandbox.requested_network.value if sandbox else None),
            sandbox_request_source=(sandbox.requested_source.value if sandbox else None),
            effective_sandbox_mode=(sandbox.effective_mode.value if sandbox else None),
            effective_sandbox_network=(sandbox.effective_network.value if sandbox else None),
            sandbox_mode_source=(sandbox.effective_mode_source.value if sandbox else None),
            sandbox_network_source=(sandbox.effective_network_source.value if sandbox else None),
            requested_human_direction=(capabilities.requested_human_request.direction.value),
            requested_human_approval=(capabilities.requested_human_request.approval.value),
            requested_human_input=capabilities.requested_human_request.input.value,
            requested_human_review=capabilities.requested_human_request.review.value,
            requested_human_request_source=(capabilities.requested_human_request_source.value),
            human_direction=capabilities.human_request.direction.value,
            human_direction_source=capabilities.human_request_sources.direction.value,
            human_approval=capabilities.human_request.approval.value,
            human_approval_source=capabilities.human_request_sources.approval.value,
            human_input=capabilities.human_request.input.value,
            human_input_source=capabilities.human_request_sources.input.value,
            human_review=capabilities.human_request.review.value,
            human_review_source=capabilities.human_request_sources.review.value,
            requested_command_run=capabilities.requested_command_run.value,
            requested_command_run_source=capabilities.requested_command_run_source.value,
            command_run=capabilities.command_run.value,
            command_run_source=capabilities.command_run_source.value,
            created_at=prepared.due_at,
        )
    )


__all__ = ["StartingDispatchBasis", "TaskResumeEventBasis", "stage_starting_dispatch"]
