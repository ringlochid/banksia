from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.definitions.contracts import (
    DefinitionKind,
    DefinitionListQuery,
    DefinitionRevisionDetailResponse,
    DefinitionRevisionHistoryQuery,
    DefinitionRevisionHistoryResponse,
    DefinitionSummaryListResponse,
    DefinitionUploadRequest,
)
from autoclaw.definitions.registry.definition_catalog import (
    get_definition_detail,
    list_policy_definitions,
    list_role_definitions,
    list_workflow_definitions,
    upload_definition,
)
from autoclaw.definitions.registry.definition_history import get_definition_history
from autoclaw.interfaces.http.errors import raise_runtime_exception
from autoclaw.persistence.session import get_db_session

router = APIRouter(prefix="/definitions", tags=["definitions"])
type DBSession = Annotated[AsyncSession, Depends(get_db_session)]
type DefinitionListParams = Annotated[DefinitionListQuery, Query()]
type DefinitionHistoryParams = Annotated[DefinitionRevisionHistoryQuery, Query()]


@router.get("/roles", response_model=DefinitionSummaryListResponse)
async def get_role_definitions(
    session: DBSession,
    query: DefinitionListParams,
) -> DefinitionSummaryListResponse:
    try:
        return await list_role_definitions(session, query)
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.get("/policies", response_model=DefinitionSummaryListResponse)
async def get_policy_definitions(
    session: DBSession,
    query: DefinitionListParams,
) -> DefinitionSummaryListResponse:
    try:
        return await list_policy_definitions(session, query)
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.get("/workflows", response_model=DefinitionSummaryListResponse)
async def get_workflow_definitions(
    session: DBSession,
    query: DefinitionListParams,
) -> DefinitionSummaryListResponse:
    try:
        return await list_workflow_definitions(session, query)
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.get("/{kind}/{key}", response_model=DefinitionRevisionDetailResponse)
async def get_definition(
    kind: DefinitionKind,
    key: str,
    session: DBSession,
) -> DefinitionRevisionDetailResponse:
    try:
        return await get_definition_detail(session, kind, key)
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.get("/{kind}/{key}/versions", response_model=DefinitionRevisionHistoryResponse)
async def get_definition_versions(
    kind: DefinitionKind,
    key: str,
    session: DBSession,
    query: DefinitionHistoryParams,
) -> DefinitionRevisionHistoryResponse:
    try:
        return await get_definition_history(session, kind, key, query)
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.post("", response_model=DefinitionRevisionDetailResponse)
async def post_definition(
    request: DefinitionUploadRequest,
    response: Response,
    session: DBSession,
) -> DefinitionRevisionDetailResponse:
    try:
        result = await upload_definition(request, session=session)
        response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
        return result.detail
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)
