from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from autoclaw.definitions.authoring.contracts import (
    DefinitionDraftBaselineRead,
    DefinitionDraftDetail,
    DefinitionDraftMode,
    DefinitionDraftStatus,
    DefinitionDraftSummary,
)
from autoclaw.definitions.authoring.storage import (
    StoredDefinitionDraftMetadata,
    StoredDraftBaseline,
    build_definition_draft_metadata,
    draft_body_content_hash,
    has_stored_definition_draft,
    normalize_definition_content,
    parse_definition_body,
    read_stored_definition_draft,
    serialize_definition_content,
)
from autoclaw.definitions.contracts import (
    DefinitionContent,
    DefinitionKind,
    PolicyDefinitionInput,
    RoleDefinitionInput,
    WorkflowDefinitionInput,
)
from autoclaw.persistence.models import (
    PolicyDefinitionModel,
    RoleDefinitionModel,
    WorkflowDefinitionModel,
)
from autoclaw.runtime.errors import invalid_request_shape_error


@dataclass(frozen=True)
class CurrentDefinitionSnapshot:
    kind: DefinitionKind
    key: str
    content: DefinitionContent
    revision_no: int
    content_hash: str
    source_path: str | None


@dataclass(frozen=True)
class ParsedDraftDefinition:
    content: DefinitionContent | None
    normalized_content: dict[str, Any] | None
    error: str | None


async def build_saved_definition_draft_summary(
    session: AsyncSession,
    *,
    data_dir: Path,
    metadata: StoredDefinitionDraftMetadata,
) -> DefinitionDraftSummary:
    draft = read_stored_definition_draft(data_dir, kind=metadata.kind, key=metadata.key)
    current_snapshot = await load_current_definition_snapshot(
        session,
        kind=metadata.kind,
        key=metadata.key,
    )
    parsed = parse_definition_body_for_storage(
        kind=metadata.kind,
        key=metadata.key,
        body=draft.body,
    )
    return build_definition_draft_summary(
        metadata=metadata,
        body=draft.body,
        parsed=parsed,
        current_snapshot=current_snapshot,
    )


async def build_definition_draft_detail(
    session: AsyncSession,
    *,
    data_dir: Path,
    kind: DefinitionKind,
    key: str,
) -> DefinitionDraftDetail:
    if not has_stored_definition_draft(data_dir, kind=kind, key=key):
        current_snapshot = await require_current_definition_snapshot(session, kind=kind, key=key)
        return build_transient_current_definition_draft(current_snapshot)

    draft = read_stored_definition_draft(data_dir, kind=kind, key=key)
    saved_current_snapshot = await load_current_definition_snapshot(session, kind=kind, key=key)
    parsed = parse_definition_body_for_storage(kind=kind, key=key, body=draft.body)
    summary = build_definition_draft_summary(
        metadata=draft.metadata,
        body=draft.body,
        parsed=parsed,
        current_snapshot=saved_current_snapshot,
    )
    return DefinitionDraftDetail(
        **summary.model_dump(mode="python"),
        body=draft.body,
        normalized_content=draft.normalized_content,
        baseline_body=draft.metadata.baseline_body,
        baseline_normalized_content=draft.metadata.baseline_normalized_content,
        is_saved=True,
    )


def build_transient_current_definition_draft(
    current_snapshot: CurrentDefinitionSnapshot,
) -> DefinitionDraftDetail:
    body = serialize_definition_content(current_snapshot.kind, current_snapshot.content)
    normalized_content = normalize_definition_content(current_snapshot.content)
    metadata = build_definition_draft_metadata(
        kind=current_snapshot.kind,
        key=current_snapshot.key,
        mode=DefinitionDraftMode.UPDATE,
        body=body,
        based_on=StoredDraftBaseline(
            revision_no=current_snapshot.revision_no,
            content_hash=current_snapshot.content_hash,
            source_path=current_snapshot.source_path,
        ),
        baseline_body=body,
        baseline_normalized_content=normalized_content,
    )
    summary = build_definition_draft_summary(
        metadata=metadata,
        body=body,
        parsed=ParsedDraftDefinition(
            content=current_snapshot.content,
            normalized_content=normalized_content,
            error=None,
        ),
        current_snapshot=current_snapshot,
    )
    return DefinitionDraftDetail(
        **summary.model_dump(mode="python"),
        body=body,
        normalized_content=normalized_content,
        baseline_body=body,
        baseline_normalized_content=normalized_content,
        is_saved=False,
    )


def build_definition_draft_summary(
    *,
    metadata: StoredDefinitionDraftMetadata,
    body: str,
    parsed: ParsedDraftDefinition,
    current_snapshot: CurrentDefinitionSnapshot | None,
) -> DefinitionDraftSummary:
    return DefinitionDraftSummary(
        kind=metadata.kind,
        key=metadata.key,
        mode=metadata.mode,
        draft_path=metadata.draft_path,
        normalized_path=metadata.normalized_path,
        body_format="yaml",
        content_hash=draft_body_content_hash(body),
        based_on=DefinitionDraftBaselineRead.model_validate(
            metadata.based_on.model_dump(mode="python")
        ),
        status=definition_draft_status(
            metadata=metadata,
            body=body,
            parsed=parsed,
            current_snapshot=current_snapshot,
        ),
        updated_at=metadata.updated_at,
    )


