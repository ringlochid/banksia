from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from autoclaw.definitions.contracts.registry import (
    DefinitionContent,
    DefinitionKind,
    DefinitionListQuery,
    DefinitionListSort,
    DefinitionRevisionDetailResponse,
    DefinitionSummaryListResponse,
    DefinitionSummaryRead,
    DefinitionUploadRequest,
    PolicyDefinitionInput,
    RoleDefinitionInput,
)
from autoclaw.definitions.contracts.workflow import (
    NodeDefinitionInput,
    RootNodeDefinition,
    WorkflowDefinitionInput,
)
from autoclaw.definitions.registry.revisions.ids import canonical_content_hash
from autoclaw.definitions.registry.revisions.reads import load_current_definition_revision_rows
from autoclaw.definitions.registry.upsert import (
    upsert_policy_definition,
    upsert_role_definition,
    upsert_workflow_definition,
)
from autoclaw.persistence.models import (
    PolicyDefinitionModel,
    PolicyRevisionModel,
    RoleDefinitionModel,
    RoleRevisionModel,
    WorkflowDefinitionModel,
    WorkflowRevisionModel,
)
from autoclaw.persistence.session_operations import write_session_operation
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.errors import RuntimeOperationError, invalid_request_shape_error


@dataclass(frozen=True)
class DefinitionUploadResult:
    detail: DefinitionRevisionDetailResponse
    is_created: bool

    @property
    def created(self) -> bool:
        return self.is_created


async def upload_definition(
    request: DefinitionUploadRequest,
    *,
    session: AsyncSession | None = None,
) -> DefinitionUploadResult:
    return await write_session_operation(
        lambda active_session: _upload_definition(active_session, request),
        session=session,
    )


async def list_role_definitions(
    session: AsyncSession,
    query: DefinitionListQuery,
) -> DefinitionSummaryListResponse:
    if query.applies_to is not None:
        raise invalid_request_shape_error("applies_to is not supported on /definitions/roles")
    rows = await load_current_definition_revision_rows(
        session,
        RoleDefinitionModel,
        RoleRevisionModel,
        definition_key=RoleDefinitionModel.role_key,
        revision_key=RoleRevisionModel.role_key,
        current_revision_no=RoleDefinitionModel.current_revision_no,
    )
    items = [
        DefinitionSummaryRead(
            key=definition_row.role_key,
            title=definition.title,
            description=definition.description,
            current_revision_no=revision_row.revision_no,
            allowed_node_kinds=tuple(definition.allowed_node_kinds),
            labels=tuple(definition.labels),
            updated_at=coerce_utc(definition_row.updated_at),
        )
        for definition_row, revision_row in rows
        for definition in [RoleDefinitionInput.model_validate(revision_row.content_json)]
        if _matches_query(
            query.q,
            definition_row.role_key,
            definition.title,
            definition.description,
            definition.instruction,
            *definition.labels,
        )
        and (
            query.allowed_node_kind is None
            or query.allowed_node_kind in definition.allowed_node_kinds
        )
    ]
    return _page_definition_summaries(DefinitionKind.ROLE, items, query)


async def list_policy_definitions(
    session: AsyncSession,
    query: DefinitionListQuery,
) -> DefinitionSummaryListResponse:
    if query.allowed_node_kind is not None:
        raise invalid_request_shape_error(
            "allowed_node_kind is not supported on /definitions/policies"
        )
    rows = await load_current_definition_revision_rows(
        session,
        PolicyDefinitionModel,
        PolicyRevisionModel,
        definition_key=PolicyDefinitionModel.policy_key,
        revision_key=PolicyRevisionModel.policy_key,
        current_revision_no=PolicyDefinitionModel.current_revision_no,
    )
    items = [
        DefinitionSummaryRead(
            key=definition_row.policy_key,
            title=definition.title,
            description=definition.description,
            current_revision_no=revision_row.revision_no,
            applies_to=tuple(definition.applies_to),
            budget_spec=definition.budget_spec,
            labels=tuple(definition.labels),
            updated_at=coerce_utc(definition_row.updated_at),
        )
        for definition_row, revision_row in rows
        for definition in [PolicyDefinitionInput.model_validate(revision_row.content_json)]
        if _matches_query(
            query.q,
            definition_row.policy_key,
            definition.title,
            definition.description,
            definition.instruction,
            *definition.labels,
        )
        and (query.applies_to is None or query.applies_to in definition.applies_to)
    ]
    return _page_definition_summaries(DefinitionKind.POLICY, items, query)


