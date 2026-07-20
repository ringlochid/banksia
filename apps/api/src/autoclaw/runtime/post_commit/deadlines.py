from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Protocol, Self

from autoclaw.runtime.clock import utc_now
from autoclaw.runtime.post_commit.signals import (
    CommandRunDue,
    DispatchStartDue,
    HumanRequestDue,
    RuntimeEffectSignal,
    WatchdogDue,
)

type DeadlineDueSignal = HumanRequestDue | CommandRunDue | WatchdogDue | DispatchStartDue
type DeadlineDueSignalType = (
    type[HumanRequestDue] | type[CommandRunDue] | type[WatchdogDue] | type[DispatchStartDue]
)
type _DeadlinePublish = Callable[[RuntimeEffectSignal], bool]
type _DeadlineClock = Callable[[], datetime]


class CancelableDeadlineTimer(Protocol):
    """Cancelable delayed callback returned by an event-loop scheduler."""

    def cancel(self) -> None: ...


type DeadlineTimerFactory = Callable[
    [float, Callable[[], None]],
    CancelableDeadlineTimer,
]


@dataclass(frozen=True, slots=True)
class _DeadlineSlot:
    signal_type: DeadlineDueSignalType
    source_id: str


@dataclass(frozen=True, slots=True)
class _ScheduledDeadline:
    signal: DeadlineDueSignal
    timer: CancelableDeadlineTimer


class DeadlineScheduler:
    """Lifespan-owned exact-generation timer registry without durable authority."""

    def __init__(
        self,
        *,
        publish: _DeadlinePublish,
        now: _DeadlineClock = utc_now,
        schedule_later: DeadlineTimerFactory | None = None,
    ) -> None:
        self._publish = publish
        self._now = now
        self._schedule_later = schedule_later
        self._deadlines: dict[_DeadlineSlot, _ScheduledDeadline] = {}
        self._is_accepting = False
        self._has_entered = False

    async def __aenter__(self) -> Self:
        if self._has_entered:
            raise RuntimeError("deadline scheduler lifespan cannot be re-entered")
        self._has_entered = True
        if self._schedule_later is None:
            self._schedule_later = asyncio.get_running_loop().call_later
        self._is_accepting = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self._is_accepting = False
        for scheduled in self._deadlines.values():
            scheduled.timer.cancel()
        self._deadlines.clear()

    def register(self, signal: DeadlineDueSignal) -> bool:
        """Register a current generation, replacing only an older generation."""

        if not self._is_accepting or self._schedule_later is None:
            raise RuntimeError("deadline scheduler is outside its lifespan")
        slot = _deadline_slot(signal)
        current = self._deadlines.get(slot)
        if current is not None:
            if current.signal == signal or not _is_newer_deadline(signal, current.signal):
                return False
            current.timer.cancel()

        delay_seconds = max(
            0.0,
            (_as_utc(signal.due_at) - _as_utc(self._now())).total_seconds(),
        )
        timer = self._schedule_later(
            delay_seconds,
            lambda: self._publish_if_current(slot, signal),
        )
        self._deadlines[slot] = _ScheduledDeadline(signal=signal, timer=timer)
        return True

    def cancel_source(
        self,
        signal_type: DeadlineDueSignalType,
        source_id: str,
    ) -> bool:
        """Cancel the process-local timer for one exact durable source."""

        scheduled = self._deadlines.pop(_DeadlineSlot(signal_type, source_id), None)
        if scheduled is None:
            return False
        scheduled.timer.cancel()
        return True

    def _publish_if_current(
        self,
        slot: _DeadlineSlot,
        signal: DeadlineDueSignal,
    ) -> None:
        current = self._deadlines.get(slot)
        if current is None or current.signal != signal:
            return
        del self._deadlines[slot]
        self._publish(signal)


def _deadline_slot(signal: DeadlineDueSignal) -> _DeadlineSlot:
    match signal:
        case HumanRequestDue(request_id=request_id):
            return _DeadlineSlot(HumanRequestDue, request_id)
        case CommandRunDue(run_id=run_id):
            return _DeadlineSlot(CommandRunDue, run_id)
        case WatchdogDue(dispatch_id=dispatch_id):
            return _DeadlineSlot(WatchdogDue, dispatch_id)
        case DispatchStartDue(dispatch_id=dispatch_id):
            return _DeadlineSlot(DispatchStartDue, dispatch_id)


def _is_newer_deadline(
    candidate: DeadlineDueSignal,
    current: DeadlineDueSignal,
) -> bool:
    if type(candidate) is not type(current):
        raise TypeError("deadline generations must belong to the same source family")
    match candidate, current:
        case (
            WatchdogDue(activity_revision=candidate_revision),
            WatchdogDue(activity_revision=current_revision),
        ):
            return candidate_revision > current_revision
        case (
            DispatchStartDue(provider_start_revision=candidate_revision),
            DispatchStartDue(provider_start_revision=current_revision),
        ):
            return candidate_revision > current_revision
        case HumanRequestDue(due_at=candidate_due), HumanRequestDue(due_at=current_due):
            return _as_utc(candidate_due) > _as_utc(current_due)
        case CommandRunDue(due_at=candidate_due), CommandRunDue(due_at=current_due):
            return _as_utc(candidate_due) > _as_utc(current_due)
    raise TypeError(f"unsupported deadline signal type: {type(candidate).__name__}")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "CancelableDeadlineTimer",
    "DeadlineDueSignal",
    "DeadlineDueSignalType",
    "DeadlineScheduler",
    "DeadlineTimerFactory",
]