def definition_draft_status(
    *,
    metadata: StoredDefinitionDraftMetadata,
    body: str,
    parsed: ParsedDraftDefinition,
    current_snapshot: CurrentDefinitionSnapshot | None,
) -> DefinitionDraftStatus:
    if parsed.error is not None:
        return DefinitionDraftStatus.INVALID
    if definition_draft_is_stale(metadata, current_snapshot=current_snapshot):
        return DefinitionDraftStatus.STALE
    if metadata.mode == DefinitionDraftMode.CREATE:
        return DefinitionDraftStatus.NEW
    if metadata.baseline_body is not None and body == metadata.baseline_body:
        return DefinitionDraftStatus.CLEAN
    return DefinitionDraftStatus.MODIFIED


def definition_draft_is_stale(
    metadata: StoredDefinitionDraftMetadata,
    *,
    current_snapshot: CurrentDefinitionSnapshot | None,
) -> bool:
    if metadata.mode == DefinitionDraftMode.CREATE:
        return current_snapshot is not None
    if current_snapshot is None:
        return True
    return (
        metadata.based_on.revision_no != current_snapshot.revision_no
        or metadata.based_on.content_hash != current_snapshot.content_hash
    )


async def require_current_definition_snapshot(
    session: AsyncSession,
    *,
    kind: DefinitionKind,
    key: str,
) -> CurrentDefinitionSnapshot:
    snapshot = await load_current_definition_snapshot(session, kind=kind, key=key)
    if snapshot is None:
        raise FileNotFoundError(f"unknown definition key '{key}'")
    return snapshot


async def load_current_definition_snapshot(
    session: AsyncSession,
    *,
    kind: DefinitionKind,
    key: str,
) -> CurrentDefinitionSnapshot | None:
    if kind == DefinitionKind.ROLE:
        row = await session.scalar(
            select(RoleDefinitionModel)
            .options(joinedload(RoleDefinitionModel.current_revision))
            .where(RoleDefinitionModel.role_key == key)
        )
        if row is None or row.current_revision is None or row.current_revision_no is None:
            return None
        return CurrentDefinitionSnapshot(
            kind=kind,
            key=key,
            content=RoleDefinitionInput.model_validate(row.current_revision.content_json),
            revision_no=row.current_revision.revision_no,
            content_hash=row.current_revision.content_hash,
            source_path=row.current_revision.source_path,
        )

    if kind == DefinitionKind.POLICY:
        row = await session.scalar(
            select(PolicyDefinitionModel)
            .options(joinedload(PolicyDefinitionModel.current_revision))
            .where(PolicyDefinitionModel.policy_key == key)
        )
        if row is None or row.current_revision is None or row.current_revision_no is None:
            return None
        return CurrentDefinitionSnapshot(
            kind=kind,
            key=key,
            content=PolicyDefinitionInput.model_validate(row.current_revision.content_json),
            revision_no=row.current_revision.revision_no,
            content_hash=row.current_revision.content_hash,
            source_path=row.current_revision.source_path,
        )

    row = await session.scalar(
        select(WorkflowDefinitionModel)
        .options(joinedload(WorkflowDefinitionModel.current_revision))
        .where(WorkflowDefinitionModel.workflow_key == key)
    )
    if row is None or row.current_revision is None or row.current_revision_no is None:
        return None
    return CurrentDefinitionSnapshot(
        kind=kind,
        key=key,
        content=WorkflowDefinitionInput.model_validate(row.current_revision.content_json),
        revision_no=row.current_revision.revision_no,
        content_hash=row.current_revision.content_hash,
        source_path=row.current_revision.source_path,
    )


def parse_definition_body_for_storage(
    *,
    kind: DefinitionKind,
    key: str,
    body: str,
) -> ParsedDraftDefinition:
    try:
        content = parse_definition_body(kind, key, body)
    except ValueError as exc:
        return ParsedDraftDefinition(content=None, normalized_content=None, error=str(exc))
    return ParsedDraftDefinition(
        content=content,
        normalized_content=normalize_definition_content(content),
        error=None,
    )


def parse_cursor_offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        offset = int(cursor)
    except ValueError as exc:
        raise invalid_request_shape_error("cursor must be an integer offset") from exc
    if offset < 0:
        raise invalid_request_shape_error("cursor must be non-negative")
    return offset


def next_cursor(offset: int, limit: int, selected_count: int) -> str | None:
    return str(offset + limit) if selected_count > limit else None


__all__ = [
    "CurrentDefinitionSnapshot",
    "ParsedDraftDefinition",
    "build_definition_draft_detail",
    "build_definition_draft_summary",
    "build_saved_definition_draft_summary",
    "build_transient_current_definition_draft",
    "definition_draft_is_stale",
    "definition_draft_status",
    "load_current_definition_snapshot",
    "next_cursor",
    "parse_cursor_offset",
    "parse_definition_body_for_storage",
    "require_current_definition_snapshot",
]
