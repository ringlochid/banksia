from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from banksia.workflows.contracts import (
    Identifier,
    NormalizedWorkflow,
    ProviderSandbox,
    PublishedWorkflowRevision,
    WorkflowProvenance,
    WorkflowRevisionSummary,
)
from banksia.workflows.errors import WorkflowValidationIssue
from banksia.workflows.operations import NewMember


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


class CreateWorkflowDraftRequest(_AuthoringModel):
    kind: Literal["create"]
    workflow_id: Identifier
    description: Annotated[str, Field(min_length=1, max_length=1024, pattern=r"\S")]
    note: Annotated[str, Field(max_length=8192)] | None = None
    lead: NewMember | None = None


class OpenWorkflowDraftRequest(_AuthoringModel):
    kind: Literal["open"]
    workflow_id: Identifier


WorkflowDraftOpenRequest = Annotated[
    CreateWorkflowDraftRequest | OpenWorkflowDraftRequest,
    Field(discriminator="kind"),
]
WORKFLOW_DRAFT_OPEN_REQUEST_ADAPTER: TypeAdapter[WorkflowDraftOpenRequest] = TypeAdapter(
    WorkflowDraftOpenRequest
)


class WorkflowDraftOpenResult(_AuthoringModel):
    draft: WorkflowDraftReadback
    is_created: bool


class WorkflowDraftValidationResult(_AuthoringModel):
    is_valid: bool
    issues: tuple[WorkflowValidationIssue, ...] = ()
    draft: WorkflowDraftReadback


class WorkflowDefaultProviderReadback(_AuthoringModel):
    kind: Literal["codex", "claude", "openclaw"]
    model: str | None = None
    effort: str | None = None
    sandbox: ProviderSandbox | None = None


class WorkflowAuthoringOptions(_AuthoringModel):
    workflow_fields: tuple[str, ...]
    member_fields: tuple[str, ...]
    provider_kinds: tuple[str, ...]
    codex_efforts: tuple[str, ...]
    claude_efforts: tuple[str, ...]
    managed_sandbox_options: tuple[ProviderSandbox, ...]
    human_request_kinds: tuple[str, ...]
    command_run_values: tuple[str, ...]
    default_provider: WorkflowDefaultProviderReadback | None = None


class WorkflowLibraryState(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    PUBLISHED_WITH_DRAFT = "published_with_draft"


class WorkflowLibraryAction(StrEnum):
    EDIT = "edit"
    START_RUN = "start_run"
    REMOVE = "remove"


class WorkflowSearchItem(_AuthoringModel):
    workflow_id: Identifier
    description: str
    state: WorkflowLibraryState
    updated_at: datetime
    provenance: WorkflowProvenance
    published_revision_no: Annotated[int, Field(ge=1)] | None = None
    available_actions: tuple[WorkflowLibraryAction, ...]


class WorkflowSearchResponse(_AuthoringModel):
    items: tuple[WorkflowSearchItem, ...]
    next_cursor: str | None = None


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
    description: str
    state: WorkflowLibraryState
    updated_at: datetime
    provenance: WorkflowProvenance
    published_revision_no: Annotated[int, Field(ge=1)] | None = None
    available_actions: tuple[WorkflowLibraryAction, ...]
    published: WorkflowPublishedReadback | None = None
    revisions: tuple[WorkflowRevisionReadback, ...] = ()
    revisions_next_cursor: str | None = None
    active_draft: WorkflowDraftReadback | None = None

    @model_validator(mode="after")
    def require_controller_truth(self) -> WorkflowGetResponse:
        if self.published is None and self.active_draft is None:
            raise ValueError("Workflow detail requires published truth or an active draft")
        has_published_workflow = self.published_revision_no is not None
        has_active_draft = self.active_draft is not None
        expected_state = (
            WorkflowLibraryState.PUBLISHED_WITH_DRAFT
            if has_published_workflow and has_active_draft
            else (
                WorkflowLibraryState.PUBLISHED
                if has_published_workflow
                else WorkflowLibraryState.DRAFT
            )
        )
        if self.state is not expected_state:
            raise ValueError("Workflow detail state contradicts controller truth")
        if (self.published is not None) is not has_published_workflow:
            raise ValueError("Workflow detail publication contradicts its current revision")
        expected_actions = (
            (
                WorkflowLibraryAction.EDIT,
                WorkflowLibraryAction.START_RUN,
                WorkflowLibraryAction.REMOVE,
            )
            if has_published_workflow
            else (WorkflowLibraryAction.EDIT, WorkflowLibraryAction.REMOVE)
        )
        if self.available_actions != expected_actions:
            raise ValueError("Workflow detail actions contradict its current publication")
        if self.published is not None and self.published.workflow_id != self.workflow_id:
            raise ValueError("Workflow detail selected publication has the wrong identity")
        if self.active_draft is not None:
            if self.active_draft.workflow_id != self.workflow_id:
                raise ValueError("Workflow detail active draft has the wrong identity")
            if self.active_draft.workflow.description != self.description:
                raise ValueError("Workflow detail description contradicts its active draft")
        elif (
            self.published is not None
            and self.published.revision_no == self.published_revision_no
            and self.published.workflow.description != self.description
        ):
            raise ValueError("Workflow detail description contradicts its current publication")
        if not has_published_workflow:
            if self.provenance is not WorkflowProvenance.USER:
                raise ValueError("A draft-only Workflow must have user provenance")
            if self.revisions or self.revisions_next_cursor is not None:
                raise ValueError("A draft-only Workflow cannot expose publication history")
        return self


class WorkflowDraftDiscardResult(_AuthoringModel):
    is_discarded: bool
    draft_id: str


class WorkflowRemovalResult(_AuthoringModel):
    is_removed: bool
    workflow_id: Identifier


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
    "WORKFLOW_DRAFT_OPEN_REQUEST_ADAPTER",
    "CreateWorkflowDraftRequest",
    "OpenWorkflowDraftRequest",
    "WorkflowAuthoringOptions",
    "WorkflowDefaultProviderReadback",
    "WorkflowDraftDiscardResult",
    "WorkflowDraftImportResult",
    "WorkflowDraftMutationResult",
    "WorkflowDraftOpenRequest",
    "WorkflowDraftOpenResult",
    "WorkflowDraftReadback",
    "WorkflowDraftValidationResult",
    "WorkflowGetResponse",
    "WorkflowLibraryAction",
    "WorkflowLibraryState",
    "WorkflowPublishedReadback",
    "WorkflowRemovalResult",
    "WorkflowRevisionReadback",
    "WorkflowSearchItem",
    "WorkflowSearchResponse",
    "map_workflow_published_readback",
    "map_workflow_revision_readback",
]
