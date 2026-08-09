from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from typing import TypeVar

from banksia.config import Settings
from banksia.operator.conversation_reads import OperatorSessionFactory
from banksia.operator.tools.contracts import (
    EmptyOperatorToolInput,
    OperatorTool,
    OperatorToolName,
    WorkflowDraftCreateInput,
    WorkflowDraftEditInput,
    WorkflowDraftMutationInput,
    WorkflowDraftSelection,
    WorkflowDraftUndoInput,
    WorkflowDraftValidateInput,
    WorkflowGetInput,
    WorkflowPublishedSelection,
    WorkflowSearchInput,
    bind_operator_tool,
)
from banksia.operator.tools.workflow_projection import (
    OperatorPublishedWorkflowSource,
    OperatorWorkflowCatalogResult,
    OperatorWorkflowDraftCreateReceipt,
    OperatorWorkflowDraftDiscardReceipt,
    OperatorWorkflowDraftEditReceipt,
    OperatorWorkflowDraftStaleError,
    OperatorWorkflowDraftUndoReceipt,
    OperatorWorkflowDraftValidationReceipt,
    OperatorWorkflowMemberResult,
    OperatorWorkflowPublishedReceipt,
    build_operator_workflow_member_result,
    map_operator_workflow_catalog_result,
    map_operator_workflow_draft_create_receipt,
    map_operator_workflow_draft_edit_receipt,
    map_operator_workflow_draft_reference,
    map_operator_workflow_draft_undo_receipt,
    map_operator_workflow_draft_validation_receipt,
    map_operator_workflow_published_receipt,
)
from banksia.persistence.session_operations import write_session_operation
from banksia.workflows.authoring import (
    discard_workflow_draft,
    edit_workflow_draft,
    import_workflow_draft,
    publish_workflow_draft,
    undo_workflow_draft,
    validate_workflow_draft,
)
from banksia.workflows.authoring_contracts import (
    WorkflowAuthoringOptions,
    WorkflowSearchResponse,
)
from banksia.workflows.catalog import (
    list_workflow_revisions,
    read_published_workflow_revision,
    read_workflow_catalog_snapshot,
)
from banksia.workflows.contracts import NormalizedWorkflow
from banksia.workflows.cursors import (
    decode_workflow_revision_cursor,
    encode_workflow_revision_cursor,
)
from banksia.workflows.library import (
    build_workflow_authoring_options,
    read_workflow_draft,
    search_workflow_catalog,
)
from banksia.workflows.service_errors import (
    WorkflowNotFoundError,
    WorkflowStaleDraftError,
)

ResultT = TypeVar("ResultT")


