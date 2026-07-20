from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import cast

from pydantic import JsonValue, TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from autoclaw.persistence.models import HumanRequestModel
from autoclaw.runtime.clock import utc_now
from autoclaw.runtime.contracts import (
    HumanRequestResolution,
    HumanRequestResolutionKind,
    HumanRequestResolutionSurface,
    HumanRequestStatus,
)
from autoclaw.runtime.human_request.service import persist_human_request_resolution
from autoclaw.runtime.post_commit.deadlines import DeadlineScheduler
from autoclaw.runtime.post_commit.publisher import RuntimeEffectPublisher
from autoclaw.runtime.post_commit.signals import HumanRequestDue, HumanRequestOpened

type HumanRequestOpenedHandler = Callable[
    [AsyncSession, HumanRequestOpened],
    Awaitable[None],
]
type HumanRequestDueHandler = Callable[
    [AsyncSession, HumanRequestDue],
    Awaitable[None],
]
type HumanRequestDeadlineClock = Callable[[], datetime]

_TIMEOUT_SUMMARY = "The controller-owned human request reached its deadline."
_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])


def create_human_request_opened_handler(
    scheduler: DeadlineScheduler,
) -> HumanRequestOpenedHandler:
    async def handle(session: AsyncSession, signal: HumanRequestOpened) -> None:
        source = await _read_human_request(session, signal.request_id)
        if (
            source is None
            or source.status != HumanRequestStatus.OPEN.value
            or source.due_at is None
        ):
            scheduler.cancel_source(HumanRequestDue, signal.request_id)
            return
        scheduler.register(
            HumanRequestDue(
                request_id=source.request_id,
                due_at=_as_utc(source.due_at),
            )
        )

    return handle


def create_human_request_due_handler(
    *,
    runtime_effect_publisher: RuntimeEffectPublisher,
    now: HumanRequestDeadlineClock = utc_now,
) -> HumanRequestDueHandler:
    async def handle(session: AsyncSession, signal: HumanRequestDue) -> None:
        await expire_human_request(
            session,
            signal=signal,
            runtime_effect_publisher=runtime_effect_publisher,
            now=now(),
        )

    return handle


async def expire_human_request(
    session: AsyncSession,
    *,
    signal: HumanRequestDue,
    runtime_effect_publisher: RuntimeEffectPublisher | None = None,
    now: datetime | None = None,
) -> bool:
    """Terminalize one exact elapsed request deadline or lose harmlessly."""

    source = await _read_human_request(session, signal.request_id)
    if source is None or source.status != HumanRequestStatus.OPEN.value or source.due_at is None:
        return False
    stored_due_at = _as_utc(source.due_at)
    if stored_due_at != _as_utc(signal.due_at):
        return False
    resolved_at = _as_utc(now or utc_now())
    if resolved_at < stored_due_at:
        return False

    resolution = HumanRequestResolution(
        request_id=source.request_id,
        task_id=source.task_id,
        resolution_kind=HumanRequestResolutionKind.TIMED_OUT,
        policy_basis=_timeout_policy_basis(source),
        summary=_TIMEOUT_SUMMARY,
        resolved_at=resolved_at,
        resolved_by_actor_ref=None,
        resolved_by_surface=HumanRequestResolutionSurface.CONTROLLER,
    )
    return await persist_human_request_resolution(
        session,
        source=source,
        resolution=resolution,
        expected_due_at=source.due_at,
        runtime_effect_publisher=runtime_effect_publisher,
    )


async def _read_human_request(
    session: AsyncSession,
    request_id: str,
) -> HumanRequestModel | None:
    return cast(
        HumanRequestModel | None,
        await session.scalar(
            select(HumanRequestModel)
            .options(raiseload("*"))
            .where(HumanRequestModel.request_id == request_id)
        ),
    )


def _timeout_policy_basis(source: HumanRequestModel) -> dict[str, JsonValue]:
    basis: dict[str, JsonValue] = {
        "timeout_policy": _JSON_OBJECT_ADAPTER.validate_python(
            source.timeout_policy_json or {"kind": "deadline"},
            strict=True,
        ),
    }
    if source.default_behavior_json is not None:
        basis["default_behavior"] = _JSON_OBJECT_ADAPTER.validate_python(
            source.default_behavior_json,
            strict=True,
        )
    return basis


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "HumanRequestDueHandler",
    "HumanRequestOpenedHandler",
    "create_human_request_due_handler",
    "create_human_request_opened_handler",
    "expire_human_request",
]
