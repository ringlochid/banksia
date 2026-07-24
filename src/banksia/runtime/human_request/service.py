from __future__ import annotations

import logging
from datetime import datetime
from typing import cast

from pydantic import JsonValue
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import AttemptWaitModel, HumanRequestModel, TaskModel
from banksia.runtime.clock import utc_now
from banksia.runtime.contracts import (
    HumanRequestListResponse,
    HumanRequestResolution,
    HumanRequestResolutionKind,
    HumanRequestResolutionSurface,
    HumanRequestResolveRequest,
    HumanRequestResolveResponse,
    HumanRequestStatus,
    TaskEventType,
    serialize_human_request_item_answers,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.currentness import (
    AttemptWaitIdentity,
    clear_current_attempt_wait,
)
from banksia.runtime.errors import RuntimeOperationError, missing_resource_error
from banksia.runtime.human_request.records import (
    human_request_read_from_model,
    read_human_request_file_references,
    validate_answered_item_responses,
)
from banksia.runtime.post_commit import HumanRequestTerminal, RuntimeEffectPublisher
from banksia.runtime.task_events import append_task_event

logger = logging.getLogger(__name__)

_RESOLUTION_SUMMARY = "Human answered the controller-owned request."
_CONFLICT_NEXT_STEP = "Reread the current human-request source before retrying the resolution."


async def list_human_requests(
    session: AsyncSession,
    *,
    task_id: str,
) -> HumanRequestListResponse:
    await _require_task_exists(session, task_id)
    rows = list(
        await session.scalars(
            select(HumanRequestModel)
            .where(HumanRequestModel.task_id == task_id)
            .order_by(
                HumanRequestModel.opened_at.asc(),
                HumanRequestModel.request_id.asc(),
            )
        )
    )
    items = []
    for row in rows:
        files = await read_human_request_file_references(
            session,
            request_id=row.request_id,
        )
        items.append(human_request_read_from_model(row, files=files))
    return HumanRequestListResponse(task_id=task_id, items=tuple(items))


async def resolve_human_request(
    session: AsyncSession,
    *,
    task_id: str,
    request_id: str,
    request: HumanRequestResolveRequest,
    actor_ref: str | None = None,
    resolved_by_surface: HumanRequestResolutionSurface = (
        HumanRequestResolutionSurface.CONTROL_API
    ),
    runtime_effect_publisher: RuntimeEffectPublisher | None = None,
) -> HumanRequestResolveResponse:
    source = await _human_request_for_task(
        session,
        task_id=task_id,
        request_id=request_id,
    )
    if source is None:
        raise _human_request_conflict(f"human request '{request_id}' is not current")
    item_responses = dict(request.item_responses)
    validate_answered_item_responses(source, item_responses)

    resolved_at = utc_now()
    resolution = HumanRequestResolution(
        request_id=source.request_id,
        task_id=source.task_id,
        resolution_kind=HumanRequestResolutionKind.ANSWERED,
        item_responses=item_responses,
        summary=_RESOLUTION_SUMMARY,
        resolved_by_actor_ref=actor_ref,
        resolved_by_surface=resolved_by_surface,
        resolved_at=resolved_at,
    )
    won = await persist_human_request_resolution(
        session,
        source=source,
        resolution=resolution,
        runtime_effect_publisher=runtime_effect_publisher,
    )
    if not won:
        raise _human_request_conflict(f"human request '{request_id}' is already terminal")

    return HumanRequestResolveResponse(task_id=task_id, resolution=resolution)


async def persist_human_request_resolution(
    session: AsyncSession,
    *,
    source: HumanRequestModel,
    resolution: HumanRequestResolution,
    expected_due_at: datetime | None = None,
    resolution_policy_basis: dict[str, JsonValue] | None = None,
    runtime_effect_publisher: RuntimeEffectPublisher | None = None,
) -> bool:
    """Commit one exact answer, timeout, or cancellation winner."""

    if resolution.request_id != source.request_id or resolution.task_id != source.task_id:
        raise ValueError("human request resolution does not match its exact source")
    if (
        resolution.resolution_kind == HumanRequestResolutionKind.TIMED_OUT
        and expected_due_at is None
    ):
        raise ValueError("human request timeout requires its exact stored deadline")
    terminal_status, event_type = _terminal_resolution_state(resolution.resolution_kind)
    predicates = [
        HumanRequestModel.request_id == source.request_id,
        HumanRequestModel.task_id == source.task_id,
        HumanRequestModel.status == HumanRequestStatus.OPEN.value,
    ]
    if expected_due_at is not None:
        predicates.append(HumanRequestModel.due_at == expected_due_at)
    request_id = await session.scalar(
        update(HumanRequestModel)
        .where(*predicates)
        .values(
            status=terminal_status.value,
            resolution_kind=resolution.resolution_kind.value,
            item_responses_json=serialize_human_request_item_answers(resolution.item_responses),
            resolution_policy_basis_json=resolution_policy_basis,
            resolution_summary=resolution.summary,
            resolved_by_actor_ref=resolution.resolved_by_actor_ref,
            resolved_by_surface=resolution.resolved_by_surface.value,
            resolved_at=resolution.resolved_at,
        )
        .returning(HumanRequestModel.request_id)
    )
    if request_id is None:
        await session.rollback()
        return False

    wait_consumed = await _consume_exact_human_wait(session, source=source)
    if not wait_consumed:
        await session.rollback()
        raise _human_request_conflict(
            f"human request '{source.request_id}' no longer owns its exact Attempt wait"
        )

    await _append_human_request_terminal_event(
        session,
        source=source,
        resolution=resolution,
        terminal_status=terminal_status,
        event_type=event_type,
    )
    await session.commit()
    publish_human_request_terminal(
        request_id=source.request_id,
        runtime_effect_publisher=runtime_effect_publisher,
    )
    return True


def publish_human_request_terminal(
    *,
    request_id: str,
    runtime_effect_publisher: RuntimeEffectPublisher | None,
) -> None:
    if runtime_effect_publisher is None:
        return
    try:
        runtime_effect_publisher.publish(HumanRequestTerminal(request_id))
    except Exception:
        logger.exception(
            "failed to publish committed human-request terminal hint",
            extra={"request_id": request_id},
        )


async def _consume_exact_human_wait(
    session: AsyncSession,
    *,
    source: HumanRequestModel,
) -> bool:
    wait_id = await session.scalar(
        delete(AttemptWaitModel)
        .where(
            AttemptWaitModel.task_id == source.task_id,
            AttemptWaitModel.assignment_id == source.assignment_id,
            AttemptWaitModel.attempt_id == source.attempt_id,
            AttemptWaitModel.source_dispatch_id == source.source_dispatch_id,
            AttemptWaitModel.human_request_id == source.request_id,
            AttemptWaitModel.command_run_id.is_(None),
            AttemptWaitModel.delegation_wave_id.is_(None),
        )
        .returning(AttemptWaitModel.wait_id)
    )
    if wait_id is None:
        return False
    return await clear_current_attempt_wait(
        session,
        identity=AttemptWaitIdentity(
            task_id=source.task_id,
            assignment_id=source.assignment_id,
            attempt_id=source.attempt_id,
            wait_id=wait_id,
        ),
    )


async def _append_human_request_terminal_event(
    session: AsyncSession,
    *,
    source: HumanRequestModel,
    resolution: HumanRequestResolution,
    terminal_status: HumanRequestStatus,
    event_type: TaskEventType,
) -> None:
    await append_task_event(
        session,
        task_id=source.task_id,
        event_type=event_type,
        event_source=_event_source_for_resolution_surface(resolution.resolved_by_surface),
        occurred_at=resolution.resolved_at,
        dispatch_id=source.source_dispatch_id,
        attempt_id=source.attempt_id,
        actor_ref=resolution.resolved_by_actor_ref,
        payload={
            "request_id": source.request_id,
            "kind": source.request_kind,
            "summary": source.request_summary,
            "source_dispatch_id": source.source_dispatch_id,
            "due_at": source.due_at,
            "status": terminal_status.value,
            "resolution_kind": resolution.resolution_kind.value,
            "resolution_summary": resolution.summary,
            "resolved_at": resolution.resolved_at,
            "resolved_by_surface": resolution.resolved_by_surface.value,
            "resolved_by_actor_ref": resolution.resolved_by_actor_ref,
        },
    )


def _terminal_resolution_state(
    resolution_kind: HumanRequestResolutionKind,
) -> tuple[HumanRequestStatus, TaskEventType]:
    if resolution_kind == HumanRequestResolutionKind.ANSWERED:
        return HumanRequestStatus.RESOLVED, TaskEventType.HUMAN_REQUEST_RESOLVED
    if resolution_kind == HumanRequestResolutionKind.TIMED_OUT:
        return HumanRequestStatus.TIMED_OUT, TaskEventType.HUMAN_REQUEST_TIMED_OUT
    return HumanRequestStatus.CANCELLED, TaskEventType.HUMAN_REQUEST_CANCELLED


async def _human_request_for_task(
    session: AsyncSession,
    *,
    task_id: str,
    request_id: str,
) -> HumanRequestModel | None:
    return cast(
        HumanRequestModel | None,
        await session.scalar(
            select(HumanRequestModel).where(
                HumanRequestModel.task_id == task_id,
                HumanRequestModel.request_id == request_id,
            )
        ),
    )


async def _require_task_exists(session: AsyncSession, task_id: str) -> None:
    task_exists = await session.scalar(
        select(TaskModel.task_id).where(TaskModel.task_id == task_id).limit(1)
    )
    if task_exists is None:
        raise missing_resource_error(f"unknown task_id '{task_id}'")


def _human_request_conflict(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary=summary,
        is_retryable=False,
        suggested_next_step=_CONFLICT_NEXT_STEP,
        status_code_override=409,
    )


def _event_source_for_resolution_surface(
    surface: HumanRequestResolutionSurface,
) -> str:
    if surface == HumanRequestResolutionSurface.OPERATOR_MCP:
        return "operator_mcp"
    if surface == HumanRequestResolutionSurface.CONTROLLER:
        return "controller"
    return "control_api"


__all__ = [
    "list_human_requests",
    "persist_human_request_resolution",
    "publish_human_request_terminal",
    "resolve_human_request",
]