async def list_workflow_definitions(
    session: AsyncSession,
    query: DefinitionListQuery,
) -> DefinitionSummaryListResponse:
    if query.allowed_node_kind is not None or query.applies_to is not None:
        raise invalid_request_shape_error(
            "route-specific node-kind filters are not supported on /definitions/workflows"
        )
    rows = await load_current_definition_revision_rows(
        session,
        WorkflowDefinitionModel,
        WorkflowRevisionModel,
        definition_key=WorkflowDefinitionModel.workflow_key,
        revision_key=WorkflowRevisionModel.workflow_key,
        current_revision_no=WorkflowDefinitionModel.current_revision_no,
    )
    items = [
        DefinitionSummaryRead(
            key=definition_row.workflow_key,
            description=definition.description,
            current_revision_no=revision_row.revision_no,
            updated_at=coerce_utc(definition_row.updated_at),
        )
        for definition_row, revision_row in rows
        for definition in [WorkflowDefinitionInput.model_validate(revision_row.content_json)]
        if _matches_query(
            query.q,
            definition_row.workflow_key,
            *_workflow_search_fields(definition),
        )
    ]
    return _page_definition_summaries(DefinitionKind.WORKFLOW, items, query)


async def get_definition_detail(
    session: AsyncSession,
    kind: DefinitionKind,
    key: str,
) -> DefinitionRevisionDetailResponse:
    if kind == DefinitionKind.ROLE:
        definition_row = await session.scalar(
            select(RoleDefinitionModel)
            .options(joinedload(RoleDefinitionModel.current_revision))
            .where(RoleDefinitionModel.role_key == key)
        )
    elif kind == DefinitionKind.POLICY:
        definition_row = await session.scalar(
            select(PolicyDefinitionModel)
            .options(joinedload(PolicyDefinitionModel.current_revision))
            .where(PolicyDefinitionModel.policy_key == key)
        )
    else:
        definition_row = await session.scalar(
            select(WorkflowDefinitionModel)
            .options(joinedload(WorkflowDefinitionModel.current_revision))
            .where(WorkflowDefinitionModel.workflow_key == key)
        )
    return _definition_detail_from_row(kind, key, definition_row)


def coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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


def next_page_cursor(offset: int, limit: int, selected_count: int) -> str | None:
    return str(offset + limit) if selected_count > limit else None


def _definition_invalid_error(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.INVALID_REQUEST_SHAPE,
        summary=summary,
        is_retryable=False,
        suggested_next_step=(
            "Reread the canonical request shape and resend the request with only the live "
            "required fields."
        ),
        status_code_override=422,
    )


def _matches_query(query: str | None, *fields: str | None) -> bool:
    if query is None:
        return True
    needle = query.casefold()
    return any(field is not None and needle in field.casefold() for field in fields)


def _workflow_search_fields(definition: WorkflowDefinitionInput) -> tuple[str, ...]:
    descriptions = [definition.description]
    _collect_node_descriptions(definition.root, descriptions)
    return tuple(descriptions)


def _collect_node_descriptions(
    node: RootNodeDefinition | NodeDefinitionInput,
    descriptions: list[str],
) -> None:
    descriptions.append(node.description)
    for child in node.children or ():
        _collect_node_descriptions(child, descriptions)


