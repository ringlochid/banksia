from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import Table, delete, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from oh_my_subagents.persistence.models import (
    WorkflowDefinitionModel,
    WorkflowDraftModel,
    WorkflowRevisionModel,
    WorkflowUndoReceiptModel,
)
from oh_my_subagents.workflows.authoring_contracts import (
    CreateWorkflowDraftRequest,
    WorkflowDraftImportResult,
    WorkflowDraftMutationResult,
    WorkflowDraftOpenRequest,
    WorkflowDraftOpenResult,
    WorkflowDraftReadback,
    WorkflowDraftValidationResult,
    WorkflowRemovalResult,
)
from oh_my_subagents.workflows.authoring_identifiers import (
    new_workflow_draft_etag,
    new_workflow_draft_id,
    new_workflow_undo_receipt_id,
    next_workflow_member_sequence,
)
from oh_my_subagents.workflows.canonical import canonical_workflow_hash
from oh_my_subagents.workflows.catalog import read_published_workflow_revision
from oh_my_subagents.workflows.contracts import (
    NormalizedWorkflow,
    PublishedWorkflowRevision,
    WorkflowProvenance,
)
from oh_my_subagents.workflows.ingest import normalize_workflow_object
from oh_my_subagents.workflows.integrity import (
    read_persisted_workflow,
    validate_persisted_workflow_identity,
)
from oh_my_subagents.workflows.library import (
    build_workflow_authoring_options,
    map_workflow_draft_readback,
    read_workflow_catalog_entry,
    read_workflow_draft,
    reload_workflow_draft,
    search_workflow_catalog,
)
from oh_my_subagents.workflows.operations import (
    DraftOperation,
    build_new_workflow,
    edit_normalized_workflow,
)
from oh_my_subagents.workflows.provider_retirement import retired_provider_issues
from oh_my_subagents.workflows.publication import acquire_workflow_owner, publish_workflow_revision
from oh_my_subagents.workflows.service_errors import (
    WorkflowDraftConflictError,
    WorkflowNotFoundError,
    WorkflowPreconditionRequiredError,
    WorkflowStaleDraftError,
    WorkflowUndoReceiptError,
)


async def open_workflow_draft(
    session: AsyncSession,
    *,
    request: WorkflowDraftOpenRequest,
) -> WorkflowDraftOpenResult:
    if isinstance(request, CreateWorkflowDraftRequest):
        workflow = build_new_workflow(
            workflow_id=request.workflow_id,
            description=request.description,
            note=request.note,
            lead=request.lead,
        )
        return WorkflowDraftOpenResult(
            draft=await _create_new_workflow_draft(session, workflow=workflow),
            is_created=True,
        )
    return await _open_existing_workflow_draft(
        session,
        workflow_id=request.workflow_id,
    )


async def import_workflow_draft(
    session: AsyncSession,
    *,
    workflow: NormalizedWorkflow,
    expected_etag: str | None = None,
) -> WorkflowDraftImportResult:
    existing = await _active_draft_row_for_update(session, workflow_id=workflow.id)
    if existing is None:
        return WorkflowDraftImportResult(
            draft=await _create_workflow_draft(session, workflow=workflow),
            is_created=True,
        )
    if expected_etag is None:
        raise WorkflowPreconditionRequiredError(
            f"Workflow {workflow.id!r} already has a draft; its current ETag is required"
        )
    if existing.etag != expected_etag:
        raise WorkflowStaleDraftError(map_workflow_draft_readback(existing))
    if existing.content_hash == canonical_workflow_hash(workflow):
        return WorkflowDraftImportResult(
            draft=map_workflow_draft_readback(existing),
            is_created=False,
        )
    receipt = await _replace_draft_content(session, row=existing, workflow=workflow)
    return WorkflowDraftImportResult(
        draft=await read_workflow_draft(session, draft_id=existing.draft_id),
        is_created=False,
        undo_receipt=receipt,
    )


