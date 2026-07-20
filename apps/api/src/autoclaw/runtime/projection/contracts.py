from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WorkflowManifestTask(ProjectionModel):
    task_id: str
    task_key: str
    title: str
    summary: str


class CriteriaReadback(ProjectionModel):
    flow_revision_id: str
    owner_node_key: str
    slot: str
    version: int = Field(ge=1)
    description: str
    criteria: tuple[str, ...]
    logical_path: str


class WorkflowManifestNode(ProjectionModel):
    node_key: str
    parent_node_key: str | None
    child_node_keys: tuple[str, ...]
    node_kind: str
    role_key: str
    role_revision_no: int = Field(ge=1)
    policy_key: str
    policy_revision_no: int = Field(ge=1)
    description: str
    node_instruction: str | None
    consumes: dict[str, object] | None
    produces: dict[str, object] | None
    criteria: tuple[CriteriaReadback, ...]


class WorkflowManifestEdge(ProjectionModel):
    provider_node_key: str
    consumer_node_key: str
    kind: str
    slot: str
    description: str


class WorkflowManifestReadback(ProjectionModel):
    manifest_version: int = 2
    flow_id: str
    active_flow_revision_id: str
    workflow_key: str | None
    task: WorkflowManifestTask
    nodes: tuple[WorkflowManifestNode, ...]
    edges: tuple[WorkflowManifestEdge, ...]


class AssignmentCriteriaReadback(ProjectionModel):
    slot: str
    version: int | None
    logical_path: str
    description: str


class AttemptAssignmentReadback(ProjectionModel):
    assignment_id: str
    attempt_id: str
    flow_revision_id: str
    assignment_key: str
    node_key: str
    parent_assignment_id: str | None
    retry_of_attempt_id: str | None
    summary: str
    instruction: str | None
    criteria: tuple[AssignmentCriteriaReadback, ...]
    consumes: tuple[dict[str, object], ...]
    produces: tuple[dict[str, object], ...]


class ProjectionRef(ProjectionModel):
    source_id: str
    logical_path: str
    description: str
    slot: str | None = None
    version: int | None = None


class LatestCheckpointReadback(ProjectionModel):
    checkpoint_id: str
    task_id: str
    flow_id: str
    assignment_id: str
    attempt_id: str
    authoring_dispatch_id: str
    checkpoint_kind: str
    outcome: str | None
    summary: str
    evidence: dict[str, object]
    criteria_results: tuple[dict[str, object], ...]
    artifacts: tuple[ProjectionRef, ...]
    transients: tuple[ProjectionRef, ...]
    recorded_at: datetime


class ArtifactIndexEntry(ProjectionModel):
    artifact_publication_id: str
    checkpoint_id: str
    slot: str
    version: int = Field(ge=1)
    logical_path: str
    description: str
    supersedes_publication_id: str | None
    supersedes_version: int | None
    is_current: bool
    published_at: datetime


class ArtifactIndexReadback(ProjectionModel):
    task_id: str
    assignment_id: str
    attempt_id: str
    publications: tuple[ArtifactIndexEntry, ...]


class TransientIndexEntry(ProjectionModel):
    transient_localization_id: str
    checkpoint_id: str | None
    source_logical_path: str
    localized_logical_path: str
    description: str
    retention_status: str
    localized_at: datetime
    expires_at: datetime | None
    removed_at: datetime | None


class TransientIndexReadback(ProjectionModel):
    task_id: str
    assignment_id: str
    attempt_id: str
    localizations: tuple[TransientIndexEntry, ...]


__all__ = [
    "ArtifactIndexEntry",
    "ArtifactIndexReadback",
    "AssignmentCriteriaReadback",
    "AttemptAssignmentReadback",
    "CriteriaReadback",
    "LatestCheckpointReadback",
    "ProjectionRef",
    "TransientIndexEntry",
    "TransientIndexReadback",
    "WorkflowManifestEdge",
    "WorkflowManifestNode",
    "WorkflowManifestReadback",
    "WorkflowManifestTask",
]
