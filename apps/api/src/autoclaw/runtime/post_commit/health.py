from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from autoclaw.runtime.post_commit.signals import (
    RuntimeEffectSignal,
    RuntimeEffectSourceContext,
    runtime_effect_source_context,
)

type RuntimeEffectFailureKind = Literal[
    "command_owner_task_failed",
    "dispatcher_failed",
    "handler_failed",
    "publish_failed",
    "queue_full",
    "router_inactive",
    "unregistered_signal",
    "unsupported_signal",
]


@dataclass(frozen=True, slots=True)
class RuntimeEffectFailure:
    failure_kind: RuntimeEffectFailureKind
    signal_type: str
    source_context: RuntimeEffectSourceContext
    exception_type: str | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class RuntimeEffectHealthSnapshot:
    is_healthy: bool
    failure_count: int
    last_failure: RuntimeEffectFailure | None


class RuntimeEffectHealth:
    """Process-local runtime-effect failure state with sanitized context only."""

    def __init__(self) -> None:
        self._failure_count = 0
        self._last_failure: RuntimeEffectFailure | None = None

    def mark_failure(
        self,
        *,
        failure_kind: RuntimeEffectFailureKind,
        signal: object | None,
        exception_type: str | None = None,
    ) -> None:
        signal_type, source_context = _failure_signal_context(signal)
        self._failure_count += 1
        self._last_failure = RuntimeEffectFailure(
            failure_kind=failure_kind,
            signal_type=signal_type,
            source_context=source_context,
            exception_type=_sanitize_type_name(exception_type),
            occurred_at=datetime.now(UTC),
        )

    def snapshot(self) -> RuntimeEffectHealthSnapshot:
        return RuntimeEffectHealthSnapshot(
            is_healthy=self._failure_count == 0,
            failure_count=self._failure_count,
            last_failure=self._last_failure,
        )


def _failure_signal_context(
    signal: object | None,
) -> tuple[str, RuntimeEffectSourceContext]:
    if signal is None:
        return "RuntimeEffectRouter", ()
    signal_type = _sanitize_type_name(type(signal).__name__) or "unknown"
    if not isinstance(signal, RuntimeEffectSignal):
        return signal_type, ()
    try:
        return signal_type, runtime_effect_source_context(signal)
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
    "RuntimeEffectFailure",
    "RuntimeEffectFailureKind",
    "RuntimeEffectHealth",
    "RuntimeEffectHealthSnapshot",
]
