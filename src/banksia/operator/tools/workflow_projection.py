from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from banksia.workflows.authoring_contracts import (
    WorkflowDraftImportResult,
    WorkflowDraftMutationResult,
    WorkflowDraftReadback,
    WorkflowDraftValidationResult,
    WorkflowLibraryAction,
    WorkflowLibraryState,
)
from banksia.workflows.catalog import (
    WorkflowCatalogSnapshot,
    WorkflowRevisionSummaryPage,
)
from banksia.workflows.contracts import (
    Identifier,
    MemberCapabilities,
    NormalizedMember,
    NormalizedWorkflow,
    PublishedWorkflowRevision,
    StoredProviderSelection,
    WorkflowProvenance,
)
from banksia.workflows.errors import WorkflowValidationIssue
from banksia.workflows.library import (
    derive_workflow_library_actions,
    derive_workflow_library_state,
)
from banksia.workflows.operations import (
    AddMemberOperation,
    DraftOperation,
    RemoveMemberOperation,
    UpdateMemberOperation,
    UpdateWorkflowOperation,
)
from banksia.workflows.service_errors import WorkflowNotFoundError


class _WorkflowProjectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OperatorPublishedWorkflowSource(_WorkflowProjectionModel):
    kind: Literal["published"] = "published"
    workflow_id: Identifier
    revision_no: Annotated[int, Field(ge=1)]


class OperatorWorkflowDraftReference(_WorkflowProjectionModel):
    kind: Literal["draft"] = "draft"
    workflow_id: Identifier
    draft_id: str
    base_revision_no: Annotated[int, Field(ge=1)] | None = None
    etag: str


type OperatorWorkflowSource = Annotated[
    OperatorPublishedWorkflowSource | OperatorWorkflowDraftReference,
    Field(discriminator="kind"),
]


class OperatorWorkflowRevisionReference(_WorkflowProjectionModel):
    source: OperatorPublishedWorkflowSource
    provenance: WorkflowProvenance


class OperatorWorkflowCatalogResult(_WorkflowProjectionModel):
    kind: Literal["workflow_catalog"] = "workflow_catalog"
    workflow_id: Identifier
    description: str
    state: WorkflowLibraryState
    updated_at: datetime
    provenance: WorkflowProvenance
    available_actions: tuple[WorkflowLibraryAction, ...]
    published: OperatorPublishedWorkflowSource | None = None
    active_draft: OperatorWorkflowDraftReference | None = None
    revisions: tuple[OperatorWorkflowRevisionReference, ...] = ()
    revisions_next_cursor: str | None = None

    @model_validator(mode="after")
    def require_source_identity(self) -> OperatorWorkflowCatalogResult:
        sources = (
            *((self.published,) if self.published is not None else ()),
            *((self.active_draft,) if self.active_draft is not None else ()),
            *(revision.source for revision in self.revisions),
        )
        if any(source.workflow_id != self.workflow_id for source in sources):
            raise ValueError("Workflow catalog source has the wrong identity")
        return self


class OperatorWorkflowIdentity(_WorkflowProjectionModel):
    kind: Literal["workflow"] = "workflow"
    id: Identifier
    description: str
    note: str | None = None
    lead_member_id: Identifier


class OperatorWorkflowMember(_WorkflowProjectionModel):
    id: Identifier
    title: str | None = None
    description: str | None = None
    instruction: str | None = None
    provider: StoredProviderSelection | None = None
    capabilities: MemberCapabilities | None = None
    child_ids: tuple[Identifier, ...] | None = None


class OperatorWorkflowMemberResult(_WorkflowProjectionModel):
    kind: Literal["workflow_member"] = "workflow_member"
    source: OperatorWorkflowSource
    workflow: OperatorWorkflowIdentity
    member: OperatorWorkflowMember

    @model_validator(mode="after")
    def require_source_identity(self) -> OperatorWorkflowMemberResult:
        if self.source.workflow_id != self.workflow.id:
            raise ValueError("Workflow source and authored content identities disagree")
        return self


class OperatorWorkflowDraftCreateReceipt(_WorkflowProjectionModel):
    draft: OperatorWorkflowDraftReference
    is_created: bool
    undo_receipt: str | None = None


class OperatorWorkflowUpdated(_WorkflowProjectionModel):
    kind: Literal["workflow_updated"] = "workflow_updated"


class OperatorWorkflowMemberAdded(_WorkflowProjectionModel):
    kind: Literal["member_added"] = "member_added"
    parent_member_id: Identifier
    member_id: Identifier


class OperatorWorkflowMemberUpdated(_WorkflowProjectionModel):
    kind: Literal["member_updated"] = "member_updated"
    member_id: Identifier


