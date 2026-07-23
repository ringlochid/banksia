from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from banksia.workflows.contracts import (
    Identifier,
    NormalizedWorkflow,
    ProviderSandbox,
    PublishedWorkflowRevision,
    WorkflowProvenance,
    WorkflowRevisionSummary,
)
from banksia.workflows.errors import WorkflowValidationIssue


class _AuthoringModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WorkflowDraftReadback(_AuthoringModel):
    draft_id: str
    workflow_id: Identifier
    base_revision_no: Annotated[int, Field(ge=1)] | None = None
    etag: str
    workflow: NormalizedWorkflow


class WorkflowDraftMutationResult(_AuthoringModel):
    draft: WorkflowDraftReadback
    undo_receipt: str


class WorkflowDraftImportResult(_AuthoringModel):
    draft: WorkflowDraftReadback
    is_created: bool
    undo_receipt: str | None = None


class WorkflowDraftValidationResult(_AuthoringModel):
    is_valid: bool
    issues: tuple[WorkflowValidationIssue, ...] = ()
    draft: WorkflowDraftReadback


class WorkflowAuthoringOptions(_AuthoringModel):
    workflow_fields: tuple[str, ...]
    member_fields: tuple[str, ...]
    provider_kinds: tuple[str, ...]
    codex_efforts: tuple[str, ...]
    claude_efforts: tuple[str, ...]
    managed_sandbox_options: tuple[ProviderSandbox, ...]
    human_request_kinds: tuple[str, ...]
    command_run_values: tuple[str, ...]


class WorkflowSearchItem(_AuthoringModel):
    workflow_id: Identifier
    description: str
    published_revision_no: Annotated[int, Field(ge=1)] | None = None
    provenance: WorkflowProvenance | None = None
    draft_id: str | None = None
    draft_etag: str | None = None


class WorkflowSearchResponse(_AuthoringModel):
    items: tuple[WorkflowSearchItem, ...]


class WorkflowPublishedReadback(_AuthoringModel):
    workflow_id: Identifier
    revision_no: Annotated[int, Field(ge=1)]
    workflow: NormalizedWorkflow


class WorkflowRevisionReadback(_AuthoringModel):
    workflow_id: Identifier
    revision_no: Annotated[int, Field(ge=1)]
    provenance: WorkflowProvenance


class WorkflowGetResponse(_AuthoringModel):
    workflow_id: Identifier
    published: WorkflowPublishedReadback | None = None
    revisions: tuple[WorkflowRevisionReadback, ...] = ()
    active_draft: WorkflowDraftReadback | None = None


class WorkflowDraftDiscardResult(_AuthoringModel):
    is_discarded: bool
    draft_id: str


AUTHORING_OPTIONS = WorkflowAuthoringOptions(
    workflow_fields=("description", "note"),
    member_fields=("title", "description", "instruction", "provider", "capabilities"),
    provider_kinds=("codex", "claude", "openclaw"),
    codex_efforts=("none", "minimal", "low", "medium", "high", "xhigh"),
    claude_efforts=("low", "medium", "high", "xhigh", "max"),
    managed_sandbox_options=(
        ProviderSandbox(mode="read_only", network="deny"),
        ProviderSandbox(mode="workspace_write", network="deny"),
        ProviderSandbox(mode="workspace_write", network="allow"),
        ProviderSandbox(mode="full_access", network="allow"),
    ),
    human_request_kinds=("input", "direction", "approval", "review"),
    command_run_values=("allow",),
)


def map_workflow_published_readback(
    revision: PublishedWorkflowRevision,
) -> WorkflowPublishedReadback:
    return WorkflowPublishedReadback(
        workflow_id=revision.workflow_id,
        revision_no=revision.revision_no,
        workflow=revision.workflow,
    )


def map_workflow_revision_readback(
    revision: WorkflowRevisionSummary,
) -> WorkflowRevisionReadback:
    return WorkflowRevisionReadback(
        workflow_id=revision.workflow_id,
        revision_no=revision.revision_no,
        provenance=revision.provenance,
    )


__all__ = [
    "AUTHORING_OPTIONS",
    "WorkflowAuthoringOptions",
    "WorkflowDraftDiscardResult",
    "WorkflowDraftImportResult",
    "WorkflowDraftMutationResult",
    "WorkflowDraftReadback",
    "WorkflowDraftValidationResult",
    "WorkflowGetResponse",
    "WorkflowPublishedReadback",
    "WorkflowRevisionReadback",
    "WorkflowSearchItem",
    "WorkflowSearchResponse",
    "map_workflow_published_readback",
    "map_workflow_revision_readback",
]
