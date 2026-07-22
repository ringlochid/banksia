"""Non-authoritative runtime projection package."""

from banksia.runtime.projection.health import (
    SupportProjectionFailure,
    SupportProjectionHealth,
    SupportProjectionHealthSnapshot,
)
from banksia.runtime.projection.owner import SupportProjectionOwner
from banksia.runtime.projection.signals import (
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