class OperatorWorkflowMemberRemoved(_WorkflowProjectionModel):
    kind: Literal["member_removed"] = "member_removed"
    member_id: Identifier


type OperatorWorkflowAcceptedChange = Annotated[
    OperatorWorkflowUpdated
    | OperatorWorkflowMemberAdded
    | OperatorWorkflowMemberUpdated
    | OperatorWorkflowMemberRemoved,
    Field(discriminator="kind"),
]


class OperatorWorkflowDraftEditReceipt(_WorkflowProjectionModel):
    draft: OperatorWorkflowDraftReference
    undo_receipt: str
    accepted_change: OperatorWorkflowAcceptedChange


class OperatorWorkflowDraftValidationReceipt(_WorkflowProjectionModel):
    draft: OperatorWorkflowDraftReference
    is_valid: bool
    issues: tuple[WorkflowValidationIssue, ...] = ()


class OperatorWorkflowDraftUndoReceipt(_WorkflowProjectionModel):
    draft: OperatorWorkflowDraftReference
    consumed_receipt_id: str


class OperatorWorkflowDraftDiscardReceipt(_WorkflowProjectionModel):
    is_discarded: bool
    draft_id: str


class OperatorWorkflowPublishedReceipt(_WorkflowProjectionModel):
    workflow_id: Identifier
    revision_no: Annotated[int, Field(ge=1)]


class OperatorWorkflowDraftStaleError(ValueError):
    """A compact stale-draft failure with no authored Workflow body."""

    def __init__(self, draft: OperatorWorkflowDraftReference) -> None:
        self.draft = draft
        super().__init__("draft precondition is stale")


def map_operator_workflow_catalog_result(
    snapshot: WorkflowCatalogSnapshot,
    *,
    revision_page: WorkflowRevisionSummaryPage | None,
    revisions_next_cursor: str | None,
) -> OperatorWorkflowCatalogResult:
    summary = snapshot.summary
    has_published_workflow = summary.published_revision_no is not None
    return OperatorWorkflowCatalogResult(
        workflow_id=summary.workflow_id,
        description=summary.description,
        state=derive_workflow_library_state(
            has_active_draft=summary.has_active_draft,
            has_published_workflow=has_published_workflow,
        ),
        updated_at=summary.updated_at,
        provenance=summary.provenance,
        available_actions=tuple(
            action
            for action in derive_workflow_library_actions(
                has_published_workflow=has_published_workflow,
                has_retired_provider_selection=summary.has_retired_provider_selection,
            )
            if action is not WorkflowLibraryAction.REMOVE
        ),
        published=(
            OperatorPublishedWorkflowSource(
                workflow_id=summary.workflow_id,
                revision_no=summary.published_revision_no,
            )
            if summary.published_revision_no is not None
            else None
        ),
        active_draft=(
            OperatorWorkflowDraftReference(
                workflow_id=snapshot.active_draft.workflow_id,
                draft_id=snapshot.active_draft.draft_id,
                base_revision_no=snapshot.active_draft.base_revision_no,
                etag=snapshot.active_draft.etag,
            )
            if snapshot.active_draft is not None
            else None
        ),
        revisions=tuple(
            OperatorWorkflowRevisionReference(
                source=OperatorPublishedWorkflowSource(
                    workflow_id=revision.workflow_id,
                    revision_no=revision.revision_no,
                ),
                provenance=revision.provenance,
            )
            for revision in (revision_page.items if revision_page is not None else ())
        ),
        revisions_next_cursor=revisions_next_cursor,
    )


def build_operator_workflow_member_result(
    workflow: NormalizedWorkflow,
    *,
    source: OperatorWorkflowSource,
    member_id: str | None,
) -> OperatorWorkflowMemberResult:
    selected_member_id = member_id or workflow.lead.id
    selected_member = _find_workflow_member(workflow.lead, selected_member_id)
    if selected_member is None:
        raise WorkflowNotFoundError(
            f"Member {selected_member_id!r} does not exist in Workflow {workflow.id!r}"
        )
    return OperatorWorkflowMemberResult(
        source=source,
        workflow=OperatorWorkflowIdentity(
            id=workflow.id,
            description=workflow.description,
            note=workflow.note,
            lead_member_id=workflow.lead.id,
        ),
        member=OperatorWorkflowMember(
            id=selected_member.id,
            title=selected_member.title,
            description=selected_member.description,
            instruction=selected_member.instruction,
            provider=selected_member.provider,
            capabilities=selected_member.capabilities,
            child_ids=(
                tuple(child.id for child in selected_member.children)
                if selected_member.children is not None
                else None
            ),
        ),
    )


