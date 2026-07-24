from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import exists, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AttemptModel,
    DispatchCapabilitySetModel,
    DispatchRequestModel,
    DispatchTurnModel,
    TaskModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.contracts import TaskEventSource, TaskEventType
from banksia.runtime.dispatch.currentness import dispatch_attempt_is_current
from banksia.runtime.post_commit import DispatchStartDue
from banksia.runtime.task_events import append_task_event
from banksia.runtime.team.currentness import dispatch_team_selection_is_current


@dataclass(frozen=True, slots=True)
class ProviderStartCandidate:
    """Minimum persisted facts for one exact current starting generation."""

    task_id: str
    team_revision_id: str
    task_control_revision: int
    assignment_id: str
    attempt_id: str
    member_id: str
    opened_reason: str
    predecessor_dispatch_id: str | None
    provider_kind: ProviderKind | None
    model_override: str | None
    effort_override: str | None
    gateway_profile: str | None
    provider_start_attempt_count: int
    persisted_due_at: datetime
    instructions: str | None
    input: str | None
    provider_native_access: str | None
    network_access: str | None
    sandbox_mode: str | None


@dataclass(frozen=True, slots=True)
class ProviderStartAcceptanceResult:
    """Report whether one exact provider-start generation won acceptance."""

    task_id: str
    dispatch_id: str
    provider_start_revision: int
    is_accepted: bool
    provider_start_attempt_count: int | None = None
    adapter_started_at: datetime | None = None
    node_activity_revision: int | None = None
    last_node_activity_at: datetime | None = None


async def accept_provider_start_if_current(
    session: AsyncSession,
    *,
    task_id: str,
    dispatch_id: str,
    expected_provider_start_revision: int,
    expected_provider_start_attempt_count: int,
    expected_due_at: datetime,
    accepted_at: datetime,
) -> ProviderStartAcceptanceResult:
    """Accept one exact generation; a zero-row update is an ordinary loser."""

    accepted_row = (
        await session.execute(
            update(DispatchTurnModel)
            .where(
                DispatchTurnModel.dispatch_id == dispatch_id,
                DispatchTurnModel.task_id == task_id,
                DispatchTurnModel.status == "starting",
                DispatchTurnModel.provider_start_revision == expected_provider_start_revision,
                DispatchTurnModel.provider_start_attempt_count
                == expected_provider_start_attempt_count,
                DispatchTurnModel.next_provider_start_at == expected_due_at,
                dispatch_attempt_is_current(),
                dispatch_team_selection_is_current(),
                exists(
                    select(TaskModel.task_id).where(
                        TaskModel.task_id == DispatchTurnModel.task_id,
                        TaskModel.status == "running",
                    )
                ),
            )
            .values(
                status="open",
                adapter_started_at=accepted_at,
                provider_start_attempt_count=DispatchTurnModel.provider_start_attempt_count + 1,
                next_provider_start_at=None,
                provider_start_retry_kind=None,
                provider_start_last_error_code=None,
            )
            .returning(
                DispatchTurnModel.dispatch_id,
                DispatchTurnModel.attempt_id,
                DispatchTurnModel.member_id,
                DispatchTurnModel.provider_start_attempt_count,
                DispatchTurnModel.node_activity_revision,
                DispatchTurnModel.last_node_activity_at,
            )
        )
    ).one_or_none()
    result = ProviderStartAcceptanceResult(
        task_id=task_id,
        dispatch_id=dispatch_id,
        provider_start_revision=expected_provider_start_revision,
        is_accepted=accepted_row is not None,
        provider_start_attempt_count=(
            int(accepted_row.provider_start_attempt_count) if accepted_row is not None else None
        ),
        adapter_started_at=accepted_at if accepted_row is not None else None,
        node_activity_revision=(
            int(accepted_row.node_activity_revision) if accepted_row is not None else None
        ),
        last_node_activity_at=(
            accepted_row.last_node_activity_at if accepted_row is not None else None
        ),
    )
    if accepted_row is not None:
        await _append_provider_start_accepted_event(
            session,
            task_id=task_id,
            dispatch_id=dispatch_id,
            accepted_at=accepted_at,
            attempt_id=accepted_row.attempt_id,
            member_id=accepted_row.member_id,
            attempt_count=accepted_row.provider_start_attempt_count,
            provider_start_revision=expected_provider_start_revision,
        )
    return result


