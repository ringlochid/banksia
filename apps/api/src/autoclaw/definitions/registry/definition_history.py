from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from autoclaw.definitions.contracts.registry import (
    DefinitionHistorySort,
    DefinitionKind,
    DefinitionRevisionDetailResponse,
    DefinitionRevisionHistoryEntry,
    DefinitionRevisionHistoryQuery,
    DefinitionRevisionHistoryResponse,
)
from autoclaw.definitions.registry.definition_catalog import (
    coerce_utc,
    get_definition_detail,
    next_page_cursor,
    parse_cursor_offset,
)
from autoclaw.persistence.models import (
    PolicyRevisionModel,
    RoleRevisionModel,
    WorkflowRevisionModel,
)

type RevisionStamp = tuple[int, datetime]


async def get_definition_history(
    session: AsyncSession,
    kind: DefinitionKind,
    key: str,
    query: DefinitionRevisionHistoryQuery,
) -> DefinitionRevisionHistoryResponse:
    detail = await get_definition_detail(session, kind, key)
    offset = parse_cursor_offset(query.cursor)
    if kind == DefinitionKind.ROLE:
        role_revisions = (
            await session.scalars(
                select(RoleRevisionModel)
                .where(RoleRevisionModel.role_key == key)
                .order_by(_role_history_ordering(query.sort))
            )
        ).all()
        return _history_response(
            detail,
            kind,
            offset,
            query.limit,
            [(row.revision_no, row.created_at) for row in role_revisions],
        )
    if kind == DefinitionKind.POLICY:
        policy_revisions = (
            await session.scalars(
                select(PolicyRevisionModel)
                .where(PolicyRevisionModel.policy_key == key)
                .order_by(_policy_history_ordering(query.sort))
            )
        ).all()
        return _history_response(
            detail,
            kind,
            offset,
            query.limit,
            [(row.revision_no, row.created_at) for row in policy_revisions],
        )
    workflow_revisions = (
        await session.scalars(
            select(WorkflowRevisionModel)
            .where(WorkflowRevisionModel.workflow_key == key)
            .order_by(_workflow_history_ordering(query.sort))
        )
    ).all()
    return _history_response(
        detail,
        kind,
        offset,
        query.limit,
        [(row.revision_no, row.created_at) for row in workflow_revisions],
    )


def _history_response(
    detail: DefinitionRevisionDetailResponse,
    kind: DefinitionKind,
    offset: int,
    limit: int,
    revisions: Sequence[RevisionStamp],
) -> DefinitionRevisionHistoryResponse:
    selected = revisions[offset : offset + limit + 1]
    items = tuple(
        DefinitionRevisionHistoryEntry(
            revision_no=revision_no,
            recorded_by=None,
            updated_at=coerce_utc(created_at),
        )
        for revision_no, created_at in selected[:limit]
    )
    return DefinitionRevisionHistoryResponse(
        key=detail.key,
        kind=kind,
        current_revision_no=detail.revision_no,
        items=items,
        next_cursor=next_page_cursor(offset, limit, len(selected)),
    )


def _role_history_ordering(sort: DefinitionHistorySort) -> ColumnElement[Any]:
    if sort == DefinitionHistorySort.REVISION_NO_ASC:
        return RoleRevisionModel.revision_no.asc()
    if sort == DefinitionHistorySort.UPDATED_AT_DESC:
        return RoleRevisionModel.created_at.desc()
    if sort == DefinitionHistorySort.UPDATED_AT_ASC:
        return RoleRevisionModel.created_at.asc()
    return RoleRevisionModel.revision_no.desc()


def _policy_history_ordering(sort: DefinitionHistorySort) -> ColumnElement[Any]:
    if sort == DefinitionHistorySort.REVISION_NO_ASC:
        return PolicyRevisionModel.revision_no.asc()
    if sort == DefinitionHistorySort.UPDATED_AT_DESC:
        return PolicyRevisionModel.created_at.desc()
    if sort == DefinitionHistorySort.UPDATED_AT_ASC:
        return PolicyRevisionModel.created_at.asc()
    return PolicyRevisionModel.revision_no.desc()


def _workflow_history_ordering(sort: DefinitionHistorySort) -> ColumnElement[Any]:
    if sort == DefinitionHistorySort.REVISION_NO_ASC:
        return WorkflowRevisionModel.revision_no.asc()
    if sort == DefinitionHistorySort.UPDATED_AT_DESC:
        return WorkflowRevisionModel.created_at.desc()
    if sort == DefinitionHistorySort.UPDATED_AT_ASC:
        return WorkflowRevisionModel.created_at.asc()
    return WorkflowRevisionModel.revision_no.desc()


__all__ = ["get_definition_history"]
