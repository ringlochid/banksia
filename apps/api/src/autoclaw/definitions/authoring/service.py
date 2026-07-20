from __future__ import annotations

from pathlib import Path
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.definitions.authoring.contracts import (
    DefinitionDraftCreateRequest,
    DefinitionDraftDetailResponse,
    DefinitionDraftListQuery,
    DefinitionDraftListResponse,
    DefinitionDraftMode,
    DefinitionDraftPublishResponse,
    DefinitionDraftValidationResponse,
    DefinitionDraftWriteRequest,
)
from autoclaw.definitions.authoring.publishing import publish_valid_definition_draft
from autoclaw.definitions.authoring.readback import (
    build_definition_draft_detail,
    build_saved_definition_draft_summary,
    load_current_definition_snapshot,
    next_cursor,
    parse_cursor_offset,
    parse_definition_body_for_storage,
    require_current_definition_snapshot,
)
from autoclaw.definitions.authoring.storage import (
    StoredDraftBaseline,
    build_definition_draft_metadata,
    delete_stored_definition_draft,
    has_stored_definition_draft,
    list_stored_definition_drafts,
    normalize_definition_content,
    read_stored_definition_draft,
    serialize_definition_content,
    write_stored_definition_draft,
)
from autoclaw.definitions.authoring.validation import validate_definition_draft
from autoclaw.definitions.contracts import DefinitionKind
from autoclaw.persistence.session_operations import write_session_operation
from autoclaw.runtime.errors import (
    invalid_request_shape_error,
    name_collision_error,
)


async def list_definition_drafts(
    session: AsyncSession,
    *,
    data_dir: Path,
    query: DefinitionDraftListQuery,
) -> DefinitionDraftListResponse:
    metadata = sorted(
        list_stored_definition_drafts(data_dir),
        key=lambda draft_metadata: draft_metadata.updated_at,
        reverse=True,
    )
    offset = parse_cursor_offset(query.cursor)
    selected = metadata[offset : offset + query.limit + 1]
    items = [
        await build_saved_definition_draft_summary(
            session,
            data_dir=data_dir,
            metadata=draft_metadata,
        )
        for draft_metadata in selected[: query.limit]
    ]
    return DefinitionDraftListResponse(
        items=tuple(items),
        next_cursor=next_cursor(offset, query.limit, len(selected)),
    )


async def create_definition_draft(
    session: AsyncSession,
    *,
    data_dir: Path,
    request: DefinitionDraftCreateRequest,
) -> DefinitionDraftDetailResponse:
    if has_stored_definition_draft(data_dir, kind=request.kind, key=request.key):
        raise name_collision_error(
            f"definition draft '{request.kind.value}:{request.key}' already exists"
        )
    if request.body_format != "yaml":
        raise invalid_request_shape_error("draft body_format must be yaml")
    current_snapshot = await load_current_definition_snapshot(
        session,
        kind=request.kind,
        key=request.key,
    )
    if request.mode == DefinitionDraftMode.CREATE:
        if current_snapshot is not None:
            raise name_collision_error(f"{request.kind.value} '{request.key}' already exists")
        assert request.body is not None
        body = request.body
        based_on = StoredDraftBaseline()
        baseline_body = body
        baseline_normalized_content = parse_definition_body_for_storage(
            kind=request.kind,
            key=request.key,
            body=body,
        ).normalized_content
    else:
        current_snapshot = await require_current_definition_snapshot(
            session,
            kind=request.kind,
            key=request.key,
        )
        body = request.body or serialize_definition_content(request.kind, current_snapshot.content)
        based_on = StoredDraftBaseline(
            revision_no=current_snapshot.revision_no,
            content_hash=current_snapshot.content_hash,
            source_path=current_snapshot.source_path,
        )
        baseline_body = serialize_definition_content(request.kind, current_snapshot.content)
        baseline_normalized_content = normalize_definition_content(current_snapshot.content)

    parsed = parse_definition_body_for_storage(kind=request.kind, key=request.key, body=body)
    metadata = build_definition_draft_metadata(
        kind=request.kind,
        key=request.key,
        mode=request.mode,
        body=body,
        based_on=based_on,
        baseline_body=baseline_body,
        baseline_normalized_content=baseline_normalized_content,
    )
    write_stored_definition_draft(
        data_dir,
        metadata=metadata,
        body=body,
        normalized_content=parsed.normalized_content,
    )
    return await read_definition_draft(
        session,
        data_dir=data_dir,
        kind=request.kind,
        key=request.key,
    )


