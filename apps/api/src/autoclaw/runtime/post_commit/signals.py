from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class RuntimeEffectSignal:
    """Marker for one disposable exact-source runtime scheduling hint."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class FlowStartCommitted(RuntimeEffectSignal):
    flow_id: str


@dataclass(frozen=True, slots=True)
class BoundaryAccepted(RuntimeEffectSignal):
    source_dispatch_id: str


@dataclass(frozen=True, slots=True)
class HumanRequestOpened(RuntimeEffectSignal):
    request_id: str


@dataclass(frozen=True, slots=True)
class HumanRequestDue(RuntimeEffectSignal):
    request_id: str
    due_at: datetime


@dataclass(frozen=True, slots=True)
class HumanRequestTerminal(RuntimeEffectSignal):
    request_id: str


@dataclass(frozen=True, slots=True)
class CommandRunPending(RuntimeEffectSignal):
    run_id: str


@dataclass(frozen=True, slots=True)
class CommandRunDue(RuntimeEffectSignal):
    run_id: str
    due_at: datetime


@dataclass(frozen=True, slots=True)
class CommandRunCancellationRequested(RuntimeEffectSignal):
    run_id: str
    ownership_revision: int


@dataclass(frozen=True, slots=True)
class CommandRunTerminal(RuntimeEffectSignal):
    run_id: str


@dataclass(frozen=True, slots=True)
class CommandProcessExited(RuntimeEffectSignal):
    run_id: str
    ownership_revision: int


@dataclass(frozen=True, slots=True)
class DispatchCleanupRequested(RuntimeEffectSignal):
    dispatch_id: str


@dataclass(frozen=True, slots=True)
class TransientCleanupRequested(RuntimeEffectSignal):
    transient_localization_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class WatchdogDeadlineChanged(RuntimeEffectSignal):
    dispatch_id: str
    activity_revision: int
    due_at: datetime


@dataclass(frozen=True, slots=True)
class WatchdogDue(RuntimeEffectSignal):
    dispatch_id: str
    activity_revision: int
    due_at: datetime


@dataclass(frozen=True, slots=True)
class DispatchStartDue(RuntimeEffectSignal):
    dispatch_id: str
    provider_start_revision: int
    due_at: datetime


ALL_RUNTIME_EFFECT_SIGNAL_TYPES: tuple[type[RuntimeEffectSignal], ...] = (
    FlowStartCommitted,
    BoundaryAccepted,
    HumanRequestOpened,
    HumanRequestDue,
    HumanRequestTerminal,
    CommandRunPending,
    CommandRunDue,
    CommandRunCancellationRequested,
    CommandRunTerminal,
    CommandProcessExited,
    DispatchCleanupRequested,
    TransientCleanupRequested,
    WatchdogDeadlineChanged,
    WatchdogDue,
    DispatchStartDue,
)

type RuntimeEffectContextValue = str | int
type RuntimeEffectSourceContext = tuple[tuple[str, RuntimeEffectContextValue], ...]


def runtime_effect_source_context(
    signal: RuntimeEffectSignal,
) -> RuntimeEffectSourceContext:
    """Return the bounded non-secret identity fields safe for runtime health."""

    match signal:
        case FlowStartCommitted(flow_id=flow_id):
            return (("flow_id", flow_id),)
        case BoundaryAccepted(source_dispatch_id=source_dispatch_id):
            return (("source_dispatch_id", source_dispatch_id),)
        case HumanRequestOpened(request_id=request_id):
            return (("request_id", request_id),)
        case HumanRequestDue(request_id=request_id, due_at=due_at):
            return (("request_id", request_id), ("due_at", due_at.isoformat()))
        case HumanRequestTerminal(request_id=request_id):
            return (("request_id", request_id),)
        case CommandRunPending(run_id=run_id):
            return (("run_id", run_id),)
        case CommandRunDue(run_id=run_id, due_at=due_at):
            return (("run_id", run_id), ("due_at", due_at.isoformat()))
        case CommandRunCancellationRequested(
            run_id=run_id,
            ownership_revision=ownership_revision,
        ):
            return (("run_id", run_id), ("ownership_revision", ownership_revision))
        case CommandRunTerminal(run_id=run_id):
            return (("run_id", run_id),)
        case CommandProcessExited(run_id=run_id, ownership_revision=ownership_revision):
            return (("run_id", run_id), ("ownership_revision", ownership_revision))
        case DispatchCleanupRequested(dispatch_id=dispatch_id):
            return (("dispatch_id", dispatch_id),)
        case TransientCleanupRequested(
            transient_localization_id=transient_localization_id,
            expires_at=expires_at,
        ):
            return (
                ("transient_localization_id", transient_localization_id),
                ("expires_at", expires_at.isoformat()),
            )
        case WatchdogDeadlineChanged(
            dispatch_id=dispatch_id,
            activity_revision=activity_revision,
            due_at=due_at,
        ):
            return (
                ("dispatch_id", dispatch_id),
                ("activity_revision", activity_revision),
                ("due_at", due_at.isoformat()),
            )
        case WatchdogDue(
            dispatch_id=dispatch_id,
            activity_revision=activity_revision,
            due_at=due_at,
        ):
            return (
                ("dispatch_id", dispatch_id),
                ("activity_revision", activity_revision),
                ("due_at", due_at.isoformat()),
            )
        case DispatchStartDue(
            dispatch_id=dispatch_id,
            provider_start_revision=provider_start_revision,
            due_at=due_at,
        ):
            return (
                ("dispatch_id", dispatch_id),
                ("provider_start_revision", provider_start_revision),
                ("due_at", due_at.isoformat()),
            )
    raise TypeError(f"unsupported runtime effect signal type: {type(signal).__name__}")


__all__ = [
    "ALL_RUNTIME_EFFECT_SIGNAL_TYPES",
    "BoundaryAccepted",
    "CommandProcessExited",
    "CommandRunCancellationRequested",
    "CommandRunDue",
    "CommandRunPending",
    "CommandRunTerminal",
    "DispatchCleanupRequested",
    "DispatchStartDue",
    "FlowStartCommitted",
    "HumanRequestDue",
    "HumanRequestOpened",
    "HumanRequestTerminal",
    "RuntimeEffectContextValue",
    "RuntimeEffectSignal",
    "RuntimeEffectSourceContext",
    "TransientCleanupRequested",
    "WatchdogDeadlineChanged",
    "WatchdogDue",
    "runtime_effect_source_context",
]
