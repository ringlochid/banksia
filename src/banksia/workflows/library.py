from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from banksia.config import Settings
from banksia.persistence.models import WorkflowDraftModel
from banksia.providers import ProviderKind
from banksia.runtime.errors import invalid_request_shape_error
from banksia.workflows.authoring_contracts import (
    AUTHORING_OPTIONS,
    WorkflowAuthoringOptions,
    WorkflowDefaultProviderReadback,
    WorkflowDraftReadback,
    WorkflowGetResponse,
    WorkflowLibraryAction,
    WorkflowLibraryState,
    WorkflowSearchItem,
    WorkflowSearchResponse,
    map_workflow_published_readback,
    map_workflow_revision_readback,
)
from banksia.workflows.catalog import (
    list_workflow_revisions,
    read_workflow_detail_snapshot,
    search_workflows,
)
from banksia.workflows.contracts import NormalizedWorkflow, ProviderSandbox
from banksia.workflows.cursors import (
    decode_workflow_revision_cursor,
    decode_workflow_search_cursor,
    encode_workflow_revision_cursor,
    encode_workflow_search_cursor,
)
from banksia.workflows.service_errors import WorkflowNotFoundError


def build_workflow_authoring_options(settings: Settings) -> WorkflowAuthoringOptions:
    provider_kind = settings.runtime.default_provider
    if provider_kind is None:
        return AUTHORING_OPTIONS
    if provider_kind is ProviderKind.OPENCLAW:
        default_provider = WorkflowDefaultProviderReadback(kind="openclaw")
    elif provider_kind is ProviderKind.CODEX:
        default_provider = WorkflowDefaultProviderReadback(
            kind="codex",
            model=settings.codex.model or None,
            effort=settings.codex.effort or None,
            sandbox=ProviderSandbox(
                mode=settings.runtime.managed_provider_sandbox_mode.value,
                network=settings.runtime.managed_provider_network_access.value,
            ),
        )
    else:
        default_provider = WorkflowDefaultProviderReadback(
            kind="claude",
            model=settings.claude.model or None,
            effort=settings.claude.effort or None,
            sandbox=ProviderSandbox(
                mode=settings.runtime.managed_provider_sandbox_mode.value,
                network=settings.runtime.managed_provider_network_access.value,
            ),
        )
    return AUTHORING_OPTIONS.model_copy(update={"default_provider": default_provider})


async def search_workflow_catalog(
    session: AsyncSession,
    *,
    query: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> WorkflowSearchResponse:
    normalized_query = (query or "").strip()
    after_workflow_id = decode_workflow_search_cursor(
        cursor,
        normalized_query=normalized_query,
    )
    page = await search_workflows(
        session,
        query=normalized_query or None,
        after_workflow_id=after_workflow_id,
        limit=limit,
    )
    return WorkflowSearchResponse(
        items=tuple(
            WorkflowSearchItem(
                workflow_id=item.workflow_id,
                description=item.description,
                state=_library_state(
                    has_active_draft=item.has_active_draft,
                    has_published_workflow=item.published_revision_no is not None,
                ),
                updated_at=item.updated_at,
                provenance=item.provenance,
                published_revision_no=item.published_revision_no,
                available_actions=_library_actions(
                    has_published_workflow=item.published_revision_no is not None
                ),
            )
            for item in page.items
        ),
        next_cursor=(
            encode_workflow_search_cursor(
                page.next_workflow_id,
                normalized_query=normalized_query,
            )
            if page.next_workflow_id is not None
            else None
        ),
    )


async def read_workflow_catalog_entry(
    session: AsyncSession,
    *,
    workflow_id: str,
    revision_no: int | None = None,
    should_include_revisions: bool = True,
    revision_cursor: str | None = None,
    revision_limit: int = 20,
) -> WorkflowGetResponse:
    if not should_include_revisions and revision_cursor is not None:
        raise invalid_request_shape_error(
            "A Workflow revision cursor requires revision history to be included."
        )
    snapshot = await read_workflow_detail_snapshot(
        session,
        workflow_id=workflow_id,
        revision_no=revision_no,
    )
    summary = snapshot.summary
    published = snapshot.selected_published_revision
    draft = snapshot.active_draft
    before_revision_no = decode_workflow_revision_cursor(
        revision_cursor,
        workflow_id=workflow_id,
    )
    revision_page = (
        await list_workflow_revisions(
            session,
            workflow_id=workflow_id,
            before_revision_no=before_revision_no,
            maximum_revision_no=snapshot.maximum_revision_no,
            limit=revision_limit,
        )
        if should_include_revisions and summary.published_revision_no is not None
        else None
    )
    has_published_workflow = summary.published_revision_no is not None
    return WorkflowGetResponse(
        workflow_id=workflow_id,
        description=summary.description,
        state=_library_state(
            has_active_draft=summary.has_active_draft,
            has_published_workflow=has_published_workflow,
        ),
        updated_at=summary.updated_at,
        provenance=summary.provenance,
        published_revision_no=summary.published_revision_no,
        available_actions=_library_actions(has_published_workflow=has_published_workflow),
        published=(map_workflow_published_readback(published) if published is not None else None),
        revisions=tuple(map_workflow_revision_readback(item) for item in revision_page.items)
        if revision_page is not None
        else (),
        revisions_next_cursor=(
            encode_workflow_revision_cursor(
                revision_page.next_revision_no,
                workflow_id=workflow_id,
            )
            if revision_page is not None and revision_page.next_revision_no is not None
            else None
        ),
        active_draft=draft,
    )


async def read_workflow_draft(
    session: AsyncSession,
    *,
    draft_id: str,
) -> WorkflowDraftReadback:
    row = await session.get(WorkflowDraftModel, draft_id)
    if row is None:
        raise WorkflowNotFoundError(f"Workflow draft {draft_id!r} does not exist")
    return map_workflow_draft_readback(row)


def map_workflow_draft_readback(row: WorkflowDraftModel) -> WorkflowDraftReadback:
    return WorkflowDraftReadback(
        draft_id=row.draft_id,
        workflow_id=row.workflow_key,
        base_revision_no=row.base_revision_no,
        etag=row.etag,
        workflow=NormalizedWorkflow.model_validate(row.content_json),
    )


def _library_state(
    *,
    has_active_draft: bool,
    has_published_workflow: bool,
) -> WorkflowLibraryState:
    if has_active_draft and has_published_workflow:
        return WorkflowLibraryState.PUBLISHED_WITH_DRAFT
    if has_active_draft:
        return WorkflowLibraryState.DRAFT
    if has_published_workflow:
        return WorkflowLibraryState.PUBLISHED
    raise RuntimeError("Workflow library entry has no controller truth")


def _library_actions(
    *,
    has_published_workflow: bool,
) -> tuple[WorkflowLibraryAction, ...]:
    if has_published_workflow:
        return (
            WorkflowLibraryAction.EDIT,
            WorkflowLibraryAction.START_RUN,
        )
    return (WorkflowLibraryAction.EDIT,)


__all__ = [
    "build_workflow_authoring_options",
    "map_workflow_draft_readback",
    "read_workflow_catalog_entry",
    "read_workflow_draft",
    "search_workflow_catalog",
]
