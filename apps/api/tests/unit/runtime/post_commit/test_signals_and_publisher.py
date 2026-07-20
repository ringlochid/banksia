from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest
from autoclaw.runtime.post_commit.health import RuntimeEffectHealth
from autoclaw.runtime.post_commit.publisher import CapturedRuntimeEffectPublisher
from autoclaw.runtime.post_commit.signals import (
    ALL_RUNTIME_EFFECT_SIGNAL_TYPES,
    BoundaryAccepted,
    CommandProcessExited,
    CommandRunCancellationRequested,
    CommandRunDue,
    CommandRunPending,
    CommandRunTerminal,
    DispatchCleanupRequested,
    DispatchStartDue,
    FlowStartCommitted,
    HumanRequestDue,
    HumanRequestOpened,
    HumanRequestTerminal,
    TransientCleanupRequested,
    WatchdogDeadlineChanged,
    WatchdogDue,
)

DUE_AT = datetime(2026, 7, 18, 12, 30, tzinfo=UTC)


def test_runtime_effect_signals_are_frozen_and_complete() -> None:
    signals = (
        FlowStartCommitted("flow.alpha"),
        BoundaryAccepted("dispatch.alpha"),
        HumanRequestOpened("human.alpha"),
        HumanRequestDue("human.alpha", DUE_AT),
        HumanRequestTerminal("human.alpha"),
        CommandRunPending("command.alpha"),
        CommandRunDue("command.alpha", DUE_AT),
        CommandRunCancellationRequested("command.alpha", 3),
        CommandRunTerminal("command.alpha"),
        CommandProcessExited("command.alpha", 3),
        DispatchCleanupRequested("dispatch.alpha"),
        TransientCleanupRequested("transient.alpha", DUE_AT),
        WatchdogDeadlineChanged("dispatch.alpha", 4, DUE_AT),
        WatchdogDue("dispatch.alpha", 4, DUE_AT),
        DispatchStartDue("dispatch.alpha", 5, DUE_AT),
    )

    assert tuple(type(signal) for signal in signals) == ALL_RUNTIME_EFFECT_SIGNAL_TYPES
    with pytest.raises(FrozenInstanceError):
        signals[0].flow_id = "flow.changed"  # type: ignore[misc]


def test_captured_publisher_records_exact_signals_without_a_drain_api() -> None:
    publisher = CapturedRuntimeEffectPublisher()
    signal = BoundaryAccepted("dispatch.alpha")

    assert publisher.publish(signal) is True

    assert publisher.signals == (signal,)
    assert not hasattr(publisher, "drain")
    assert not hasattr(publisher, "wait_for_runtime_effects")


def test_runtime_health_records_only_sanitized_exact_signal_context() -> None:
    health = RuntimeEffectHealth()
    signal = DispatchStartDue("dispatch.alpha", 7, DUE_AT)

    health.mark_failure(
        failure_kind="handler_failed",
        signal=signal,
        exception_type="ProviderSecretError",
    )

    snapshot = health.snapshot()
    assert snapshot.is_healthy is False
    assert snapshot.failure_count == 1
    assert snapshot.last_failure is not None
    assert snapshot.last_failure.signal_type == "DispatchStartDue"
    assert dict(snapshot.last_failure.source_context) == {
        "dispatch_id": "dispatch.alpha",
        "due_at": DUE_AT.isoformat(),
        "provider_start_revision": 7,
    }
    assert snapshot.last_failure.exception_type == "ProviderSecretError"
    assert "secret payload" not in repr(snapshot)
