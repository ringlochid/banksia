from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    model_validator,
)

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
WorkflowIdentifier = NonEmptyText
SlotIdentifier = NonEmptyText


class NodeKind(StrEnum):
    ROOT = "root"
    PARENT = "parent"
    WORKER = "worker"


class ProviderKind(StrEnum):
    OPENCLAW = "openclaw"
    CODEX = "codex"
    CLAUDE = "claude"


class CodexProviderSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[ProviderKind.CODEX]


class ClaudeProviderSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[ProviderKind.CLAUDE]


class OpenClawProviderSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[ProviderKind.OPENCLAW]


type ProviderSelection = Annotated[
    CodexProviderSelection | ClaudeProviderSelection | OpenClawProviderSelection,
    Field(discriminator="kind"),
]


class ConsumeSelector(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    slot: SlotIdentifier
    is_required: bool = Field(default=True, alias="required")

    @property
    def required(self) -> bool:
        return self.is_required


class ConsumeBuckets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifacts: list[ConsumeSelector] | None = None
    criteria: list[ConsumeSelector] | None = None


class ProduceSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: SlotIdentifier
    description: NonEmptyText
    file_hint: NonEmptyText | None = None


class ProduceBuckets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifacts: list[ProduceSlot] | None = None


class CriteriaDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: SlotIdentifier
    description: NonEmptyText
    criteria: list[NonEmptyText] = Field(min_length=1)


class ChildDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consumes: ConsumeBuckets | None = None
    criteria: list[SlotIdentifier] | None = None


class WorkflowNodeInput[NodeKindT: NodeKind](BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_key: WorkflowIdentifier
    kind: NodeKindT
    title: NonEmptyText | None = None
    role_id: WorkflowIdentifier
    policy_id: WorkflowIdentifier
    provider: ProviderSelection | None = None
    description: NonEmptyText
    instruction: NonEmptyText | None = None


class NodeDefinitionInput(WorkflowNodeInput[Literal[NodeKind.PARENT, NodeKind.WORKER]]):
    consumes: ConsumeBuckets | None = None
    produces: ProduceBuckets | None = None
    criteria: list[CriteriaDeclaration] | None = None
    child_defaults: ChildDefaults | None = None
    children: list[NodeDefinitionInput] | None = None

    @model_validator(mode="after")
    def validate_structural_kind(self) -> Self:
        if self.kind == NodeKind.WORKER and self.children:
            raise ValueError("worker workflow nodes must not contain children")
        return self


class RootNodeDefinition(WorkflowNodeInput[Literal[NodeKind.ROOT]]):
    produces: ProduceBuckets | None = None
    criteria: list[CriteriaDeclaration] | None = None
    child_defaults: ChildDefaults | None = None
    children: list[NodeDefinitionInput] | None = None


type WorkflowNode = RootNodeDefinition | NodeDefinitionInput


class WorkflowDefinitionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: WorkflowIdentifier
    description: NonEmptyText
    root: RootNodeDefinition

    @model_validator(mode="after")
    def validate_workflow(self, info: ValidationInfo) -> Self:
        from autoclaw.definitions.contracts.validation import validate_workflow_definition

        return validate_workflow_definition(self, info)


class WorkflowDefinitionFile(WorkflowDefinitionInput):
    kind: Literal["workflow"]


NodeDefinitionInput.model_rebuild()

__all__ = [
    "ChildDefaults",
    "ClaudeProviderSelection",
    "CodexProviderSelection",
    "ConsumeBuckets",
    "ConsumeSelector",
    "CriteriaDeclaration",
    "NodeDefinitionInput",
    "NodeKind",
    "NonEmptyText",
    "OpenClawProviderSelection",
    "ProduceBuckets",
    "ProduceSlot",
    "ProviderKind",
    "ProviderSelection",
    "RootNodeDefinition",
    "SlotIdentifier",
    "WorkflowDefinitionFile",
    "WorkflowDefinitionInput",
    "WorkflowIdentifier",
    "WorkflowNode",
    "WorkflowNodeInput",
]
