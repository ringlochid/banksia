from pydantic import BaseModel, ConfigDict

from banksia.runtime.contracts.flow import RuntimeFlowRead
from banksia.runtime.contracts.primitives import EgressBoundary
from banksia.runtime.contracts.refs import CheckpointFileRef


class BoundaryWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    boundary: EgressBoundary


class BoundaryRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted_boundary: EgressBoundary
    flow: RuntimeFlowRead
    latest_checkpoint_ref: CheckpointFileRef | None = None


__all__ = ["BoundaryRead", "BoundaryWrite"]
