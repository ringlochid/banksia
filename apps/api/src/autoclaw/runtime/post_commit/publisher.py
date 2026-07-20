from __future__ import annotations

from typing import Protocol

from autoclaw.runtime.post_commit.signals import RuntimeEffectSignal


class RuntimeEffectPublisher(Protocol):
    """Nonblocking publication boundary for disposable runtime signals."""

    def publish(self, signal: RuntimeEffectSignal) -> bool:
        """Attempt an in-process enqueue without waiting for handler work."""

        ...


class CapturedRuntimeEffectPublisher:
    """Small test publisher that captures accepted signals without drain semantics."""

    def __init__(self, *, should_accept: bool = True) -> None:
        self._should_accept = should_accept
        self._signals: list[RuntimeEffectSignal] = []

    @property
    def signals(self) -> tuple[RuntimeEffectSignal, ...]:
        return tuple(self._signals)

    def publish(self, signal: RuntimeEffectSignal) -> bool:
        if not self._should_accept:
            return False
        self._signals.append(signal)
        return True


__all__ = ["CapturedRuntimeEffectPublisher", "RuntimeEffectPublisher"]
