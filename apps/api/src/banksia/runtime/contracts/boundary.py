from pydantic import BaseModel, ConfigDict

from banksia.runtime.contracts.flow import RuntimeFlowRead
from banksia.runtime.contracts.primitives import EgressBoundary


class BoundaryRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted_boundary: EgressBoundary
    flow: RuntimeFlowRead


__all__ = ["BoundaryRead"]
