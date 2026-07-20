from typing import Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from autoclaw.definitions.contracts.workflow import (
    ChildDefaults,
    ConsumeBuckets,
    CriteriaDeclaration,
    ProduceBuckets,
    ProviderSelection,
)
from autoclaw.runtime.contracts.checkpoint import TransientSurfaceWrite
from autoclaw.runtime.contracts.common import RuntimeSchemaText
from autoclaw.runtime.contracts.flow import RuntimeFlowRead
from autoclaw.runtime.contracts.refs import (
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


class ChildNodeDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_key: RuntimeSchemaText = Field(validation_alias=AliasChoices("node_key", "id"))
    parent_node_key: RuntimeSchemaText | None = Field(default=None, exclude=True)
    role: RuntimeSchemaText
    policy: RuntimeSchemaText
    provider: ProviderSelection | None = None
    description: RuntimeSchemaText
    instruction: RuntimeSchemaText | None = None
    consumes: ConsumeBuckets | None = None
    produces: ProduceBuckets | None = None
    criteria: list[CriteriaDeclaration] | None = None
    child_defaults: ChildDefaults | None = None
    children: list["ChildNodeDraft"] | None = None


class ChildNodePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: RuntimeSchemaText | None = None
    policy: RuntimeSchemaText | None = None
    provider: ProviderSelection | None = None
    description: RuntimeSchemaText | None = None
    instruction: RuntimeSchemaText | None = None
    consumes: ConsumeBuckets | None = None
    produces: ProduceBuckets | None = None
    criteria: list[CriteriaDeclaration] | None = None
    child_defaults: ChildDefaults | None = None
    children: list[ChildNodeDraft] | None = None

    @model_validator(mode="after")
    def validate_patch_shape(self) -> "ChildNodePatch":
        if self.children is not None:
            raise ValueError("update_child does not support subtree patch shapes")
        if "policy" in self.model_fields_set and self.policy is None:
            raise ValueError("update_child cannot clear the node policy")
        return self


class AddChildPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child: ChildNodeDraft
    target_parent_node_key: RuntimeSchemaText | None = Field(
        default=None,
        validation_alias=AliasChoices("target_parent_node_key", "parent_node_key"),
    )

    @model_validator(mode="after")
    def bind_target_parent(self) -> "AddChildPayload":
        if self.target_parent_node_key is not None:
            self.child = self.child.model_copy(
                update={"parent_node_key": self.target_parent_node_key}
            )
        return self


class UpdateChildPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_node_key: RuntimeSchemaText
    patch: ChildNodePatch


class RemoveChildPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_node_key: RuntimeSchemaText


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


class AddChildSuccess(ParentToolMutationSuccess):
    tool_name: Literal["add_child"] = "add_child"


class UpdateChildSuccess(ParentToolMutationSuccess):
    tool_name: Literal["update_child"] = "update_child"


class RemoveChildSuccess(ParentToolMutationSuccess):
    tool_name: Literal["remove_child"] = "remove_child"


class ReleaseGreenSuccess(ParentToolMutationSuccess):
    tool_name: Literal["release_green"] = "release_green"


class ReleaseBlockedSuccess(ParentToolMutationSuccess):
    tool_name: Literal["release_blocked"] = "release_blocked"


ChildNodeDraft.model_rebuild()

__all__ = [
    "AddChildPayload",
    "AddChildSuccess",
    "AssignChildPayload",
    "AssignChildSuccess",
    "AssignmentIntent",
    "ChildNodeDraft",
    "ChildNodePatch",
    "ParentToolMutationSuccess",
    "ReleaseBlockedPayload",
    "ReleaseBlockedSuccess",
    "ReleaseGreenPayload",
    "ReleaseGreenSuccess",
    "RemoveChildPayload",
    "RemoveChildSuccess",
    "SupplementalDurableContext",
    "SupplementalSlot",
    "UpdateChildPayload",
    "UpdateChildSuccess",
]
