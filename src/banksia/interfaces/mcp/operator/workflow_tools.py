from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

import banksia.persistence.session_operations as session_operations
from banksia.interfaces.mcp.mcp_operation_failures import ContractFastMCP
from banksia.interfaces.mcp.tool_teaching import (
    ToolTeaching,
    mutating_tool_teaching,
    read_only_tool_teaching,
)
from banksia.workflows.authoring import (
    create_workflow_draft,
    discard_workflow_draft,
    edit_workflow_draft,
    publish_workflow_draft,
    read_workflow_catalog_entry,
    search_workflow_catalog,
    undo_workflow_draft,
    validate_workflow_draft,
)
from banksia.workflows.authoring_contracts import (
    AUTHORING_OPTIONS,
    WorkflowAuthoringOptions,
    WorkflowDraftDiscardResult,
    WorkflowDraftMutationResult,
    WorkflowDraftReadback,
    WorkflowDraftValidationResult,
    WorkflowGetResponse,
    WorkflowPublishedReadback,
    WorkflowSearchResponse,
    map_workflow_published_readback,
)
from banksia.workflows.contracts import NormalizedWorkflow
from banksia.workflows.ingest import normalize_workflow_object
from banksia.workflows.operations import DraftOperation

WORKFLOW_OPERATOR_TOOL_NAMES: tuple[str, ...] = (
    "workflow_search",
    "workflow_get",
    "workflow_authoring_options",
    "workflow_draft_create",
    "workflow_draft_edit",
    "workflow_draft_validate",
    "workflow_draft_undo",
    "workflow_draft_discard",
    "workflow_draft_publish",
)


def register_workflow_tools(server: FastMCP) -> None:
    _register_workflow_search(server)
    _register_workflow_get(server)
    _register_workflow_authoring_options(server)
    _register_workflow_draft_create(server)
    _register_workflow_draft_edit(server)
    _register_workflow_draft_validate(server)
    _register_workflow_draft_undo(server)
    _register_workflow_draft_discard(server)
    _register_workflow_draft_publish(server)
    if isinstance(server, ContractFastMCP):
        server.require_strict_tool_inputs(WORKFLOW_OPERATOR_TOOL_NAMES)