async def edit_workflow_draft(
    session: AsyncSession,
    *,
    draft_id: str,
    expected_etag: str,
    operation: DraftOperation,
) -> WorkflowDraftMutationResult:
    row = await _current_draft_row(session, draft_id=draft_id, expected_etag=expected_etag)
    current_workflow = read_persisted_workflow(
        row.content_json,
        expected_workflow_id=row.workflow_key,
        source="Workflow draft",
    )
    next_member_sequence = row.next_member_sequence

    def allocate_member_id() -> str:
        nonlocal next_member_sequence
        member_id = f"member-{next_member_sequence}"
        next_member_sequence += 1
        return member_id

    updated_workflow = edit_normalized_workflow(
        current_workflow,
        operation,
        member_id_allocator=allocate_member_id,
    )
    receipt = await _replace_draft_content(
        session,
        row=row,
        workflow=updated_workflow,
        next_member_sequence=next_member_sequence,
    )
    return WorkflowDraftMutationResult(
        draft=await read_workflow_draft(session, draft_id=draft_id),
        undo_receipt=receipt,
    )


async def validate_workflow_draft(
    session: AsyncSession,
    *,
    draft_id: str,
) -> WorkflowDraftValidationResult:
    draft = await read_workflow_draft(session, draft_id=draft_id)
    issues = retired_provider_issues(draft.workflow)
    return WorkflowDraftValidationResult(
        is_valid=not issues,
        issues=issues,
        draft=draft,
    )


async def undo_workflow_draft(
    session: AsyncSession,
    *,
    draft_id: str,
    expected_etag: str,
    receipt_id: str,
) -> WorkflowDraftReadback:
    row = await _current_draft_row(session, draft_id=draft_id, expected_etag=expected_etag)
    receipt = await session.scalar(
        select(WorkflowUndoReceiptModel).where(
            WorkflowUndoReceiptModel.receipt_id == receipt_id,
            WorkflowUndoReceiptModel.draft_id == draft_id,
        )
    )
    if receipt is None or receipt.consumed:
        raise WorkflowUndoReceiptError("Undo receipt is missing or has already been used")
    if receipt.expected_etag != row.etag:
        raise WorkflowStaleDraftError(map_workflow_draft_readback(row))
    read_persisted_workflow(
        receipt.previous_content_json,
        expected_workflow_id=row.workflow_key,
        source="Workflow undo receipt",
    )
    new_etag = new_workflow_draft_etag()
    consumed = await session.execute(
        update(WorkflowUndoReceiptModel)
        .where(
            WorkflowUndoReceiptModel.receipt_id == receipt_id,
            WorkflowUndoReceiptModel.consumed.is_(False),
        )
        .values(consumed=True)
    )
    if cast(CursorResult[Any], consumed).rowcount != 1:
        raise WorkflowUndoReceiptError("Undo receipt has already been used")
    changed = await session.execute(
        update(WorkflowDraftModel)
        .where(
            WorkflowDraftModel.draft_id == draft_id,
            WorkflowDraftModel.etag == expected_etag,
        )
        .values(
            content_json=receipt.previous_content_json,
            content_hash=receipt.previous_content_hash,
            etag=new_etag,
        )
    )
    if cast(CursorResult[Any], changed).rowcount != 1:
        session.expire(row)
        current = await session.get(WorkflowDraftModel, draft_id)
        if current is None:
            raise WorkflowNotFoundError(f"Workflow draft {draft_id!r} does not exist")
        raise WorkflowStaleDraftError(map_workflow_draft_readback(current))
    return await reload_workflow_draft(session, draft_id=draft_id)