def _sort_definition_summaries(
    items: list[DefinitionSummaryRead],
    sort: DefinitionListSort,
) -> list[DefinitionSummaryRead]:
    if sort == DefinitionListSort.UPDATED_AT_DESC:
        return sorted(items, key=lambda item: (item.updated_at, item.key.casefold()), reverse=True)
    if sort == DefinitionListSort.UPDATED_AT_ASC:
        return sorted(items, key=lambda item: (item.updated_at, item.key.casefold()))
    if sort == DefinitionListSort.KEY_DESC:
        return sorted(items, key=lambda item: item.key.casefold(), reverse=True)
    return sorted(items, key=lambda item: item.key.casefold())


def _page_definition_summaries(
    kind: DefinitionKind,
    items: list[DefinitionSummaryRead],
    query: DefinitionListQuery,
) -> DefinitionSummaryListResponse:
    offset = parse_cursor_offset(query.cursor)
    ordered = _sort_definition_summaries(items, query.sort)
    selected = ordered[offset : offset + query.limit + 1]
    return DefinitionSummaryListResponse(
        kind=kind,
        items=tuple(selected[: query.limit]),
        next_cursor=next_page_cursor(offset, query.limit, len(selected)),
    )


def _content_from_kind(kind: DefinitionKind, payload: dict[str, object]) -> DefinitionContent:
    if kind == DefinitionKind.ROLE:
        return RoleDefinitionInput.model_validate(payload)
    if kind == DefinitionKind.POLICY:
        return PolicyDefinitionInput.model_validate(payload)
    return WorkflowDefinitionInput.model_validate(payload)


def _definition_detail_from_row(
    kind: DefinitionKind,
    key: str,
    definition_row: RoleDefinitionModel | PolicyDefinitionModel | WorkflowDefinitionModel | None,
) -> DefinitionRevisionDetailResponse:
    if definition_row is None:
        raise FileNotFoundError(f"unknown definition key '{key}'")
    if definition_row.current_revision_no is None or definition_row.current_revision is None:
        raise _definition_invalid_error(
            f"missing current revision pointer for {kind.value} '{key}'"
        )
    revision = definition_row.current_revision
    return DefinitionRevisionDetailResponse(
        key=key,
        revision_no=revision.revision_no,
        content=_content_from_kind(kind, revision.content_json),
        recorded_by=None,
        updated_at=coerce_utc(definition_row.updated_at),
    )


async def _upload_definition(
    session: AsyncSession,
    request: DefinitionUploadRequest,
) -> DefinitionUploadResult:
    current_hash = await _current_content_hash(session, request.kind, request.content.id)
    content_hash = canonical_content_hash(request.content.model_dump(mode="json"))
    try:
        if request.kind == DefinitionKind.ROLE:
            await upsert_role_definition(
                session,
                cast(RoleDefinitionInput, request.content),
                source_path=None,
            )
        elif request.kind == DefinitionKind.POLICY:
            await upsert_policy_definition(
                session,
                cast(PolicyDefinitionInput, request.content),
                source_path=None,
            )
        else:
            await upsert_workflow_definition(
                session,
                cast(WorkflowDefinitionInput, request.content),
                source_path=None,
            )
    except ValueError as exc:
        raise _definition_invalid_error(str(exc)) from exc
    return DefinitionUploadResult(
        detail=await get_definition_detail(session, request.kind, request.content.id),
        is_created=current_hash is None or current_hash != content_hash,
    )


async def _current_content_hash(
    session: AsyncSession,
    kind: DefinitionKind,
    key: str,
) -> str | None:
    try:
        detail = await get_definition_detail(session, kind, key)
    except FileNotFoundError:
        return None
    return canonical_content_hash(detail.content.model_dump(mode="json"))


__all__ = [
    "DefinitionUploadResult",
    "coerce_utc",
    "get_definition_detail",
    "list_policy_definitions",
    "list_role_definitions",
    "list_workflow_definitions",
    "next_page_cursor",
    "parse_cursor_offset",
    "upload_definition",
]