def _register_workflow_search(server: FastMCP) -> None:
    search_teaching = read_only_tool_teaching(
        name="workflow_search",
        summary="Search the published Workflow catalog.",
        details=("Use workflow_get for the selected Workflow and bounded revision history.",),
    )

    @server.tool(
        name="workflow_search",
        title=search_teaching.title,
        description=search_teaching.description,
        annotations=_annotations(search_teaching, is_idempotent=True),
    )
    async def workflow_search(
        query: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> WorkflowSearchResponse:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return await session_operations.read_session_operation(
            lambda session: search_workflow_catalog(
                session,
                query=query,
                cursor=cursor,
                limit=limit,
            )
        )


def _register_workflow_get(server: FastMCP) -> None:
    get_teaching = read_only_tool_teaching(
        name="workflow_get",
        summary=(
            "Read one current or exact immutable Workflow revision, bounded history, "
            "and its active draft when present."
        ),
    )

    @server.tool(
        name="workflow_get",
        title=get_teaching.title,
        description=get_teaching.description,
        annotations=_annotations(get_teaching, is_idempotent=True),
    )
    async def workflow_get(
        workflow_id: str,
        revision_no: int | None = None,
        include_revisions: bool = True,
        revision_cursor: str | None = None,
        revision_limit: int = 20,
    ) -> WorkflowGetResponse:
        if not 1 <= revision_limit <= 100:
            raise ValueError("revision_limit must be between 1 and 100")
        return await session_operations.read_session_operation(
            lambda session: read_workflow_catalog_entry(
                session,
                workflow_id=workflow_id,
                revision_no=revision_no,
                should_include_revisions=include_revisions,
                revision_cursor=revision_cursor,
                revision_limit=revision_limit,
            )
        )


def _register_workflow_authoring_options(server: FastMCP) -> None:
    options_teaching = read_only_tool_teaching(
        name="workflow_authoring_options",
        summary="Read the closed Workflow draft operation and provider option vocabulary.",
    )

    @server.tool(
        name="workflow_authoring_options",
        title=options_teaching.title,
        description=options_teaching.description,
        annotations=_annotations(options_teaching, is_idempotent=True),
    )
    async def workflow_authoring_options() -> WorkflowAuthoringOptions:
        return AUTHORING_OPTIONS


def _register_workflow_draft_create(server: FastMCP) -> None:
    create_teaching = mutating_tool_teaching(
        name="workflow_draft_create",
        summary="Create the single active draft for one complete normalized Workflow.",
        details=("This does not publish or start runtime work.",),
    )

    @server.tool(
        name="workflow_draft_create",
        title=create_teaching.title,
        description=create_teaching.description,
        annotations=_annotations(create_teaching),
    )
    async def workflow_draft_create(workflow: NormalizedWorkflow) -> WorkflowDraftReadback:
        normalized = normalize_workflow_object(workflow.model_dump(mode="json", exclude_none=True))
        return await session_operations.write_session_operation(
            lambda session: create_workflow_draft(session, workflow=normalized)
        )


def _register_workflow_draft_edit(server: FastMCP) -> None:
    edit_teaching = mutating_tool_teaching(
        name="workflow_draft_edit",
        summary="Apply one closed edit operation using the current opaque draft ETag.",
        details=("Returns one single-use Undo receipt and a new ETag.",),
    )

    @server.tool(
        name="workflow_draft_edit",
        title=edit_teaching.title,
        description=edit_teaching.description,
        annotations=_annotations(edit_teaching),
    )
    async def workflow_draft_edit(
        draft_id: str,
        etag: str,
        operation: DraftOperation,
    ) -> WorkflowDraftMutationResult:
        return await session_operations.write_session_operation(
            lambda session: edit_workflow_draft(
                session,
                draft_id=draft_id,
                expected_etag=etag,
                operation=operation,
            )
        )


def _register_workflow_draft_validate(server: FastMCP) -> None:
    validate_teaching = read_only_tool_teaching(
        name="workflow_draft_validate",
        summary="Validate the complete current draft without changing it.",
    )

    @server.tool(
        name="workflow_draft_validate",
        title=validate_teaching.title,
        description=validate_teaching.description,
        annotations=_annotations(validate_teaching, is_idempotent=True),
    )
    async def workflow_draft_validate(draft_id: str) -> WorkflowDraftValidationResult:
        return await session_operations.read_session_operation(
            lambda session: validate_workflow_draft(session, draft_id=draft_id)
        )


def _register_workflow_draft_undo(server: FastMCP) -> None:
    undo_teaching = mutating_tool_teaching(
        name="workflow_draft_undo",
        summary="Consume one Undo receipt against its exact current draft ETag.",
    )

    @server.tool(
        name="workflow_draft_undo",
        title=undo_teaching.title,
        description=undo_teaching.description,
        annotations=_annotations(undo_teaching),
    )
    async def workflow_draft_undo(
        draft_id: str,
        etag: str,
        receipt_id: str,
    ) -> WorkflowDraftReadback:
        return await session_operations.write_session_operation(
            lambda session: undo_workflow_draft(
                session,
                draft_id=draft_id,
                expected_etag=etag,
                receipt_id=receipt_id,
            )
        )


def _register_workflow_draft_discard(server: FastMCP) -> None:
    discard_teaching = mutating_tool_teaching(
        name="workflow_draft_discard",
        summary="Discard only the selected draft using its current ETag.",
    )

    @server.tool(
        name="workflow_draft_discard",
        title=discard_teaching.title,
        description=discard_teaching.description,
        annotations=_annotations(
            discard_teaching,
            is_destructive=True,
            is_idempotent=True,
        ),
    )
    async def workflow_draft_discard(
        draft_id: str,
        etag: str,
    ) -> WorkflowDraftDiscardResult:
        await session_operations.write_session_operation(
            lambda session: discard_workflow_draft(
                session,
                draft_id=draft_id,
                expected_etag=etag,
            )
        )
        return WorkflowDraftDiscardResult(is_discarded=True, draft_id=draft_id)


def _register_workflow_draft_publish(server: FastMCP) -> None:
    publish_teaching = mutating_tool_teaching(
        name="workflow_draft_publish",
        summary="Publish the exact current draft as an immutable Workflow revision.",
        details=("This does not start a Task or contact a provider.",),
    )

    @server.tool(
        name="workflow_draft_publish",
        title=publish_teaching.title,
        description=publish_teaching.description,
        annotations=_annotations(
            publish_teaching,
            is_destructive=True,
            is_idempotent=True,
        ),
    )
    async def workflow_draft_publish(
        draft_id: str,
        etag: str,
    ) -> WorkflowPublishedReadback:
        return map_workflow_published_readback(
            await session_operations.write_session_operation(
                lambda session: publish_workflow_draft(
                    session,
                    draft_id=draft_id,
                    expected_etag=etag,
                )
            )
        )


def _annotations(
    teaching: ToolTeaching,
    *,
    is_destructive: bool = False,
    is_idempotent: bool = False,
) -> ToolAnnotations:
    return ToolAnnotations(
        readOnlyHint=teaching.annotations.readOnlyHint,
        destructiveHint=is_destructive,
        idempotentHint=is_idempotent,
        openWorldHint=False,
    )


__all__ = ["WORKFLOW_OPERATOR_TOOL_NAMES", "register_workflow_tools"]
