from __future__ import annotations

from dataclasses import dataclass

from banksia.config import Settings
from banksia.operator.conversation_reads import OperatorSessionFactory
from banksia.operator.tools.contracts import (
    EmptyOperatorToolInput,
    OperatorTool,
    OperatorToolName,
    WorkflowDraftCreateInput,
    WorkflowDraftEditInput,
    WorkflowDraftMutationInput,
    WorkflowDraftUndoInput,
    WorkflowDraftValidateInput,
    WorkflowGetInput,
    WorkflowSearchInput,
    bind_operator_tool,
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
    WorkflowDraftDiscardResult,
    WorkflowDraftImportResult,
    WorkflowDraftMutationResult,
    WorkflowDraftReadback,
    WorkflowDraftValidationResult,
    WorkflowGetResponse,
    WorkflowPublishedReadback,
    WorkflowSearchResponse,
    map_workflow_published_readback,
)
from banksia.workflows.library import (
    build_workflow_authoring_options,
    read_workflow_catalog_entry,
    search_workflow_catalog,
)


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

    async def get(self, request: WorkflowGetInput) -> WorkflowGetResponse:
        async with self.session_factory() as session:
            return await read_workflow_catalog_entry(
                session,
                workflow_id=request.workflow_id,
                revision_no=request.revision_no,
                should_include_revisions=request.should_include_revisions,
                revision_cursor=request.revision_cursor,
                revision_limit=request.revision_limit,
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
    ) -> WorkflowDraftImportResult:
        async with self.session_factory() as session:
            return await write_session_operation(
                lambda db: import_workflow_draft(
                    db,
                    workflow=request.workflow,
                    expected_etag=request.etag,
                ),
                session=session,
            )

    async def edit_draft(
        self,
        request: WorkflowDraftEditInput,
    ) -> WorkflowDraftMutationResult:
        async with self.session_factory() as session:
            return await write_session_operation(
                lambda db: edit_workflow_draft(
                    db,
                    draft_id=request.draft_id,
                    expected_etag=request.etag,
                    operation=request.operation,
                ),
                session=session,
            )

    async def validate_draft(
        self,
        request: WorkflowDraftValidateInput,
    ) -> WorkflowDraftValidationResult:
        async with self.session_factory() as session:
            return await validate_workflow_draft(
                session,
                draft_id=request.draft_id,
            )

    async def undo_draft(
        self,
        request: WorkflowDraftUndoInput,
    ) -> WorkflowDraftReadback:
        async with self.session_factory() as session:
            return await write_session_operation(
                lambda db: undo_workflow_draft(
                    db,
                    draft_id=request.draft_id,
                    expected_etag=request.etag,
                    receipt_id=request.receipt_id,
                ),
                session=session,
            )

    async def discard_draft(
        self,
        request: WorkflowDraftMutationInput,
    ) -> WorkflowDraftDiscardResult:
        async with self.session_factory() as session:
            await write_session_operation(
                lambda db: discard_workflow_draft(
                    db,
                    draft_id=request.draft_id,
                    expected_etag=request.etag,
                ),
                session=session,
            )
        return WorkflowDraftDiscardResult(
            is_discarded=True,
            draft_id=request.draft_id,
        )

    async def publish_draft(
        self,
        request: WorkflowDraftMutationInput,
    ) -> WorkflowPublishedReadback:
        async with self.session_factory() as session:
            published = await write_session_operation(
                lambda db: publish_workflow_draft(
                    db,
                    draft_id=request.draft_id,
                    expected_etag=request.etag,
                ),
                session=session,
            )
        return map_workflow_published_readback(published)


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
                "Read one coherent Workflow snapshot, including its current publication, "
                "active draft and ETag, and bounded revision history."
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
                "Workflow already has an active draft, pass its current ETag to replace it."
            ),
            input_model=WorkflowDraftCreateInput,
            handler=leaves.create_draft,
        ),
        bind_operator_tool(
            name=OperatorToolName.WORKFLOW_DRAFT_EDIT,
            description=(
                "Apply one typed edit to the current draft using its exact ETag. New Member "
                "IDs are allocated by the controller."
            ),
            input_model=WorkflowDraftEditInput,
            handler=leaves.edit_draft,
        ),
        bind_operator_tool(
            name=OperatorToolName.WORKFLOW_DRAFT_VALIDATE,
            description="Validate the current draft and return its complete current readback.",
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


__all__ = ["build_workflow_operator_tools"]
