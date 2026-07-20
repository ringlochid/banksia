from pydantic import BaseModel, ConfigDict

from autoclaw.runtime.contracts.flow import RuntimeFlowRead
from autoclaw.runtime.contracts.primitives import EgressBoundary
from autoclaw.runtime.contracts.refs import CheckpointFileRef


class BoundaryWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    boundary: EgressBoundary


class BoundaryRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted_boundary: EgressBoundary
    flow: RuntimeFlowRead
    latest_checkpoint_ref: CheckpointFileRef | None = None


__all__ = ["BoundaryRead", "BoundaryWrite"]
