"""Non-authoritative runtime projection package."""

from oh_my_subagents.runtime.projection.health import (
    SupportProjectionFailure,
    SupportProjectionHealth,
    SupportProjectionHealthSnapshot,
)
from oh_my_subagents.runtime.projection.owner import SupportProjectionOwner
from oh_my_subagents.runtime.projection.signals import (
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
