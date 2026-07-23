from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from banksia.runtime.contracts.common import RuntimeSchemaText
from banksia.runtime.contracts.primitives import FlowStatus, TaskComposeInput
from banksia.runtime.contracts.refs import WorkflowManifestRef


class TaskStartRequest(TaskComposeInput):
    """Temporary public start contract over the existing launch body."""


class TaskStartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    task_id: RuntimeSchemaText
    compiled_plan_id: RuntimeSchemaText
    active_flow_revision_id: RuntimeSchemaText
    flow_status: FlowStatus
    workflow_manifest_ref: WorkflowManifestRef


__all__ = ["TaskStartRequest", "TaskStartResponse"]
