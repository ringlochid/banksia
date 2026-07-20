"""Non-authoritative runtime projection package."""

from autoclaw.runtime.projection.health import (
    SupportProjectionFailure,
    SupportProjectionHealth,
    SupportProjectionHealthSnapshot,
)
from autoclaw.runtime.projection.owner import SupportProjectionOwner
from autoclaw.runtime.projection.signals import (
    ArtifactProjection,
    AttemptAssignmentProjection,
    CriteriaProjection,
    LatestCheckpointProjection,
    SupportProjectionSignal,
    TransientProjection,
    WorkflowManifestProjection,
)

__all__ = [
    "ArtifactProjection",
    "AttemptAssignmentProjection",
    "CriteriaProjection",
    "LatestCheckpointProjection",
    "SupportProjectionFailure",
    "SupportProjectionHealth",
    "SupportProjectionHealthSnapshot",
    "SupportProjectionOwner",
    "SupportProjectionSignal",
    "TransientProjection",
    "WorkflowManifestProjection",
]