async def discard_workflow_draft(
    session: AsyncSession,
    *,
    draft_id: str,
    expected_etag: str,
) -> None:
    row = await _current_draft_row(
        session,
        draft_id=draft_id,
        expected_etag=expected_etag,
    )
    deleted = await session.execute(
        delete(WorkflowDraftModel).where(
            WorkflowDraftModel.draft_id == draft_id,
            WorkflowDraftModel.etag == expected_etag,
        )
    )
    if cast(CursorResult[Any], deleted).rowcount == 1:
        await session.execute(
            update(WorkflowDefinitionModel)
            .where(
                WorkflowDefinitionModel.workflow_key == row.workflow_key,
                WorkflowDefinitionModel.current_revision_no.is_not(None),
            )
            .values(updated_at=datetime.now(UTC))
        )
        return
    current = await session.get(WorkflowDraftModel, draft_id)
    if current is None:
        raise WorkflowNotFoundError(f"Workflow draft {draft_id!r} does not exist")
    raise WorkflowStaleDraftError(map_workflow_draft_readback(current))


async def remove_workflow(
    session: AsyncSession,
    *,
    workflow_id: str,
) -> WorkflowRemovalResult:
    draft = await _active_draft_row_for_update(session, workflow_id=workflow_id)
    owner = await acquire_workflow_owner(session, workflow_id=workflow_id)
    draft = await _active_draft_row_for_update(session, workflow_id=workflow_id)
    has_revisions = await _has_published_revisions(session, workflow_id=workflow_id)
    if draft is None and owner.current_revision_no is None:
        if not has_revisions:
            await session.delete(owner)
        raise WorkflowNotFoundError(f"Workflow {workflow_id!r} does not exist")
    if draft is not None:
        await session.delete(draft)
    if owner.current_revision_no is not None:
        owner.current_revision_no = None
        owner.updated_at = datetime.now(UTC)
    elif not has_revisions:
        await session.delete(owner)
    await session.flush()
    return WorkflowRemovalResult(is_removed=True, workflow_id=workflow_id)


async def publish_workflow_draft(
    session: AsyncSession,
    *,
    draft_id: str,
    expected_etag: str,
) -> PublishedWorkflowRevision:
    row = await _current_draft_row(session, draft_id=draft_id, expected_etag=expected_etag)
    workflow = read_persisted_workflow(
        row.content_json,
        expected_workflow_id=row.workflow_key,
        source="Workflow draft",
    )
    workflow = normalize_workflow_object(workflow.model_dump(mode="json", exclude_none=True))
    await _delete_draft_with_etag(
        session,
        row=row,
        expected_etag=expected_etag,
    )
    published = await publish_workflow_revision(
        session,
        workflow=workflow,
        provenance=WorkflowProvenance.USER,
        should_update_current=True,
    )
    return published


async def _replace_draft_content(
    session: AsyncSession,
    *,
    row: WorkflowDraftModel,
    workflow: NormalizedWorkflow,
    next_member_sequence: int | None = None,
) -> str:
    validate_persisted_workflow_identity(
        workflow.id,
        expected_workflow_id=row.workflow_key,
        source="replacement Workflow draft",
    )
    read_persisted_workflow(
        row.content_json,
        expected_workflow_id=row.workflow_key,
        source="Workflow draft",
    )
    previous_etag = row.etag
    previous_content_hash = row.content_hash
    previous_content_json = row.content_json
    next_etag = new_workflow_draft_etag()
    receipt_id = new_workflow_undo_receipt_id()
    changed = await session.execute(
        update(WorkflowDraftModel)
        .where(
            WorkflowDraftModel.draft_id == row.draft_id,
            WorkflowDraftModel.etag == previous_etag,
        )
        .values(
            content_hash=canonical_workflow_hash(workflow),
            content_json=workflow.model_dump(mode="json", exclude_none=True),
            etag=next_etag,
            next_member_sequence=max(
                row.next_member_sequence,
                next_member_sequence or next_workflow_member_sequence(workflow),
            ),
        )
    )
    if cast(CursorResult[Any], changed).rowcount != 1:
        session.expire(row)
        current = await session.get(WorkflowDraftModel, row.draft_id)
        if current is None:
            raise WorkflowNotFoundError(f"Workflow draft {row.draft_id!r} does not exist")
        raise WorkflowStaleDraftError(map_workflow_draft_readback(current))
    session.add(
        WorkflowUndoReceiptModel(
            receipt_id=receipt_id,
            draft_id=row.draft_id,
            expected_etag=next_etag,
            previous_content_hash=previous_content_hash,
            previous_content_json=previous_content_json,
        )
    )
    await session.flush()
    return receipt_id


