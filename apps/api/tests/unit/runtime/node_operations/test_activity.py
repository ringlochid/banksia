from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from autoclaw.runtime.node_operations import (
    NodeActivitySignal,
    create_watchdog_activity_publisher,
)
from autoclaw.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    WatchdogDeadlineChanged,
)


async def test_committed_node_activity_publishes_exact_watchdog_generation() -> None:
    occurred_at = datetime(2030, 1, 1, 12, tzinfo=UTC)
    runtime_publisher = CapturedRuntimeEffectPublisher()
    publish_activity = create_watchdog_activity_publisher(
        runtime_publisher,
        inactivity_timeout_seconds=900,
    )

    await publish_activity(
        NodeActivitySignal(
            task_id="task.alpha",
            dispatch_id="dispatch.alpha",
            activity_revision=7,
            occurred_at=occurred_at,
        )
    )

    assert runtime_publisher.signals == (
        WatchdogDeadlineChanged(
            dispatch_id="dispatch.alpha",
            activity_revision=7,
            due_at=occurred_at + timedelta(seconds=900),
        ),
    )


def test_watchdog_activity_publisher_rejects_nonpositive_timeout() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        create_watchdog_activity_publisher(
            CapturedRuntimeEffectPublisher(),
            inactivity_timeout_seconds=0,
        )


__all__ = []
