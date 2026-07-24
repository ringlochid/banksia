from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from banksia.interfaces.http.contracts.operation_failure import ProductFailureCode
from banksia.workflows.authoring_contracts import WorkflowDraftReadback


class _WorkflowTransportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WorkflowUndoRequest(_WorkflowTransportModel):
    receipt_id: str


class WorkflowPreconditionRequiredDetail(_WorkflowTransportModel):
    code: ProductFailureCode
    message: str


class WorkflowPreconditionRequiredResponse(_WorkflowTransportModel):
    detail: WorkflowPreconditionRequiredDetail


class WorkflowStaleDraftDetail(WorkflowPreconditionRequiredDetail):
    current: WorkflowDraftReadback


class WorkflowStaleDraftResponse(_WorkflowTransportModel):
    detail: WorkflowStaleDraftDetail


__all__ = [
    "WorkflowPreconditionRequiredResponse",
    "WorkflowStaleDraftResponse",
    "WorkflowUndoRequest",
]
