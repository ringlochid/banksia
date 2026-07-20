from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from autoclaw.runtime.projection.signals import (
    SupportProjectionSignal,
    SupportProjectionSourceContext,
    support_projection_source_context,
)

type SupportProjectionFailureKind = Literal[
    "dispatcher_failed",
    "handler_failed",
    "owner_inactive",
    "publish_failed",
    "queue_full",
    "retry_exhausted",
    "unsupported_signal",
]


@dataclass(frozen=True, slots=True)
class SupportProjectionFailure:
    failure_kind: SupportProjectionFailureKind
    signal_type: str
    source_context: SupportProjectionSourceContext
    exception_type: str | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class SupportProjectionHealthSnapshot:
    is_healthy: bool
    failure_count: int
    last_failure: SupportProjectionFailure | None


class SupportProjectionHealth:
    """Process-local support-projection failure state with sanitized context."""

    def __init__(self) -> None:
        self._failure_count = 0
        self._last_failure: SupportProjectionFailure | None = None

    def mark_failure(
        self,
        *,
        failure_kind: SupportProjectionFailureKind,
        signal: object | None,
        exception_type: str | None = None,
    ) -> None:
        signal_type, source_context = _failure_signal_context(signal)
        self._failure_count += 1
        self._last_failure = SupportProjectionFailure(
            failure_kind=failure_kind,
            signal_type=signal_type,
            source_context=source_context,
            exception_type=_sanitize_type_name(exception_type),
            occurred_at=datetime.now(UTC),
        )

    def snapshot(self) -> SupportProjectionHealthSnapshot:
        return SupportProjectionHealthSnapshot(
            is_healthy=self._failure_count == 0,
            failure_count=self._failure_count,
            last_failure=self._last_failure,
        )


def _failure_signal_context(
    signal: object | None,
) -> tuple[str, SupportProjectionSourceContext]:
    if signal is None:
        return "SupportProjectionOwner", ()
    signal_type = _sanitize_type_name(type(signal).__name__) or "unknown"
    if not isinstance(signal, SupportProjectionSignal):
        return signal_type, ()
    try:
        return signal_type, support_projection_source_context(signal)
    except TypeError:
        return signal_type, ()


def _sanitize_type_name(value: str | None) -> str | None:
    if value is None:
        return None
    sanitized = "".join(
        character for character in value if character.isalnum() or character in "._"
    )
    return sanitized[:128] or None


__all__ = [
    "SupportProjectionFailure",
    "SupportProjectionFailureKind",
    "SupportProjectionHealth",
    "SupportProjectionHealthSnapshot",
]
