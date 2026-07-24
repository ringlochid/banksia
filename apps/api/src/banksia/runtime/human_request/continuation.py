from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from banksia.persistence.models import AttemptModel, FlowModel, HumanRequestModel
from banksia.runtime.contracts import (
    FileReference,
    HumanRequestOpenRequest,
    serialize_human_request_item_answers,
)
from banksia.runtime.contracts.prompt import (
    HumanResult,
    HumanResultSource,
    HumanResultTrigger,
)
from banksia.runtime.control_transitions import (
    pause_flow_for_runtime_transition_failure,
)
from banksia.runtime.dispatch.ordinary_context import (
    OrdinaryContinuationBasis,
    OrdinaryDispatchSnapshot,
)
from banksia.runtime.dispatch.ordinary_continuation import (
    OrdinaryOpeningResult,
    open_ordinary_successor,
)
from banksia.runtime.dispatch.preparation import (
    DispatchOpeningDependencies,
    PreparedDispatchRequest,
)
from banksia.runtime.human_request.records import (
    human_request_resolution_from_model,
    pending_human_request_from_model,
    read_human_request_file_references,
)
from banksia.runtime.post_commit import HumanRequestTerminal

type HumanRequestTerminalHandler = Callable[[AsyncSession, HumanRequestTerminal], Awaitable[None]]

_TERMINAL_HUMAN_REQUEST_STATUSES = ("resolved", "timed_out", "cancelled")


def create_human_request_terminal_handler(
    dependencies: DispatchOpeningDependencies,
) -> HumanRequestTerminalHandler:
    async def handle(session: AsyncSession, signal: HumanRequestTerminal) -> None:
        await open_human_request_successor(
            session,
            signal=signal,
            dependencies=dependencies,
        )

    return handle


async def open_human_request_successor(
    session: AsyncSession,
    *,
    signal: HumanRequestTerminal,
    dependencies: DispatchOpeningDependencies,
) -> OrdinaryOpeningResult:
    """Open at most one successor from one exact terminal human request."""

    return await open_ordinary_successor(
        session,
        source_id=signal.request_id,
        dependencies=dependencies,
        read_source=read_human_request_continuation_basis,
        claim_source=claim_human_request_continuation,
        record_failure=pause_failed_human_request_continuation,
        default_failure_code="human_result_dispatch_preparation_failed",
    )


async def read_human_request_continuation_basis(
    session: AsyncSession,
    request_id: str,
) -> OrdinaryContinuationBasis | None:
    """Read one terminal, unconsumed human source and its prompt-safe result."""

    source = await session.scalar(
        select(HumanRequestModel)
        .options(raiseload("*"))
        .where(
            HumanRequestModel.request_id == request_id,
            HumanRequestModel.status.in_(_TERMINAL_HUMAN_REQUEST_STATUSES),
            HumanRequestModel.successor_dispatch_id.is_(None),
        )
    )
    if source is None:
        return None
    files = await read_human_request_file_references(
        session,
        request_id=source.request_id,
    )
    return human_request_continuation_basis(
        source,
        opened_reason="human_result",
        files=files,
    )


async def claim_human_request_continuation(
    session: AsyncSession,
    snapshot: OrdinaryDispatchSnapshot,
    prepared: PreparedDispatchRequest,
) -> bool:
    """Conditionally record the one successor identity on the exact human source."""

    trigger = snapshot.basis.trigger
    if not isinstance(trigger, HumanResultTrigger):
        return False
    request = trigger.result.request
    resolution = trigger.result.resolution
    request_id = await session.scalar(
        update(HumanRequestModel)
        .where(
            HumanRequestModel.request_id == trigger.source.request_id,
            HumanRequestModel.task_id == snapshot.prompt.task_id,
            HumanRequestModel.flow_id == snapshot.prompt.flow_id,
            HumanRequestModel.assignment_id == snapshot.prompt.assignment_id,
            HumanRequestModel.attempt_id == snapshot.prompt.attempt_id,
            HumanRequestModel.source_dispatch_id == trigger.source.source_dispatch_id,
            HumanRequestModel.status.in_(_TERMINAL_HUMAN_REQUEST_STATUSES),
            HumanRequestModel.request_kind == request.kind.value,
            HumanRequestModel.request_summary == request.summary,
            HumanRequestModel.request_items_json
            == [item.model_dump(mode="json") for item in request.items],
            HumanRequestModel.resolution_kind == resolution.resolution_kind.value,
            HumanRequestModel.item_responses_json
            == serialize_human_request_item_answers(resolution.item_responses),
            HumanRequestModel.resolution_summary == resolution.summary,
            HumanRequestModel.resolved_by_actor_ref == resolution.resolved_by_actor_ref,
            HumanRequestModel.resolved_by_surface == resolution.resolved_by_surface.value,
            HumanRequestModel.resolved_at == resolution.resolved_at,
            HumanRequestModel.successor_dispatch_id.is_(None),
        )
        .values(successor_dispatch_id=prepared.dispatch_id)
        .returning(HumanRequestModel.request_id)
    )
    return request_id is not None


