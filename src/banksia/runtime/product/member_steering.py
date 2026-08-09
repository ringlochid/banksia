from __future__ import annotations

import hmac
from dataclasses import dataclass
from secrets import token_urlsafe

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AssignmentModel,
    AttemptModel,
    DispatchTurnModel,
    TaskEventModel,
    TaskModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.clock import utc_now
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.contracts.primitives import TaskEventSource, TaskEventType
from banksia.runtime.contracts.task import (
    MemberSteerReceipt,
    MemberSteerRequest,
    ProductAction,
    ProductActionConfirmation,
)
from banksia.runtime.contracts.task_event_payloads import MemberSteeredEventPayload
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.product.action_ids import product_action_id
from banksia.runtime.product.paths import build_product_api_path
from banksia.runtime.providers import ProviderAdapterRegistry, ProviderSteerOutcome
from banksia.runtime.task_events import append_task_event


@dataclass(frozen=True, slots=True)
class MemberSteerSource:
    task_id: str
    team_revision_id: str
    member_id: str
    assignment_id: str
    attempt_id: str
    dispatch_id: str
    provider: ProviderKind
    accepted_steer_count: int


async def read_task_member_steer_actions(
    session: AsyncSession,
    *,
    task_id: str,
    adapters: ProviderAdapterRegistry | None,
) -> dict[str, ProductAction]:
    if adapters is None:
        return {}
    actions: dict[str, ProductAction] = {}
    for source in await _read_member_steer_sources(session, task_id=task_id):
        try:
            adapter = adapters.get(source.provider)
        except LookupError:
            continue
        if await adapter.can_steer(source.dispatch_id):
            actions[source.member_id] = _steer_action(source)
    return actions


async def steer_product_task_member(
    session: AsyncSession,
    *,
    task_id: str,
    member_id: str,
    request: MemberSteerRequest,
    adapters: ProviderAdapterRegistry,
    actor_ref: str | None,
    event_source: TaskEventSource,
) -> MemberSteerReceipt:
    event_id = product_action_id("member-steer-event", request.action_id)
    existing = await session.get(TaskEventModel, event_id)
    if existing is not None:
        payload = MemberSteeredEventPayload.model_validate(existing.payload)
        if (
            existing.task_id != task_id
            or existing.member_id != member_id
            or payload.action_id != request.action_id
            or payload.message != request.message
        ):
            raise _action_unavailable()
        return await _receipt(
            session,
            task_id=task_id,
            status=ProviderSteerOutcome.DELIVERED,
            adapters=adapters,
        )

    source = await _read_member_steer_source(
        session,
        task_id=task_id,
        member_id=member_id,
    )
    if source is None:
        raise _action_unavailable()
    action = _steer_action(source)
    if not hmac.compare_digest(action.id, request.action_id):
        raise _action_unavailable()

    try:
        adapter = adapters.get(source.provider)
    except LookupError as exc:
        raise _action_unavailable() from exc
    outcome = await adapter.steer(source.dispatch_id, request.message)
    if outcome is ProviderSteerOutcome.NOT_RUNNING:
        raise _action_unavailable()
    if outcome is ProviderSteerOutcome.UNCERTAIN:
        return await _receipt(
            session,
            task_id=task_id,
            status=outcome,
            adapters=adapters,
        )

    await _record_delivered_steer(
        session,
        source=source,
        request=request,
        event_id=event_id,
        actor_ref=actor_ref,
        event_source=event_source,
    )
    return await _receipt(
        session,
        task_id=task_id,
        status=outcome,
        adapters=adapters,
    )


async def _record_delivered_steer(
    session: AsyncSession,
    *,
    source: MemberSteerSource,
    request: MemberSteerRequest,
    event_id: str,
    actor_ref: str | None,
    event_source: TaskEventSource,
) -> None:
    occurred_at = utc_now()
    await append_task_event(
        session,
        task_id=source.task_id,
        event_id=event_id,
        event_type=TaskEventType.MEMBER_STEERED,
        event_source=event_source,
        occurred_at=occurred_at,
        team_revision_id=source.team_revision_id,
        dispatch_id=source.dispatch_id,
        attempt_id=source.attempt_id,
        member_id=source.member_id,
        actor_ref=actor_ref,
        payload=MemberSteeredEventPayload(
            action_id=request.action_id,
            assignment_id=source.assignment_id,
            source_dispatch_id=source.dispatch_id,
            message=request.message,
        ),
    )
    task = await session.get(TaskModel, source.task_id)
    if task is None:  # pragma: no cover - source query owns this relationship
        raise RuntimeError("Task disappeared while recording a Member steer")
    task.updated_at = occurred_at
    await session.commit()


async def _read_member_steer_source(
    session: AsyncSession,
    *,
    task_id: str,
    member_id: str,
) -> MemberSteerSource | None:
    sources = await _read_member_steer_sources(
        session,
        task_id=task_id,
        member_id=member_id,
    )
    return sources[0] if sources else None