async def _create_workflow_draft(
    session: AsyncSession,
    *,
    workflow: NormalizedWorkflow,
) -> WorkflowDraftReadback:
    existing = await _active_draft_row_for_update(session, workflow_id=workflow.id)
    if existing is not None:
        raise WorkflowDraftConflictError(f"Workflow {workflow.id!r} already has an active draft")
    owner = await acquire_workflow_owner(session, workflow_id=workflow.id)
    existing = await _active_draft_row_for_update(session, workflow_id=workflow.id)
    if existing is not None:
        raise WorkflowDraftConflictError(f"Workflow {workflow.id!r} already has an active draft")
    return await _insert_workflow_draft(
        session,
        workflow=workflow,
        base_revision_no=owner.current_revision_no,
    )


async def _create_new_workflow_draft(
    session: AsyncSession,
    *,
    workflow: NormalizedWorkflow,
) -> WorkflowDraftReadback:
    existing = await _active_draft_row_for_update(session, workflow_id=workflow.id)
    if existing is not None:
        raise WorkflowDraftConflictError(f"Workflow {workflow.id!r} already has an active draft")
    owner = await acquire_workflow_owner(session, workflow_id=workflow.id)
    existing = await _active_draft_row_for_update(session, workflow_id=workflow.id)
    if existing is not None:
        raise WorkflowDraftConflictError(f"Workflow {workflow.id!r} already has an active draft")
    if owner.current_revision_no is not None:
        raise WorkflowDraftConflictError(f"Workflow {workflow.id!r} is already published")
    return await _insert_workflow_draft(
        session,
        workflow=workflow,
        base_revision_no=None,
    )


async def _open_existing_workflow_draft(
    session: AsyncSession,
    *,
    workflow_id: str,
) -> WorkflowDraftOpenResult:
    existing = await _active_draft_row_for_update(session, workflow_id=workflow_id)
    if existing is not None:
        return WorkflowDraftOpenResult(
            draft=map_workflow_draft_readback(existing),
            is_created=False,
        )
    owner = await acquire_workflow_owner(session, workflow_id=workflow_id)
    existing = await _active_draft_row_for_update(session, workflow_id=workflow_id)
    if existing is not None:
        return WorkflowDraftOpenResult(
            draft=map_workflow_draft_readback(existing),
            is_created=False,
        )
    if owner.current_revision_no is None:
        raise WorkflowNotFoundError(f"published Workflow {workflow_id!r} does not exist")
    published = await read_published_workflow_revision(
        session,
        workflow_id=workflow_id,
        revision_no=owner.current_revision_no,
    )
    return WorkflowDraftOpenResult(
        draft=await _insert_workflow_draft(
            session,
            workflow=published.workflow,
            base_revision_no=published.revision_no,
        ),
        is_created=True,
    )


