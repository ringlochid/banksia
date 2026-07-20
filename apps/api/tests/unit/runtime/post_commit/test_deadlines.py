from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from autoclaw.runtime.post_commit.deadlines import DeadlineScheduler
from autoclaw.runtime.post_commit.signals import (
    CommandRunDue,
    DispatchStartDue,
    HumanRequestDue,
    RuntimeEffectSignal,
    WatchdogDue,
)


@dataclass
class RecordedTimer:
    delay_seconds: float
    callback: Callable[[], None]
    is_cancelled: bool = False

    def cancel(self) -> None:
        self.is_cancelled = True

    def fire(self) -> None:
        self.callback()


class RecordingTimerFactory:
    def __init__(self) -> None:
        self.timers: list[RecordedTimer] = []

    def __call__(
        self,
        delay_seconds: float,
        callback: Callable[[], None],
    ) -> RecordedTimer:
        timer = RecordedTimer(delay_seconds=delay_seconds, callback=callback)
        self.timers.append(timer)
        return timer


class RecordingDeadlinePublisher:
    def __init__(self) -> None:
        self.signals: list[RuntimeEffectSignal] = []

    def publish(self, signal: RuntimeEffectSignal) -> bool:
        self.signals.append(signal)
        return True


async def test_scheduler_publishes_overdue_exact_signal_without_sleeping() -> None:
    now = datetime(2030, 1, 1, 12, tzinfo=UTC)
    factory = RecordingTimerFactory()
    publisher = RecordingDeadlinePublisher()
    signal = HumanRequestDue("human.alpha", now - timedelta(seconds=1))
    scheduler = DeadlineScheduler(
        publish=publisher.publish,
        now=lambda: now,
        schedule_later=factory,
    )

    async with scheduler:
        assert scheduler.register(signal) is True
        assert factory.timers[0].delay_seconds == 0
        factory.timers[0].fire()

    assert publisher.signals == [signal]


async def test_scheduler_replaces_only_newer_revision_and_stale_timer_is_harmless() -> None:
    now = datetime(2030, 1, 1, 12, tzinfo=UTC)
    factory = RecordingTimerFactory()
    publisher = RecordingDeadlinePublisher()
    first = WatchdogDue("dispatch.alpha", 1, now + timedelta(seconds=30))
    current = WatchdogDue("dispatch.alpha", 2, now + timedelta(seconds=60))
    stale = WatchdogDue("dispatch.alpha", 1, now + timedelta(seconds=90))
    scheduler = DeadlineScheduler(
        publish=publisher.publish,
        now=lambda: now,
        schedule_later=factory,
    )

    async with scheduler:
        assert scheduler.register(first) is True
        assert scheduler.register(current) is True
        assert scheduler.register(stale) is False
        assert scheduler.register(current) is False
        assert factory.timers[0].is_cancelled is True

        factory.timers[0].fire()
        factory.timers[1].fire()

    assert publisher.signals == [current]


async def test_scheduler_isolates_source_families_and_cancels_exact_slot() -> None:
    now = datetime(2030, 1, 1, 12, tzinfo=UTC)
    factory = RecordingTimerFactory()
    publisher = RecordingDeadlinePublisher()
    command = CommandRunDue("shared-id", now + timedelta(seconds=10))
    provider = DispatchStartDue("shared-id", 1, now + timedelta(seconds=20))
    scheduler = DeadlineScheduler(
        publish=publisher.publish,
        now=lambda: now,
        schedule_later=factory,
    )

    async with scheduler:
        assert scheduler.register(command) is True
        assert scheduler.register(provider) is True
        assert scheduler.cancel_source(CommandRunDue, "shared-id") is True
        assert scheduler.cancel_source(CommandRunDue, "shared-id") is False

        factory.timers[0].fire()
        factory.timers[1].fire()

    assert factory.timers[0].is_cancelled is True
    assert publisher.signals == [provider]


async def test_scheduler_shutdown_cancels_pending_timers_and_has_no_manual_lifecycle() -> None:
    now = datetime(2030, 1, 1, 12, tzinfo=UTC)
    factory = RecordingTimerFactory()
    scheduler = DeadlineScheduler(
        publish=lambda signal: True,
        now=lambda: now,
        schedule_later=factory,
    )

    with pytest.raises(RuntimeError, match="outside its lifespan"):
        scheduler.register(HumanRequestDue("human.alpha", now))
    async with scheduler:
        scheduler.register(HumanRequestDue("human.alpha", now + timedelta(hours=1)))

    assert factory.timers[0].is_cancelled is True
    assert not hasattr(scheduler, "start")
    assert not hasattr(scheduler, "close")