async def _read_member_steer_sources(
    session: AsyncSession,
    *,
    task_id: str,
    member_id: str | None = None,
) -> tuple[MemberSteerSource, ...]:
    statement = (
        select(
            DispatchTurnModel.team_revision_id,
            AssignmentModel.member_id,
            AssignmentModel.assignment_id,
            AttemptModel.attempt_id,
            DispatchTurnModel.dispatch_id,
            DispatchTurnModel.resolved_provider,
        )
        .select_from(TaskModel)
        .join(
            AssignmentModel,
            (AssignmentModel.task_id == TaskModel.task_id) & AssignmentModel.closed_at.is_(None),
        )
        .join(
            AttemptModel,
            (AttemptModel.task_id == AssignmentModel.task_id)
            & (AttemptModel.assignment_id == AssignmentModel.assignment_id)
            & (AttemptModel.attempt_id == AssignmentModel.current_attempt_id),
        )
        .join(
            DispatchTurnModel,
            (DispatchTurnModel.task_id == AttemptModel.task_id)
            & (DispatchTurnModel.assignment_id == AttemptModel.assignment_id)
            & (DispatchTurnModel.attempt_id == AttemptModel.attempt_id)
            & (DispatchTurnModel.dispatch_id == AttemptModel.current_dispatch_id),
        )
        .where(
            TaskModel.task_id == task_id,
            TaskModel.status == "running",
            DispatchTurnModel.team_revision_id == TaskModel.current_team_revision_id,
            AttemptModel.status == "running",
            DispatchTurnModel.status == "open",
            DispatchTurnModel.adapter_started_at.is_not(None),
        )
    )
    if member_id is not None:
        statement = statement.where(AssignmentModel.member_id == member_id)
    rows = tuple((await session.execute(statement)).all())
    if not rows:
        return ()
    dispatch_ids = tuple(row.dispatch_id for row in rows)
    accepted_counts = {
        dispatch_id: int(count)
        for dispatch_id, count in (
            await session.execute(
                select(TaskEventModel.dispatch_id, func.count())
                .where(
                    TaskEventModel.task_id == task_id,
                    TaskEventModel.dispatch_id.in_(dispatch_ids),
                    TaskEventModel.event_type == TaskEventType.MEMBER_STEERED.value,
                )
                .group_by(TaskEventModel.dispatch_id)
            )
        ).all()
        if dispatch_id is not None
    }
    return tuple(
        MemberSteerSource(
            task_id=task_id,
            team_revision_id=row.team_revision_id,
            member_id=row.member_id,
            assignment_id=row.assignment_id,
            attempt_id=row.attempt_id,
            dispatch_id=row.dispatch_id,
            provider=ProviderKind(row.resolved_provider),
            accepted_steer_count=accepted_counts.get(row.dispatch_id, 0),
        )
        for row in rows
    )


def _steer_action(source: MemberSteerSource) -> ProductAction:
    action_id = product_action_id(
        "member-steer",
        source.task_id,
        source.member_id,
        source.assignment_id,
        source.attempt_id,
        source.dispatch_id,
        source.provider.value,
        source.accepted_steer_count,
    )
    return ProductAction(
        id=action_id,
        kind="steer",
        label="Steer",
        href=build_product_api_path(f"/tasks/{source.task_id}/members/{source.member_id}/steers"),
        confirmation=ProductActionConfirmation(
            is_required=False,
            title="Steer this Member",
            consequence=(
                "The message updates current work; completed work and tool effects are not undone."
            ),
        ),
        input_schema={
            "type": "object",
            "properties": {
                "action_id": {"type": "string"},
                "message": {"type": "string", "minLength": 1, "maxLength": 4096},
            },
            "required": ["action_id", "message"],
            "additionalProperties": False,
        },
    )


async def _receipt(
    session: AsyncSession,
    *,
    task_id: str,
    status: ProviderSteerOutcome,
    adapters: ProviderAdapterRegistry,
) -> MemberSteerReceipt:
    from banksia.runtime.product.tasks import read_product_task

    delivered = status is ProviderSteerOutcome.DELIVERED
    return MemberSteerReceipt(
        receipt_id=f"receipt.{token_urlsafe(24)}",
        status="delivered" if delivered else "uncertain",
        status_message=(
            "The Member was steered."
            if delivered
            else "Banksia could not confirm whether the steer reached the Member."
        ),
        task=await read_product_task(
            session,
            task_id,
            provider_adapters=adapters,
        ),
    )


def _action_unavailable() -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary="That Member can no longer be steered.",
        is_retryable=False,
        suggested_next_step="Reload the run and select a currently working Member.",
        status_code_override=409,
    )


__all__ = [
    "MemberSteerSource",
    "read_task_member_steer_actions",
    "steer_product_task_member",
]
