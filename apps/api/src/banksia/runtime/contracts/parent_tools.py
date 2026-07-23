from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
)

from banksia.runtime.contracts.checkpoint import TransientSurfaceWrite
from banksia.runtime.contracts.common import RuntimeSchemaText
from banksia.runtime.contracts.flow import RuntimeFlowRead
from banksia.runtime.contracts.refs import (
    AssignmentFileRef,
    CheckpointFileRef,
    WorkflowManifestRef,
)


class AssignmentIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: RuntimeSchemaText
    instruction: RuntimeSchemaText | None = None


class SupplementalSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: RuntimeSchemaText


class SupplementalDurableContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_slots: tuple[SupplementalSlot, ...] = ()
    criteria_slots: tuple[SupplementalSlot, ...] = ()


class AssignChildPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_node_key: RuntimeSchemaText
    assignment_intent: AssignmentIntent
    supplemental_durable_context: SupplementalDurableContext | None = None
    transient_surfaces: tuple[TransientSurfaceWrite, ...] = ()


class ReleaseGreenPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReleaseBlockedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssignChildSuccess(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: Literal["assign_child"] = "assign_child"
    summary: RuntimeSchemaText | None = None
    target_node_key: RuntimeSchemaText
    target_assignment_key: RuntimeSchemaText
    target_attempt_id: RuntimeSchemaText
    child_assignment_ref: AssignmentFileRef | None = None
    flow: RuntimeFlowRead
    workflow_manifest_ref: WorkflowManifestRef | None = None
    latest_checkpoint_ref: CheckpointFileRef | None = None


class ParentToolMutationSuccess(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: RuntimeSchemaText | None = None
    target_node_key: RuntimeSchemaText | None = None
    flow: RuntimeFlowRead
    workflow_manifest_ref: WorkflowManifestRef | None = None
    latest_checkpoint_ref: CheckpointFileRef | None = None


class ReleaseGreenSuccess(ParentToolMutationSuccess):
    tool_name: Literal["release_green"] = "release_green"


class ReleaseBlockedSuccess(ParentToolMutationSuccess):
    tool_name: Literal["release_blocked"] = "release_blocked"


__all__ = [
    "AssignChildPayload",
    "AssignChildSuccess",
    "AssignmentIntent",
    "ParentToolMutationSuccess",
    "ReleaseBlockedPayload",
    "ReleaseBlockedSuccess",
    "ReleaseGreenPayload",
    "ReleaseGreenSuccess",
    "SupplementalDurableContext",
    "SupplementalSlot",
]
