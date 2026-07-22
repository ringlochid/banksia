from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from banksia.definitions.contracts.workflow import ProviderKind
from banksia.runtime.contracts.capabilities import (
    EffectiveNetworkAccess,
    EffectiveProviderNativeAccess,
)
from banksia.runtime.contracts.common import RuntimeSchemaText
from banksia.runtime.contracts.primitives import FlowStatus, TaskComposeInput
from banksia.runtime.contracts.provider_resolution import ProviderSelectionBasis
from banksia.runtime.contracts.refs import WorkflowManifestRef


class TaskStartRequest(TaskComposeInput):
    """Public task-start contract over the authored task-compose body."""


class TaskStartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    task_id: RuntimeSchemaText
    compiled_plan_id: RuntimeSchemaText
    active_flow_revision_id: RuntimeSchemaText
    flow_status: FlowStatus
    workflow_manifest_ref: WorkflowManifestRef


class TaskComposePreviewIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: RuntimeSchemaText
    message: RuntimeSchemaText
    path: RuntimeSchemaText | None = None
    kind: Literal["schema", "cross_reference", "provider", "path"]


class TaskComposePreviewProviderResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_provider: ProviderKind
    resolved_provider: ProviderKind
    selection_basis: ProviderSelectionBasis


class TaskComposeNodePreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_key: RuntimeSchemaText
    provider_resolution: TaskComposePreviewProviderResolution
    provider_native_access: EffectiveProviderNativeAccess
    network_access: EffectiveNetworkAccess


class TaskComposePreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ready", "invalid"]
    nodes: tuple[TaskComposeNodePreview, ...] = ()
    errors: tuple[TaskComposePreviewIssue, ...] = ()
    warnings: tuple[TaskComposePreviewIssue, ...] = ()


__all__ = [
    "TaskComposeNodePreview",
    "TaskComposePreviewIssue",
    "TaskComposePreviewProviderResolution",
    "TaskComposePreviewResponse",
    "TaskStartRequest",
    "TaskStartResponse",
]
