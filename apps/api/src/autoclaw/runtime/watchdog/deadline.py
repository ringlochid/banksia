from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.persistence.models import DispatchTurnModel, FlowModel
from autoclaw.runtime.post_commit import WatchdogDeadlineChanged, WatchdogDue
from autoclaw.runtime.post_commit.deadlines import DeadlineScheduler

type WatchdogDeadlineChangedHandler = Callable[
    [AsyncSession, WatchdogDeadlineChanged], Awaitable[None]
]


def create_watchdog_deadline_changed_handler(
    scheduler: DeadlineScheduler,
    *,
    inactivity_timeout_seconds: int,
) -> WatchdogDeadlineChangedHandler:
    """Create the exact-dispatch watchdog deadline registration route."""

    async def register_deadline(
        session: AsyncSession,
        signal: WatchdogDeadlineChanged,
    ) -> None:
        row = (
            await session.execute(
                select(
                    DispatchTurnModel.dispatch_id,
                    DispatchTurnModel.status,
                    DispatchTurnModel.node_activity_revision,
                    DispatchTurnModel.adapter_started_at,
                    DispatchTurnModel.last_node_activity_at,
                    FlowModel.status,
                    FlowModel.current_dispatch_id,
                )
                .join(FlowModel, FlowModel.flow_id == DispatchTurnModel.flow_id)
                .where(DispatchTurnModel.dispatch_id == signal.dispatch_id)
            )
        ).one_or_none()
        if row is None:
            await session.rollback()
            scheduler.cancel_source(WatchdogDue, signal.dispatch_id)
            return

        (
            dispatch_id,
            dispatch_status,
            activity_revision,
            adapter_started_at,
            last_node_activity_at,
            flow_status,
            current_dispatch_id,
        ) = row
        await session.rollback()
        if (
            dispatch_status != "open"
            or flow_status != "running"
            or current_dispatch_id != dispatch_id
        ):
            scheduler.cancel_source(WatchdogDue, signal.dispatch_id)
            return
        if activity_revision != signal.activity_revision:
            return
        if adapter_started_at is None:
            scheduler.cancel_source(WatchdogDue, signal.dispatch_id)
            return

        due_at = calculate_watchdog_due_at(
            adapter_started_at=adapter_started_at,
            last_node_activity_at=last_node_activity_at,
            inactivity_timeout_seconds=inactivity_timeout_seconds,
        )
        if _as_utc(signal.due_at) != due_at:
            return
        scheduler.register(
            WatchdogDue(
                dispatch_id=dispatch_id,
                activity_revision=activity_revision,
                due_at=due_at,
            )
        )

    return register_deadline


def calculate_watchdog_due_at(
    *,
    adapter_started_at: datetime,
    last_node_activity_at: datetime | None,
    inactivity_timeout_seconds: int,
) -> datetime:
    """Return the authoritative inactivity deadline for one open dispatch."""

    adapter_anchor = _as_utc(adapter_started_at)
    activity_anchor = (
        _as_utc(last_node_activity_at) if last_node_activity_at is not None else adapter_anchor
    )
    return max(adapter_anchor, activity_anchor) + timedelta(seconds=inactivity_timeout_seconds)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "WatchdogDeadlineChangedHandler",
    "calculate_watchdog_due_at",
    "create_watchdog_deadline_changed_handler",
]