async def _insert_workflow_draft(
    session: AsyncSession,
    *,
    workflow: NormalizedWorkflow,
    base_revision_no: int | None,
) -> WorkflowDraftReadback:
    row = WorkflowDraftModel(
        draft_id=new_workflow_draft_id(),
        workflow_key=workflow.id,
        base_revision_no=base_revision_no,
        content_hash=canonical_workflow_hash(workflow),
        content_json=workflow.model_dump(mode="json", exclude_none=True),
        etag=new_workflow_draft_etag(),
        next_member_sequence=next_workflow_member_sequence(workflow),
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(
            select(WorkflowDraftModel).where(WorkflowDraftModel.workflow_key == workflow.id)
        )
        if existing is None:
            raise
        raise WorkflowDraftConflictError(
            f"Workflow {workflow.id!r} already has an active draft"
        ) from None
    return map_workflow_draft_readback(row)


async def _has_published_revisions(
    session: AsyncSession,
    *,
    workflow_id: str,
) -> bool:
    revision_no = await session.scalar(
        select(WorkflowRevisionModel.revision_no)
        .where(WorkflowRevisionModel.workflow_key == workflow_id)
        .limit(1)
    )
    return revision_no is not None


async def _delete_draft_with_etag(
    session: AsyncSession,
    *,
    row: WorkflowDraftModel,
    expected_etag: str,
) -> None:
    deleted = await session.execute(
        delete(WorkflowDraftModel).where(
            WorkflowDraftModel.draft_id == row.draft_id,
            WorkflowDraftModel.etag == expected_etag,
        )
    )
    if cast(CursorResult[Any], deleted).rowcount == 1:
        return
    session.expire(row)
    current = await session.get(WorkflowDraftModel, row.draft_id)
    if current is None:
        raise WorkflowNotFoundError(f"Workflow draft {row.draft_id!r} does not exist")
    raise WorkflowStaleDraftError(map_workflow_draft_readback(current))


async def _current_draft_row(
    session: AsyncSession,
    *,
    draft_id: str,
    expected_etag: str,
) -> WorkflowDraftModel:
    row = await _draft_row_for_update(session, draft_id=draft_id)
    if row is None:
        raise WorkflowNotFoundError(f"Workflow draft {draft_id!r} does not exist")
    if row.etag != expected_etag:
        raise WorkflowStaleDraftError(map_workflow_draft_readback(row))
    return row


async def _draft_row_for_update(
    session: AsyncSession,
    *,
    draft_id: str,
) -> WorkflowDraftModel | None:
    await _lock_sqlite_draft_rows(
        session,
        where_clause=WorkflowDraftModel.draft_id == draft_id,
    )
    row = await session.scalar(
        select(WorkflowDraftModel).where(WorkflowDraftModel.draft_id == draft_id).with_for_update()
    )
    if row is not None:
        read_persisted_workflow(
            row.content_json,
            expected_workflow_id=row.workflow_key,
            source="Workflow draft",
        )
    return row


async def _active_draft_row_for_update(
    session: AsyncSession,
    *,
    workflow_id: str,
) -> WorkflowDraftModel | None:
    await _lock_sqlite_draft_rows(
        session,
        where_clause=WorkflowDraftModel.workflow_key == workflow_id,
    )
    row = cast(
        WorkflowDraftModel | None,
        await session.scalar(
            select(WorkflowDraftModel)
            .where(WorkflowDraftModel.workflow_key == workflow_id)
            .with_for_update()
        ),
    )
    if row is not None:
        read_persisted_workflow(
            row.content_json,
            expected_workflow_id=row.workflow_key,
            source="Workflow draft",
        )
    return row


async def _lock_sqlite_draft_rows(
    session: AsyncSession,
    *,
    where_clause: ColumnElement[bool],
) -> None:
    if session.get_bind().dialect.name != "sqlite":
        return
    table = cast(Table, WorkflowDraftModel.__table__)
    await session.execute(
        update(table)
        .where(where_clause)
        .values(draft_id=table.c.draft_id, updated_at=table.c.updated_at)
    )


__all__ = [
    "build_workflow_authoring_options",
    "discard_workflow_draft",
    "edit_workflow_draft",
    "import_workflow_draft",
    "open_workflow_draft",
    "publish_workflow_draft",
    "read_workflow_catalog_entry",
    "read_workflow_draft",
    "remove_workflow",
    "search_workflow_catalog",
    "undo_workflow_draft",
    "validate_workflow_draft",
]