def map_operator_workflow_draft_create_receipt(
    result: WorkflowDraftImportResult,
) -> OperatorWorkflowDraftCreateReceipt:
    return OperatorWorkflowDraftCreateReceipt(
        draft=map_operator_workflow_draft_reference(result.draft),
        is_created=result.is_created,
        undo_receipt=result.undo_receipt,
    )


def map_operator_workflow_draft_edit_receipt(
    result: WorkflowDraftMutationResult,
    *,
    operation: DraftOperation,
) -> OperatorWorkflowDraftEditReceipt:
    return OperatorWorkflowDraftEditReceipt(
        draft=map_operator_workflow_draft_reference(result.draft),
        undo_receipt=result.undo_receipt,
        accepted_change=_map_accepted_workflow_change(
            result.draft.workflow,
            operation=operation,
        ),
    )


def map_operator_workflow_draft_validation_receipt(
    result: WorkflowDraftValidationResult,
) -> OperatorWorkflowDraftValidationReceipt:
    return OperatorWorkflowDraftValidationReceipt(
        draft=map_operator_workflow_draft_reference(result.draft),
        is_valid=result.is_valid,
        issues=result.issues,
    )


def map_operator_workflow_draft_undo_receipt(
    draft: WorkflowDraftReadback,
    *,
    consumed_receipt_id: str,
) -> OperatorWorkflowDraftUndoReceipt:
    return OperatorWorkflowDraftUndoReceipt(
        draft=map_operator_workflow_draft_reference(draft),
        consumed_receipt_id=consumed_receipt_id,
    )


def map_operator_workflow_published_receipt(
    revision: PublishedWorkflowRevision,
) -> OperatorWorkflowPublishedReceipt:
    return OperatorWorkflowPublishedReceipt(
        workflow_id=revision.workflow_id,
        revision_no=revision.revision_no,
    )


def map_operator_workflow_draft_reference(
    draft: WorkflowDraftReadback,
) -> OperatorWorkflowDraftReference:
    return OperatorWorkflowDraftReference(
        workflow_id=draft.workflow_id,
        draft_id=draft.draft_id,
        base_revision_no=draft.base_revision_no,
        etag=draft.etag,
    )


def _map_accepted_workflow_change(
    workflow: NormalizedWorkflow,
    *,
    operation: DraftOperation,
) -> OperatorWorkflowAcceptedChange:
    if isinstance(operation, UpdateWorkflowOperation):
        return OperatorWorkflowUpdated()
    if isinstance(operation, AddMemberOperation):
        parent = _find_workflow_member(workflow.lead, operation.parent_member_id)
        if parent is None or not parent.children:
            raise RuntimeError("accepted Member addition is missing from the draft")
        return OperatorWorkflowMemberAdded(
            parent_member_id=operation.parent_member_id,
            member_id=parent.children[-1].id,
        )
    if isinstance(operation, UpdateMemberOperation):
        return OperatorWorkflowMemberUpdated(member_id=operation.member_id)
    if isinstance(operation, RemoveMemberOperation):
        return OperatorWorkflowMemberRemoved(member_id=operation.member_id)
    raise TypeError("unknown accepted Workflow draft operation")


def _find_workflow_member(
    root: NormalizedMember,
    member_id: str,
) -> NormalizedMember | None:
    if root.id == member_id:
        return root
    for child in root.children or ():
        selected = _find_workflow_member(child, member_id)
        if selected is not None:
            return selected
    return None


__all__ = [
    "OperatorPublishedWorkflowSource",
    "OperatorWorkflowAcceptedChange",
    "OperatorWorkflowCatalogResult",
    "OperatorWorkflowDraftCreateReceipt",
    "OperatorWorkflowDraftDiscardReceipt",
    "OperatorWorkflowDraftEditReceipt",
    "OperatorWorkflowDraftReference",
    "OperatorWorkflowDraftStaleError",
    "OperatorWorkflowDraftUndoReceipt",
    "OperatorWorkflowDraftValidationReceipt",
    "OperatorWorkflowIdentity",
    "OperatorWorkflowMember",
    "OperatorWorkflowMemberResult",
    "OperatorWorkflowPublishedReceipt",
    "OperatorWorkflowRevisionReference",
    "OperatorWorkflowSource",
    "build_operator_workflow_member_result",
    "map_operator_workflow_catalog_result",
    "map_operator_workflow_draft_create_receipt",
    "map_operator_workflow_draft_edit_receipt",
    "map_operator_workflow_draft_reference",
    "map_operator_workflow_draft_undo_receipt",
    "map_operator_workflow_draft_validation_receipt",
    "map_operator_workflow_published_receipt",
]