@dataclass(frozen=True, slots=True)
class _WorkflowOperatorLeaves:
    settings: Settings
    session_factory: OperatorSessionFactory

    async def search(self, request: WorkflowSearchInput) -> WorkflowSearchResponse:
        async with self.session_factory() as session:
            return await search_workflow_catalog(
                session,
                query=request.query,
                cursor=request.cursor,
                limit=request.limit,
            )

    async def get(
        self,
        request: WorkflowGetInput,
    ) -> OperatorWorkflowCatalogResult | OperatorWorkflowMemberResult:
        async with self.session_factory() as session:
            selection = request.selection
            if selection.kind == "catalog":
                snapshot = await read_workflow_catalog_snapshot(
                    session,
                    workflow_id=request.workflow_id,
                )
                before_revision_no = decode_workflow_revision_cursor(
                    selection.revision_cursor,
                    workflow_id=request.workflow_id,
                )
                revision_page = (
                    await list_workflow_revisions(
                        session,
                        workflow_id=request.workflow_id,
                        before_revision_no=before_revision_no,
                        maximum_revision_no=snapshot.maximum_revision_no,
                        limit=selection.revision_limit,
                    )
                    if (
                        selection.should_include_revisions
                        and snapshot.summary.published_revision_no is not None
                    )
                    else None
                )
                return map_operator_workflow_catalog_result(
                    snapshot,
                    revision_page=revision_page,
                    revisions_next_cursor=(
                        encode_workflow_revision_cursor(
                            revision_page.next_revision_no,
                            workflow_id=request.workflow_id,
                        )
                        if revision_page is not None and revision_page.next_revision_no is not None
                        else None
                    ),
                )
            if isinstance(selection, WorkflowPublishedSelection):
                published = await read_published_workflow_revision(
                    session,
                    workflow_id=request.workflow_id,
                    revision_no=selection.revision_no,
                )
                return build_operator_workflow_member_result(
                    published.workflow,
                    source=OperatorPublishedWorkflowSource(
                        workflow_id=published.workflow_id,
                        revision_no=published.revision_no,
                    ),
                    member_id=selection.member_id,
                )
            if not isinstance(selection, WorkflowDraftSelection):
                raise TypeError("unknown Workflow source selection")
            draft = await read_workflow_draft(
                session,
                draft_id=selection.draft_id,
            )
            draft_reference = map_operator_workflow_draft_reference(draft)
            if draft.workflow_id != request.workflow_id:
                raise WorkflowNotFoundError(
                    f"Workflow draft {selection.draft_id!r} does not belong to "
                    f"Workflow {request.workflow_id!r}"
                )
            if draft.etag != selection.etag:
                raise OperatorWorkflowDraftStaleError(draft_reference)
            return build_operator_workflow_member_result(
                draft.workflow,
                source=draft_reference,
                member_id=selection.member_id,
            )

    async def authoring_options(
        self,
        request: EmptyOperatorToolInput,
    ) -> WorkflowAuthoringOptions:
        del request
        return build_workflow_authoring_options(self.settings)

    async def create_draft(
        self,
        request: WorkflowDraftCreateInput,
    ) -> OperatorWorkflowDraftCreateReceipt:
        async with self.session_factory() as session:
            result = await _run_with_compact_stale_error(
                write_session_operation(
                    lambda db: import_workflow_draft(
                        db,
                        workflow=NormalizedWorkflow.model_validate(
                            request.workflow.model_dump(mode="json", exclude_none=True)
                        ),
                        expected_etag=request.etag,
                    ),
                    session=session,
                )
            )
        return map_operator_workflow_draft_create_receipt(result)

    async def edit_draft(
        self,
        request: WorkflowDraftEditInput,
    ) -> OperatorWorkflowDraftEditReceipt:
        async with self.session_factory() as session:
            result = await _run_with_compact_stale_error(
                write_session_operation(
                    lambda db: edit_workflow_draft(
                        db,
                        draft_id=request.draft_id,
                        expected_etag=request.etag,
                        operation=request.operation,
                    ),
                    session=session,
                )
            )
        return map_operator_workflow_draft_edit_receipt(
            result,
            operation=request.operation,
        )

    async def validate_draft(
        self,
        request: WorkflowDraftValidateInput,
    ) -> OperatorWorkflowDraftValidationReceipt:
        async with self.session_factory() as session:
            result = await validate_workflow_draft(
                session,
                draft_id=request.draft_id,
            )
        return map_operator_workflow_draft_validation_receipt(result)

    async def undo_draft(
        self,
        request: WorkflowDraftUndoInput,
    ) -> OperatorWorkflowDraftUndoReceipt:
        async with self.session_factory() as session:
            draft = await _run_with_compact_stale_error(
                write_session_operation(
                    lambda db: undo_workflow_draft(
                        db,
                        draft_id=request.draft_id,
                        expected_etag=request.etag,
                        receipt_id=request.receipt_id,
                    ),
                    session=session,
                )
            )
        return map_operator_workflow_draft_undo_receipt(
            draft,
            consumed_receipt_id=request.receipt_id,
        )

    async def discard_draft(
        self,
        request: WorkflowDraftMutationInput,
    ) -> OperatorWorkflowDraftDiscardReceipt:
        async with self.session_factory() as session:
            await _run_with_compact_stale_error(
                write_session_operation(
                    lambda db: discard_workflow_draft(
                        db,
                        draft_id=request.draft_id,
                        expected_etag=request.etag,
                    ),
                    session=session,
                )
            )
        return OperatorWorkflowDraftDiscardReceipt(
            is_discarded=True,
            draft_id=request.draft_id,
        )

    async def publish_draft(
        self,
        request: WorkflowDraftMutationInput,
    ) -> OperatorWorkflowPublishedReceipt:
        async with self.session_factory() as session:
            published = await _run_with_compact_stale_error(
                write_session_operation(
                    lambda db: publish_workflow_draft(
                        db,
                        draft_id=request.draft_id,
                        expected_etag=request.etag,
                    ),
                    session=session,
                )
            )
        return map_operator_workflow_published_receipt(published)


