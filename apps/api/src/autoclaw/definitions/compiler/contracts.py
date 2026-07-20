from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from autoclaw.definitions.contracts.workflow import NodeKind, ProviderSelection

CompilerText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class DependencyKind(StrEnum):
    ARTIFACT = "artifact"
    CRITERIA = "criteria"


class WorkflowRevisionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    workflow_key: CompilerText
    definition_revision_no: int = Field(ge=1)


class NormalizedConsumeSelector(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        from_attributes=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    slot: CompilerText
    is_required: bool = Field(default=True, alias="required")

    @property
    def required(self) -> bool:
        return self.is_required


class NormalizedConsumeBuckets(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    artifacts: tuple[NormalizedConsumeSelector, ...] = ()
    criteria: tuple[NormalizedConsumeSelector, ...] = ()


class NormalizedProduceSlot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    slot: CompilerText
    description: CompilerText
    file_hint: CompilerText | None = None


class NormalizedProduceBuckets(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    artifacts: tuple[NormalizedProduceSlot, ...] = ()


class NormalizedCriteriaDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    owner_node_key: CompilerText
    slot: CompilerText
    description: CompilerText
    criteria: tuple[CompilerText, ...]


class NormalizedChildDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    consumes: NormalizedConsumeBuckets | None = None
    criteria: tuple[CompilerText, ...] = ()


class NormalizedDependencyEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    consumer_node_key: CompilerText
    provider_node_key: CompilerText
    kind: DependencyKind
    slot: CompilerText
    description: CompilerText
    order_index: int = Field(ge=0)


class NormalizedCompiledNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    node_key: CompilerText
    parent_node_key: CompilerText | None = None
    child_node_keys: tuple[CompilerText, ...] = ()
    structural_kind: NodeKind
    role: CompilerText
    role_revision_no: int = Field(ge=1)
    policy: CompilerText
    policy_revision_no: int = Field(ge=1)
    provider: ProviderSelection | None = None
    description: CompilerText
    node_instruction: CompilerText | None = None
    consumes: NormalizedConsumeBuckets | None = None
    produces: NormalizedProduceBuckets | None = None
    criteria: tuple[NormalizedCriteriaDeclaration, ...] = ()
    child_defaults: NormalizedChildDefaults | None = None
    order_index: int = Field(ge=0)


class NormalizedCompiledPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    workflow_key: CompilerText
    definition_revision_no: int = Field(ge=1)
    compiler_version: CompilerText
    nodes: tuple[NormalizedCompiledNode, ...]
    dependency_edges: tuple[NormalizedDependencyEdge, ...]