async def write_definition_draft(
    session: AsyncSession,
    *,
    data_dir: Path,
    kind: DefinitionKind,
    key: str,
    request: DefinitionDraftWriteRequest,
) -> DefinitionDraftDetailResponse:
    if request.body_format != "yaml":
        raise invalid_request_shape_error("draft body_format must be yaml")
    if has_stored_definition_draft(data_dir, kind=kind, key=key):
        draft = read_stored_definition_draft(data_dir, kind=kind, key=key)
        metadata = build_definition_draft_metadata(
            kind=kind,
            key=key,
            mode=draft.metadata.mode,
            body=request.body,
            based_on=draft.metadata.based_on,
            baseline_body=draft.metadata.baseline_body,
            baseline_normalized_content=draft.metadata.baseline_normalized_content,
            created_at=draft.metadata.created_at,
        )
    else:
        current_snapshot = await load_current_definition_snapshot(session, kind=kind, key=key)
        if current_snapshot is None:
            metadata = build_definition_draft_metadata(
                kind=kind,
                key=key,
                mode=DefinitionDraftMode.CREATE,
                body=request.body,
                based_on=StoredDraftBaseline(),
                baseline_body=request.body,
                baseline_normalized_content=parse_definition_body_for_storage(
                    kind=kind,
                    key=key,
                    body=request.body,
                ).normalized_content,
            )
        else:
            metadata = build_definition_draft_metadata(
                kind=kind,
                key=key,
                mode=DefinitionDraftMode.UPDATE,
                body=request.body,
                based_on=StoredDraftBaseline(
                    revision_no=current_snapshot.revision_no,
                    content_hash=current_snapshot.content_hash,
                    source_path=current_snapshot.source_path,
                ),
                baseline_body=serialize_definition_content(kind, current_snapshot.content),
                baseline_normalized_content=normalize_definition_content(current_snapshot.content),
            )

    parsed = parse_definition_body_for_storage(kind=kind, key=key, body=request.body)
    write_stored_definition_draft(
        data_dir,
        metadata=metadata,
        body=request.body,
        normalized_content=parsed.normalized_content,
    )
    return await read_definition_draft(session, data_dir=data_dir, kind=kind, key=key)


async def replace_definition_draft_with_current_revision(
    session: AsyncSession,
    *,
    data_dir: Path,
    kind: DefinitionKind,
    key: str,
) -> DefinitionDraftDetailResponse:
    draft = read_stored_definition_draft(data_dir, kind=kind, key=key)
    if draft.metadata.mode != DefinitionDraftMode.UPDATE:
        raise invalid_request_shape_error("replace-current requires an update draft")

    current_snapshot = await require_current_definition_snapshot(session, kind=kind, key=key)
    body = serialize_definition_content(kind, current_snapshot.content)
    normalized_content = normalize_definition_content(current_snapshot.content)
    metadata = build_definition_draft_metadata(
        kind=kind,
        key=key,
        mode=DefinitionDraftMode.UPDATE,
        body=body,
        based_on=StoredDraftBaseline(
            revision_no=current_snapshot.revision_no,
            content_hash=current_snapshot.content_hash,
            source_path=current_snapshot.source_path,
        ),
        baseline_body=body,
        baseline_normalized_content=normalized_content,
        created_at=draft.metadata.created_at,
    )
    write_stored_definition_draft(
        data_dir,
        metadata=metadata,
        body=body,
        normalized_content=normalized_content,
    )
    return await read_definition_draft(session, data_dir=data_dir, kind=kind, key=key)


async def read_definition_draft(
    session: AsyncSession,
    *,
    data_dir: Path,
    kind: DefinitionKind,
    key: str,
) -> DefinitionDraftDetailResponse:
    return DefinitionDraftDetailResponse(
        draft=await build_definition_draft_detail(session, data_dir=data_dir, kind=kind, key=key)
    )


def delete_definition_draft(*, data_dir: Path, kind: DefinitionKind, key: str) -> None:
    delete_stored_definition_draft(data_dir, kind=kind, key=key)


async def validate_saved_definition_draft(
    session: AsyncSession,
    *,
    data_dir: Path,
    kind: DefinitionKind,
    key: str,
) -> DefinitionDraftValidationResponse:
    draft = read_stored_definition_draft(data_dir, kind=kind, key=key)
    return (await validate_definition_draft(session, draft=draft)).response


async def publish_definition_draft(
    session: AsyncSession | None,
    *,
    data_dir: Path,
    kind: DefinitionKind,
    key: str,
) -> DefinitionDraftPublishResponse:
    draft = read_stored_definition_draft(data_dir, kind=kind, key=key)

    async def publish(active_session: AsyncSession) -> DefinitionDraftPublishResponse:
        outcome = await validate_definition_draft(active_session, draft=draft)
        if outcome.response.status != "valid" or outcome.content is None:
            return DefinitionDraftPublishResponse(
                kind=kind,
                key=key,
                status=publish_block_status(outcome.response.status),
                published_revision=None,
                validation=outcome.response,
            )
        published_revision = await publish_valid_definition_draft(
            active_session,
            draft=draft,
            content=outcome.content,
            current_snapshot=outcome.current_snapshot,
        )
        return DefinitionDraftPublishResponse(
            kind=kind,
            key=key,
            status="published",
            published_revision=published_revision,
            validation=outcome.response,
        )

    response = await write_session_operation(publish, session=session)
    if response.status == "published":
        delete_stored_definition_draft(data_dir, kind=kind, key=key)
    return response


def publish_block_status(
    validation_status: str,
) -> Literal["invalid", "stale", "name_collision"]:
    if validation_status == "name_collision":
        return "name_collision"
    if validation_status == "stale":
        return "stale"
    return "invalid"


__all__ = [
    "create_definition_draft",
    "delete_definition_draft",
    "list_definition_drafts",
    "publish_definition_draft",
    "read_definition_draft",
    "replace_definition_draft_with_current_revision",
    "validate_saved_definition_draft",
    "write_definition_draft",
]
