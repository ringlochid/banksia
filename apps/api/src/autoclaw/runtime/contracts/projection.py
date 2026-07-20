from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from autoclaw.definitions.contracts.workflow import NodeKind
from autoclaw.runtime.contracts.primitives import (
    AssignmentConsumeRef,
    CheckpointKind,
    CheckpointOutcome,
    EvidenceKind,
    EvidenceRef,
    NodeRuntimeFileKind,
    RuntimeContextRef,
    RuntimeText,
    SlotIdentifier,
    TaskIdentifier,
)

type RequiredFlag = bool


class ManifestTaskProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: TaskIdentifier
    task_key: RuntimeText
    title: RuntimeText
    summary: RuntimeText
    instruction: RuntimeText | None = None


class ManifestWorkflowProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_key: RuntimeText
    description: RuntimeText


class ManifestFilesystemRootsProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_path: Path
    context_path: Path
    outputs_path: Path
    tmp_path: Path
    runtime_path: Path


class StructuralEditRoleProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: RuntimeText
    allowed_node_kinds: tuple[NodeKind, ...]
    description: RuntimeText


class StructuralEditPolicyProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy: RuntimeText
    applies_to: tuple[NodeKind, ...]
    description: RuntimeText


class StructuralEditPaletteProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    roles: tuple[StructuralEditRoleProjection, ...] = ()
    policies: tuple[StructuralEditPolicyProjection, ...] = ()


class ManifestNodeConsumeProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: EvidenceKind
    slot: SlotIdentifier
    description: RuntimeText
    required: RequiredFlag = Field(default=True)

    @model_validator(mode="after")
    def validate_kind(self) -> ManifestNodeConsumeProjection:
        if self.kind not in {EvidenceKind.ARTIFACT, EvidenceKind.CRITERIA}:
            raise ValueError("manifest node consumes support artifact or criteria only")
        return self


class ManifestNodeProduceProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    slot: SlotIdentifier
    description: RuntimeText
    file_hint: RuntimeText | None = None


class ManifestNodeCriteriaProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    owner_node_key: RuntimeText
    slot: SlotIdentifier
    description: RuntimeText
    path: Path


class ManifestNodeProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_key: RuntimeText
    parent_node_key: RuntimeText | None = None
    child_node_keys: tuple[RuntimeText, ...] = ()
    node_kind: NodeKind
    role: RuntimeText
    policy: RuntimeText | None = None
    description: RuntimeText
    node_instruction: RuntimeText | None = None
    consumes: tuple[ManifestNodeConsumeProjection, ...] = ()
    produces: tuple[ManifestNodeProduceProjection, ...] = ()
    criteria: tuple[ManifestNodeCriteriaProjection, ...] = ()
    depends_on_node_keys: tuple[RuntimeText, ...] = ()
    depended_on_by_node_keys: tuple[RuntimeText, ...] = ()


class ManifestDependencyProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_node_key: RuntimeText
    consumer_node_key: RuntimeText
    kind: RuntimeText
    slot: SlotIdentifier
    description: RuntimeText


class ManifestCurrentContextProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    current_node_key: RuntimeText
    owner_node_key: RuntimeText
    active_attempt_id: RuntimeText
    active_assignment_path: Path
    latest_checkpoint_path: Path | None = None
    latest_relevant_checkpoint_path: Path | None = None
    current_relevant_paths: tuple[RuntimeContextRef, ...] = ()


class ManifestProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_version: int = 1
    active_flow_revision_id: RuntimeText
    generated_at: datetime
    task: ManifestTaskProjection
    workflow: ManifestWorkflowProjection
    filesystem_roots: ManifestFilesystemRootsProjection
    structural_edit_palette: StructuralEditPaletteProjection | None = None
    current_context: ManifestCurrentContextProjection
    node_tree: tuple[ManifestNodeProjection, ...]
    dependency_index: tuple[ManifestDependencyProjection, ...]


class ProduceRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    slot: SlotIdentifier
    description: RuntimeText
    file_hint: RuntimeText | None = None


class AssignmentProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    assignment_key: RuntimeText
    node_key: RuntimeText
    summary: RuntimeText
    instruction: RuntimeText | None = None
    criteria: tuple[EvidenceRef, ...] = ()
    consumes: tuple[AssignmentConsumeRef, ...] = ()
    produces: tuple[ProduceRequirement, ...] = ()
    transient_refs: tuple[EvidenceRef, ...] = ()

    @model_validator(mode="after")
    def validate_refs(self) -> AssignmentProjection:
        if any(ref.kind != EvidenceKind.CRITERIA for ref in self.criteria):
            raise ValueError("assignment criteria must use criteria refs")
        for ref in self.consumes:
            if isinstance(ref, EvidenceRef):
                if ref.kind in {EvidenceKind.TRANSIENT, EvidenceKind.CRITERIA}:
                    raise ValueError("assignment consumes must not use transient or criteria refs")
                continue
            if ref.kind != NodeRuntimeFileKind.CHECKPOINT:
                raise ValueError("assignment consumes support checkpoint runtime refs only")
        if any(ref.kind != EvidenceKind.TRANSIENT for ref in self.transient_refs):
            raise ValueError("assignment transient_refs must use transient refs")
        return self


class CheckpointHandoff(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: RuntimeText
    next_step: RuntimeText
    blockers: tuple[RuntimeText, ...] = ()
    risks: tuple[RuntimeText, ...] = ()


class CheckpointProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    checkpoint_kind: CheckpointKind
    outcome: CheckpointOutcome | None = None
    handoff: CheckpointHandoff
    produced_artifacts: tuple[EvidenceRef, ...] = ()
    transient_refs: tuple[EvidenceRef, ...] = ()

    @model_validator(mode="after")
    def validate_projection(self) -> CheckpointProjection:
        if self.checkpoint_kind == CheckpointKind.PROGRESS and self.outcome is not None:
            raise ValueError("progress checkpoints must not set outcome")
        if self.checkpoint_kind == CheckpointKind.TERMINAL and self.outcome is None:
            raise ValueError("terminal checkpoints require outcome")
        if any(ref.kind != EvidenceKind.ARTIFACT for ref in self.produced_artifacts):
            raise ValueError("checkpoint produced_artifacts must use artifact refs")
        if any(ref.kind != EvidenceKind.TRANSIENT for ref in self.transient_refs):
            raise ValueError("checkpoint transient_refs must use transient refs")
        return self


class ResolvedNodeContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_key: RuntimeText
    node_kind: NodeKind
    node_description: RuntimeText
    node_instruction: RuntimeText | None = None
    role_key: RuntimeText
    role_revision_no: int = Field(ge=1)
    role_description: RuntimeText
    role_instruction: RuntimeText | None = None
    policy_key: RuntimeText
    policy_revision_no: int = Field(ge=1)
    policy_description: RuntimeText
    policy_instruction: RuntimeText | None = None


__all__ = [
    "AssignmentProjection",
    "CheckpointHandoff",
    "CheckpointProjection",
    "ManifestCurrentContextProjection",
    "ManifestDependencyProjection",
    "ManifestFilesystemRootsProjection",
    "ManifestNodeConsumeProjection",
    "ManifestNodeCriteriaProjection",
    "ManifestNodeProduceProjection",
    "ManifestNodeProjection",
    "ManifestProjection",
    "ManifestTaskProjection",
    "ManifestWorkflowProjection",
    "ProduceRequirement",
    "ResolvedNodeContext",
    "StructuralEditPaletteProjection",
    "StructuralEditPolicyProjection",
    "StructuralEditRoleProjection",
]
