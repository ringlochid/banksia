from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from autoclaw.runtime.post_commit.publisher import RuntimeEffectPublisher
from autoclaw.runtime.post_commit.signals import WatchdogDeadlineChanged


@dataclass(frozen=True)
class NodeActivitySignal:
    task_id: str
    dispatch_id: str
    activity_revision: int
    occurred_at: datetime


type NodeActivitySignalPublisher = Callable[[NodeActivitySignal], Awaitable[None]]


def create_watchdog_activity_publisher(
    runtime_effect_publisher: RuntimeEffectPublisher,
    *,
    inactivity_timeout_seconds: int,
) -> NodeActivitySignalPublisher:
    """Translate committed Node activity into one disposable watchdog hint."""

    if inactivity_timeout_seconds <= 0:
        raise ValueError("watchdog inactivity timeout must be positive")

    async def publish_activity(signal: NodeActivitySignal) -> None:
        runtime_effect_publisher.publish(
            WatchdogDeadlineChanged(
                dispatch_id=signal.dispatch_id,
                activity_revision=signal.activity_revision,
                due_at=signal.occurred_at + timedelta(seconds=inactivity_timeout_seconds),
            )
        )

    return publish_activity


__all__ = [
    "NodeActivitySignal",
    "NodeActivitySignalPublisher",
    "create_watchdog_activity_publisher",
]