def build_workflow_operator_tools(
    *,
    settings: Settings,
    session_factory: OperatorSessionFactory,
) -> tuple[OperatorTool, ...]:
    leaves = _WorkflowOperatorLeaves(
        settings=settings,
        session_factory=session_factory,
    )
    return (
        *_build_workflow_read_tools(leaves),
        *_build_workflow_edit_tools(leaves),
        *_build_workflow_release_tools(leaves),
    )


def _build_workflow_read_tools(
    leaves: _WorkflowOperatorLeaves,
) -> tuple[OperatorTool, ...]:
    return (
        bind_operator_tool(
            name=OperatorToolName.WORKFLOW_SEARCH,
            description=(
                "Search the controller-owned Workflow library by ID or description. "
                "Continue a page only with the returned cursor."
            ),
            input_model=WorkflowSearchInput,
            handler=leaves.search,
        ),
        bind_operator_tool(
            name=OperatorToolName.WORKFLOW_GET,
            description=(
                "Read either compact Workflow catalog/history truth or exactly one Member "
                "from an exact published revision or exact draft ETag."
            ),
            input_model=WorkflowGetInput,
            handler=leaves.get,
        ),
        bind_operator_tool(
            name=OperatorToolName.WORKFLOW_AUTHORING_OPTIONS,
            description=(
                "Read the fields, providers, sandbox choices, capabilities, and configured "
                "defaults accepted by Workflow authoring."
            ),
            input_model=EmptyOperatorToolInput,
            handler=leaves.authoring_options,
        ),
    )


def _build_workflow_edit_tools(
    leaves: _WorkflowOperatorLeaves,
) -> tuple[OperatorTool, ...]:
    return (
        bind_operator_tool(
            name=OperatorToolName.WORKFLOW_DRAFT_CREATE,
            description=(
                "Create a draft from one complete structured JSON Workflow. If that "
                "Workflow already has an active draft, pass its current ETag to replace it. "
                "Returns only its current draft reference and optional Undo receipt."
            ),
            input_model=WorkflowDraftCreateInput,
            handler=leaves.create_draft,
        ),
        bind_operator_tool(
            name=OperatorToolName.WORKFLOW_DRAFT_EDIT,
            description=(
                "Apply one typed edit to the current draft using its exact ETag. New Member "
                "IDs are allocated by the controller and returned in the accepted-change "
                "receipt."
            ),
            input_model=WorkflowDraftEditInput,
            handler=leaves.edit_draft,
        ),
        bind_operator_tool(
            name=OperatorToolName.WORKFLOW_DRAFT_VALIDATE,
            description="Validate the current draft and return its current reference and issues.",
            input_model=WorkflowDraftValidateInput,
            handler=leaves.validate_draft,
        ),
    )


def _build_workflow_release_tools(
    leaves: _WorkflowOperatorLeaves,
) -> tuple[OperatorTool, ...]:
    return (
        bind_operator_tool(
            name=OperatorToolName.WORKFLOW_DRAFT_UNDO,
            description=(
                "Use one controller-issued Undo receipt against the exact current draft "
                "ETag. Receipts are single use."
            ),
            input_model=WorkflowDraftUndoInput,
            handler=leaves.undo_draft,
        ),
        bind_operator_tool(
            name=OperatorToolName.WORKFLOW_DRAFT_DISCARD,
            description=(
                "Discard only the mutable draft using its current ETag. Published revisions "
                "remain immutable."
            ),
            input_model=WorkflowDraftMutationInput,
            handler=leaves.discard_draft,
        ),
        bind_operator_tool(
            name=OperatorToolName.WORKFLOW_DRAFT_PUBLISH,
            description=(
                "Publish the exact current draft revision using its ETag and remove that "
                "mutable draft."
            ),
            input_model=WorkflowDraftMutationInput,
            handler=leaves.publish_draft,
        ),
    )


async def _run_with_compact_stale_error(
    operation: Awaitable[ResultT],
) -> ResultT:
    stale_draft = None
    try:
        return await operation
    except WorkflowStaleDraftError as error:
        stale_draft = map_operator_workflow_draft_reference(error.current)
    raise OperatorWorkflowDraftStaleError(stale_draft) from None


__all__ = ["build_workflow_operator_tools"]
