"""Non-authoritative runtime projection package."""

from banksia.runtime.projection.health import (
    SupportProjectionFailure,
    SupportProjectionHealth,
    SupportProjectionHealthSnapshot,
)
from banksia.runtime.projection.owner import SupportProjectionOwner
from banksia.runtime.projection.signals import (
    SupportProjectionSignal,
    WorkflowManifestProjection,
)

__all__ = [
    "SupportProjectionFailure",
    "SupportProjectionHealth",
    "SupportProjectionHealthSnapshot",
    "SupportProjectionOwner",
    "SupportProjectionSignal",
    "WorkflowManifestProjection",
]