async def read_provider_start_acceptance_after_commit(
    session: AsyncSession,
    *,
    candidate: ProviderStartCandidate,
    signal: DispatchStartDue,
) -> ProviderStartAcceptanceResult:
    """Reconcile an ambiguous commit using only exact scalar controller truth."""

    row = (
        (
            await session.execute(
                select(
                    DispatchTurnModel.status.label("dispatch_status"),
                    DispatchTurnModel.provider_start_revision.label("provider_start_revision"),
                    DispatchTurnModel.provider_start_attempt_count.label(
                        "provider_start_attempt_count"
                    ),
                    DispatchTurnModel.next_provider_start_at.label("next_provider_start_at"),
                    DispatchTurnModel.adapter_started_at.label("adapter_started_at"),
                    DispatchTurnModel.node_activity_revision.label("node_activity_revision"),
                    DispatchTurnModel.last_node_activity_at.label("last_node_activity_at"),
                    TaskModel.status.label("task_status"),
                    AttemptModel.status.label("attempt_status"),
                    AttemptModel.current_dispatch_id.label("current_dispatch_id"),
                    AttemptModel.current_wait_id.label("current_wait_id"),
                )
                .join(TaskModel, TaskModel.task_id == DispatchTurnModel.task_id)
                .join(AttemptModel, AttemptModel.attempt_id == DispatchTurnModel.attempt_id)
                .where(
                    DispatchTurnModel.dispatch_id == signal.dispatch_id,
                    DispatchTurnModel.task_id == candidate.task_id,
                    dispatch_team_selection_is_current(),
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    is_accepted = bool(
        row is not None
        and row.dispatch_status == "open"
        and row.provider_start_revision == signal.provider_start_revision
        and row.provider_start_attempt_count == candidate.provider_start_attempt_count + 1
        and row.next_provider_start_at is None
        and row.adapter_started_at is not None
        and row.task_status == "running"
        and row.attempt_status == "running"
        and row.current_dispatch_id == signal.dispatch_id
        and row.current_wait_id is None
    )
    if not is_accepted:
        return ProviderStartAcceptanceResult(
            task_id=candidate.task_id,
            dispatch_id=signal.dispatch_id,
            provider_start_revision=signal.provider_start_revision,
            is_accepted=False,
        )
    assert row is not None
    return ProviderStartAcceptanceResult(
        task_id=candidate.task_id,
        dispatch_id=signal.dispatch_id,
        provider_start_revision=signal.provider_start_revision,
        is_accepted=True,
        provider_start_attempt_count=int(row.provider_start_attempt_count),
        adapter_started_at=row.adapter_started_at,
        node_activity_revision=int(row.node_activity_revision),
        last_node_activity_at=row.last_node_activity_at,
    )


async def read_provider_start_candidate(
    session: AsyncSession,
    signal: DispatchStartDue,
) -> ProviderStartCandidate | None:
    """Read only the records needed to validate and launch one exact generation."""

    row = (
        (
            await session.execute(
                select(
                    DispatchTurnModel.task_id.label("task_id"),
                    DispatchTurnModel.team_revision_id.label("team_revision_id"),
                    TaskModel.control_revision.label("task_control_revision"),
                    DispatchTurnModel.assignment_id.label("assignment_id"),
                    DispatchTurnModel.attempt_id.label("attempt_id"),
                    DispatchTurnModel.member_id.label("member_id"),
                    DispatchTurnModel.opened_reason.label("opened_reason"),
                    DispatchTurnModel.predecessor_dispatch_id.label("predecessor_dispatch_id"),
                    DispatchTurnModel.provider_route_kind.label("provider_route_kind"),
                    DispatchTurnModel.model_override.label("model_override"),
                    DispatchTurnModel.effort_override.label("effort_override"),
                    DispatchTurnModel.gateway_profile.label("gateway_profile"),
                    DispatchTurnModel.provider_start_attempt_count.label(
                        "provider_start_attempt_count"
                    ),
                    DispatchTurnModel.next_provider_start_at.label("persisted_due_at"),
                    DispatchRequestModel.instructions.label("instructions"),
                    DispatchRequestModel.input.label("input"),
                    DispatchCapabilitySetModel.provider_native_access.label(
                        "provider_native_access"
                    ),
                    DispatchCapabilitySetModel.network_access.label("network_access"),
                    DispatchCapabilitySetModel.effective_sandbox_mode.label("sandbox_mode"),
                    DispatchTurnModel.status.label("dispatch_status"),
                    DispatchTurnModel.provider_start_revision.label("provider_start_revision"),
                    TaskModel.status.label("task_status"),
                    AttemptModel.status.label("attempt_status"),
                    AttemptModel.current_dispatch_id.label("current_dispatch_id"),
                    AttemptModel.current_wait_id.label("current_wait_id"),
                )
                .join(TaskModel, TaskModel.task_id == DispatchTurnModel.task_id)
                .join(AttemptModel, AttemptModel.attempt_id == DispatchTurnModel.attempt_id)
                .outerjoin(
                    DispatchRequestModel,
                    DispatchRequestModel.dispatch_id == DispatchTurnModel.dispatch_id,
                )
                .outerjoin(
                    DispatchCapabilitySetModel,
                    DispatchCapabilitySetModel.dispatch_id == DispatchTurnModel.dispatch_id,
                )
                .where(
                    DispatchTurnModel.dispatch_id == signal.dispatch_id,
                    dispatch_team_selection_is_current(),
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    if (
        row.dispatch_status != "starting"
        or row.provider_start_revision != signal.provider_start_revision
        or row.persisted_due_at is None
        or _as_utc(row.persisted_due_at) != _as_utc(signal.due_at)
        or row.task_status != "running"
        or row.attempt_status != "running"
        or row.current_dispatch_id != signal.dispatch_id
        or row.current_wait_id is not None
        or row.team_revision_id is None
    ):
        return None
    return _build_provider_start_candidate(row)


async def provider_start_is_current(
    session: AsyncSession,
    *,
    signal: DispatchStartDue,
    candidate: ProviderStartCandidate,
) -> bool:
    """Recheck exact currentness immediately before provider I/O."""

    is_current = bool(
        await session.scalar(
            select(
                exists().where(
                    DispatchTurnModel.dispatch_id == signal.dispatch_id,
                    DispatchTurnModel.task_id == candidate.task_id,
                    DispatchTurnModel.status == "starting",
                    DispatchTurnModel.provider_start_revision == signal.provider_start_revision,
                    DispatchTurnModel.provider_start_attempt_count
                    == candidate.provider_start_attempt_count,
                    DispatchTurnModel.next_provider_start_at == candidate.persisted_due_at,
                    dispatch_attempt_is_current(),
                    dispatch_team_selection_is_current(),
                    exists().where(
                        TaskModel.task_id == candidate.task_id,
                        TaskModel.status == "running",
                    ),
                )
            )
        )
    )
    await session.rollback()
    return is_current


async def rotate_provider_start_after_failure(
    session: AsyncSession,
    *,
    signal: DispatchStartDue,
    candidate: ProviderStartCandidate,
    retry: DispatchStartDue,
    failure_kind: str,
    error_code: str,
) -> bool:
    """Commit one next generation after a provider call failed or was uncertain."""

    rotated_dispatch_id = await session.scalar(
        update(DispatchTurnModel)
        .where(
            DispatchTurnModel.dispatch_id == signal.dispatch_id,
            DispatchTurnModel.task_id == candidate.task_id,
            DispatchTurnModel.status == "starting",
            DispatchTurnModel.provider_start_revision == signal.provider_start_revision,
            DispatchTurnModel.provider_start_attempt_count
            == candidate.provider_start_attempt_count,
            DispatchTurnModel.next_provider_start_at == candidate.persisted_due_at,
            dispatch_attempt_is_current(),
            dispatch_team_selection_is_current(),
            exists().where(
                TaskModel.task_id == candidate.task_id,
                TaskModel.status == "running",
            ),
        )
        .values(
            provider_start_revision=retry.provider_start_revision,
            provider_start_attempt_count=DispatchTurnModel.provider_start_attempt_count + 1,
            next_provider_start_at=retry.due_at,
            provider_start_retry_kind=failure_kind,
            provider_start_last_error_code=error_code,
        )
        .returning(DispatchTurnModel.dispatch_id)
    )
    if rotated_dispatch_id is None:
        await session.rollback()
        return False
    await append_task_event(
        session,
        task_id=candidate.task_id,
        event_type=TaskEventType.DISPATCH_START_UPDATED,
        event_source=TaskEventSource.CONTROLLER,
        occurred_at=datetime.now(UTC),
        team_revision_id=candidate.team_revision_id,
        dispatch_id=signal.dispatch_id,
        attempt_id=candidate.attempt_id,
        member_id=candidate.member_id,
        payload={
            "dispatch_id": signal.dispatch_id,
            "state": "retry_scheduled",
            "attempt_count": candidate.provider_start_attempt_count + 1,
            "provider_start_revision": retry.provider_start_revision,
            "next_attempt_at": retry.due_at,
            "retry_kind": failure_kind,
            "last_error_code": error_code,
        },
    )
    await session.commit()
    return True


async def _append_provider_start_accepted_event(
    session: AsyncSession,
    *,
    task_id: str,
    dispatch_id: str,
    accepted_at: datetime,
    attempt_id: str,
    member_id: str,
    attempt_count: int,
    provider_start_revision: int,
) -> None:
    await append_task_event(
        session,
        task_id=task_id,
        event_type=TaskEventType.DISPATCH_START_UPDATED,
        event_source=TaskEventSource.CONTROLLER,
        occurred_at=accepted_at,
        dispatch_id=dispatch_id,
        attempt_id=attempt_id,
        member_id=member_id,
        payload={
            "dispatch_id": dispatch_id,
            "state": "accepted",
            "attempt_count": attempt_count,
            "provider_start_revision": provider_start_revision,
            "next_attempt_at": None,
            "retry_kind": None,
            "last_error_code": None,
        },
    )


def _build_provider_start_candidate(row: RowMapping) -> ProviderStartCandidate:
    try:
        provider_kind: ProviderKind | None = ProviderKind(row["provider_route_kind"])
    except ValueError:
        provider_kind = None
    return ProviderStartCandidate(
        task_id=row["task_id"],
        team_revision_id=row["team_revision_id"],
        task_control_revision=row["task_control_revision"],
        assignment_id=row["assignment_id"],
        attempt_id=row["attempt_id"],
        member_id=row["member_id"],
        opened_reason=row["opened_reason"],
        predecessor_dispatch_id=row["predecessor_dispatch_id"],
        provider_kind=provider_kind,
        model_override=row["model_override"],
        effort_override=row["effort_override"],
        gateway_profile=row["gateway_profile"],
        provider_start_attempt_count=row["provider_start_attempt_count"],
        persisted_due_at=row["persisted_due_at"],
        instructions=row["instructions"],
        input=row["input"],
        provider_native_access=row["provider_native_access"],
        network_access=row["network_access"],
        sandbox_mode=row["sandbox_mode"],
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "ProviderStartAcceptanceResult",
    "ProviderStartCandidate",
    "accept_provider_start_if_current",
    "provider_start_is_current",
    "read_provider_start_acceptance_after_commit",
    "read_provider_start_candidate",
    "rotate_provider_start_after_failure",
]
