from __future__ import annotations

from dataclasses import dataclass


class SupportProjectionSignal:
    """Marker for one disposable exact-source support-projection hint."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class WorkflowManifestProjection(SupportProjectionSignal):
    flow_id: str
    active_flow_revision_id: str


ALL_SUPPORT_PROJECTION_SIGNAL_TYPES: tuple[type[SupportProjectionSignal], ...] = (
    WorkflowManifestProjection,
)

type SupportProjectionContextValue = str | int
type SupportProjectionSourceContext = tuple[
    tuple[str, SupportProjectionContextValue],
    ...,
]


def support_projection_source_context(
    signal: SupportProjectionSignal,
) -> SupportProjectionSourceContext:
    if isinstance(signal, WorkflowManifestProjection):
        return (
            ("flow_id", signal.flow_id),
            ("active_flow_revision_id", signal.active_flow_revision_id),
        )
    raise TypeError(f"unsupported support projection signal: {type(signal).__name__}")


__all__ = [
    "ALL_SUPPORT_PROJECTION_SIGNAL_TYPES",
    "SupportProjectionContextValue",
    "SupportProjectionSignal",
    "SupportProjectionSourceContext",
    "WorkflowManifestProjection",
    "support_projection_source_context",
]
