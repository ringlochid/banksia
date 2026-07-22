from __future__ import annotations

from dataclasses import dataclass


class SupportProjectionSignal:
    """Marker for one disposable exact-source support-projection hint."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class WorkflowManifestProjection(SupportProjectionSignal):
    flow_id: str
    active_flow_revision_id: str


@dataclass(frozen=True, slots=True)
class CriteriaProjection(SupportProjectionSignal):
    flow_revision_id: str
    owner_node_key: str
    slot: str
    version: int


@dataclass(frozen=True, slots=True)
class AttemptAssignmentProjection(SupportProjectionSignal):
    assignment_id: str
    attempt_id: str
    flow_revision_id: str


@dataclass(frozen=True, slots=True)
class LatestCheckpointProjection(SupportProjectionSignal):
    attempt_id: str
    checkpoint_id: str


@dataclass(frozen=True, slots=True)
class ArtifactProjection(SupportProjectionSignal):
    artifact_publication_id: str
    version: int


@dataclass(frozen=True, slots=True)
class TransientProjection(SupportProjectionSignal):
    transient_localization_id: str


ALL_SUPPORT_PROJECTION_SIGNAL_TYPES: tuple[type[SupportProjectionSignal], ...] = (
    WorkflowManifestProjection,
    CriteriaProjection,
    AttemptAssignmentProjection,
    LatestCheckpointProjection,
    ArtifactProjection,
    TransientProjection,
)

type SupportProjectionContextValue = str | int
type SupportProjectionSourceContext = tuple[
    tuple[str, SupportProjectionContextValue],
    ...,
]


def support_projection_source_context(
    signal: SupportProjectionSignal,
) -> SupportProjectionSourceContext:
    """Return the bounded source identity safe to expose in process health."""

    match signal:
        case WorkflowManifestProjection(
            flow_id=flow_id,
            active_flow_revision_id=active_flow_revision_id,
        ):
            return (
                ("flow_id", flow_id),
                ("active_flow_revision_id", active_flow_revision_id),
            )
        case CriteriaProjection(
            flow_revision_id=flow_revision_id,
            owner_node_key=owner_node_key,
            slot=slot,
            version=version,
        ):
            return (
                ("flow_revision_id", flow_revision_id),
                ("owner_node_key", owner_node_key),
                ("slot", slot),
                ("version", version),
            )
        case AttemptAssignmentProjection(
            assignment_id=assignment_id,
            attempt_id=attempt_id,
            flow_revision_id=flow_revision_id,
        ):
            return (
                ("assignment_id", assignment_id),
                ("attempt_id", attempt_id),
                ("flow_revision_id", flow_revision_id),
            )
        case LatestCheckpointProjection(
            attempt_id=attempt_id,
            checkpoint_id=checkpoint_id,
        ):
            return (("attempt_id", attempt_id), ("checkpoint_id", checkpoint_id))
        case ArtifactProjection(
            artifact_publication_id=artifact_publication_id,
            version=version,
        ):
            return (
                ("artifact_publication_id", artifact_publication_id),
                ("version", version),
            )
        case TransientProjection(transient_localization_id=transient_localization_id):
            return (("transient_localization_id", transient_localization_id),)
    raise TypeError(f"unsupported support projection signal: {type(signal).__name__}")


__all__ = [
    "ALL_SUPPORT_PROJECTION_SIGNAL_TYPES",
    "ArtifactProjection",
    "AttemptAssignmentProjection",
    "CriteriaProjection",
    "LatestCheckpointProjection",
    "SupportProjectionContextValue",
    "SupportProjectionSignal",
    "SupportProjectionSourceContext",
    "TransientProjection",
    "WorkflowManifestProjection",
    "support_projection_source_context",
]