async def pause_failed_human_request_continuation(
    session: AsyncSession,
    request_id: str,
    paused_at: datetime,
    failure_code: str,
) -> tuple[str, ...]:
    """Pause the exact failed source and every runnable sibling Attempt lane."""

    source_is_unconsumed = exists(
        select(HumanRequestModel.request_id)
        .join(
            AttemptModel,
            (AttemptModel.task_id == HumanRequestModel.task_id)
            & (AttemptModel.flow_id == HumanRequestModel.flow_id)
            & (AttemptModel.assignment_id == HumanRequestModel.assignment_id)
            & (AttemptModel.attempt_id == HumanRequestModel.attempt_id),
        )
        .where(
            HumanRequestModel.request_id == request_id,
            HumanRequestModel.flow_id == FlowModel.flow_id,
            HumanRequestModel.task_id == FlowModel.task_id,
            HumanRequestModel.status.in_(_TERMINAL_HUMAN_REQUEST_STATUSES),
            HumanRequestModel.successor_dispatch_id.is_(None),
            AttemptModel.status == "running",
            AttemptModel.current_dispatch_id.is_(None),
            AttemptModel.current_wait_id.is_(None),
        )
    )
    return await pause_flow_for_runtime_transition_failure(
        session,
        source_is_current=source_is_unconsumed,
        paused_at=paused_at,
        pause_details={
            "source": "human_request",
            "request_id": request_id,
            "failure_code": failure_code,
        },
    )


def human_request_continuation_basis(
    source: HumanRequestModel,
    *,
    opened_reason: str,
    files: tuple[FileReference, ...] = (),
) -> OrdinaryContinuationBasis:
    return OrdinaryContinuationBasis(
        task_id=source.task_id,
        flow_id=source.flow_id,
        assignment_id=source.assignment_id,
        attempt_id=source.attempt_id,
        source_dispatch_id=source.source_dispatch_id,
        source_dispatch_closed_reason="human_request_wait",
        opened_reason=opened_reason,
        trigger=build_human_result_trigger(source, files=files),
    )


def build_human_result_trigger(
    source: HumanRequestModel,
    *,
    files: tuple[FileReference, ...] = (),
) -> HumanResultTrigger:
    """Build one complete typed request and terminal resolution."""

    resolution = human_request_resolution_from_model(source)
    if resolution is None:
        raise ValueError("terminal human request is missing resolution truth")
    pending = pending_human_request_from_model(source, files=files)
    return HumanResultTrigger(
        source=HumanResultSource(
            request_id=pending.request_id,
            source_dispatch_id=pending.source_dispatch_id,
        ),
        result=HumanResult(
            request=HumanRequestOpenRequest(
                kind=pending.kind,
                summary=pending.summary,
                items=pending.items,
                files=pending.files,
                timeout=(
                    pending.timeout
                    if pending.timeout.due_at is not None
                    or pending.timeout.default_behavior is not None
                    else None
                ),
            ),
            resolution=resolution,
        ),
    )


__all__ = [
    "HumanRequestTerminalHandler",
    "build_human_result_trigger",
    "claim_human_request_continuation",
    "create_human_request_terminal_handler",
    "human_request_continuation_basis",
    "open_human_request_successor",
    "pause_failed_human_request_continuation",
    "read_human_request_continuation_basis",
]
