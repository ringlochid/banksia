from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
)

from banksia.runtime.contracts.assignment import AssignmentBody
from banksia.runtime.contracts.common import RuntimeSchemaText
from banksia.runtime.contracts.flow import RuntimeFlowRead
from banksia.runtime.contracts.refs import WorkflowManifestRef


class AssignChildPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_node_key: RuntimeSchemaText
    assignment: AssignmentBody


class AssignChildSuccess(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: Literal["assign_child"] = "assign_child"
    summary: RuntimeSchemaText | None = None
    target_node_key: RuntimeSchemaText
    target_assignment_key: RuntimeSchemaText
    target_attempt_id: RuntimeSchemaText
    flow: RuntimeFlowRead
    workflow_manifest_ref: WorkflowManifestRef | None = None


class ParentToolMutationSuccess(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: RuntimeSchemaText | None = None
    target_node_key: RuntimeSchemaText | None = None
    flow: RuntimeFlowRead
    workflow_manifest_ref: WorkflowManifestRef | None = None


__all__ = [
    "AssignChildPayload",
    "AssignChildSuccess",
    "ParentToolMutationSuccess",
]
