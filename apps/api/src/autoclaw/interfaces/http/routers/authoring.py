from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.config import get_settings
from autoclaw.definitions.authoring import (
    DefinitionDraftCreateRequest,
    DefinitionDraftDetailResponse,
    DefinitionDraftListQuery,
    DefinitionDraftListResponse,
    DefinitionDraftPublishResponse,
    DefinitionDraftValidationResponse,
    DefinitionDraftWriteRequest,
    create_definition_draft,
    delete_definition_draft,
    list_definition_drafts,
    publish_definition_draft,
    read_definition_draft,
    replace_definition_draft_with_current_revision,
    validate_saved_definition_draft,
    write_definition_draft,
)
from autoclaw.definitions.contracts import DefinitionKind
from autoclaw.definitions.registry.task_start import preview_task_compose
from autoclaw.interfaces.http.dependencies import read_dispatch_opening_dependencies
from autoclaw.interfaces.http.errors import raise_runtime_exception
from autoclaw.persistence.session import get_db_session
from autoclaw.runtime.contracts import TaskComposePreviewResponse, TaskStartRequest
from autoclaw.runtime.dispatch.preparation import DispatchOpeningDependencies

router = APIRouter(
    prefix="/authoring",
    tags=["authoring"],
)
type DBSession = Annotated[AsyncSession, Depends(get_db_session)]
type DefinitionDraftListParams = Annotated[DefinitionDraftListQuery, Query()]
type DispatchOpeningDependenciesDep = Annotated[
    DispatchOpeningDependencies,
    Depends(read_dispatch_opening_dependencies),
]


@router.post("/task-compose/preview", response_model=TaskComposePreviewResponse)
async def post_task_compose_preview(
    request: TaskStartRequest,
    session: DBSession,
    dependencies: DispatchOpeningDependenciesDep,
) -> TaskComposePreviewResponse:
    try:
        return await preview_task_compose(
            session,
            request,
            settings=dependencies.settings,
            available_adapter_kinds=dependencies.available_adapter_kinds,
        )
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.get("/definition-drafts", response_model=DefinitionDraftListResponse)
async def get_definition_drafts(
    session: DBSession,
    query: DefinitionDraftListParams,
) -> DefinitionDraftListResponse:
    try:
        return await list_definition_drafts(
            session,
            data_dir=get_settings().data_dir,
            query=query,
        )
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.post("/definition-drafts", response_model=DefinitionDraftDetailResponse)
async def post_definition_draft(
    request: DefinitionDraftCreateRequest,
    session: DBSession,
) -> DefinitionDraftDetailResponse:
    try:
        return await create_definition_draft(
            session,
            data_dir=get_settings().data_dir,
            request=request,
        )
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.get(
    "/definitions/{kind}/{key}/draft",
    response_model=DefinitionDraftDetailResponse,
)
async def get_definition_draft(
    kind: DefinitionKind,
    key: str,
    session: DBSession,
) -> DefinitionDraftDetailResponse:
    try:
        return await read_definition_draft(
            session,
            data_dir=get_settings().data_dir,
            kind=kind,
            key=key,
        )
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.put(
    "/definitions/{kind}/{key}/draft",
    response_model=DefinitionDraftDetailResponse,
)
async def put_definition_draft(
    kind: DefinitionKind,
    key: str,
    request: DefinitionDraftWriteRequest,
    session: DBSession,
) -> DefinitionDraftDetailResponse:
    try:
        return await write_definition_draft(
            session,
            data_dir=get_settings().data_dir,
            kind=kind,
            key=key,
            request=request,
        )
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.delete("/definitions/{kind}/{key}/draft", status_code=status.HTTP_204_NO_CONTENT)
async def delete_definition_draft_route(
    kind: DefinitionKind,
    key: str,
) -> Response:
    try:
        delete_definition_draft(data_dir=get_settings().data_dir, kind=kind, key=key)
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/definitions/{kind}/{key}/draft/replace-current",
    response_model=DefinitionDraftDetailResponse,
)
async def post_definition_draft_replace_current(
    kind: DefinitionKind,
    key: str,
    session: DBSession,
) -> DefinitionDraftDetailResponse:
    try:
        return await replace_definition_draft_with_current_revision(
            session,
            data_dir=get_settings().data_dir,
            kind=kind,
            key=key,
        )
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.post(
    "/definitions/{kind}/{key}/draft/validate",
    response_model=DefinitionDraftValidationResponse,
)
async def post_definition_draft_validate(
    kind: DefinitionKind,
    key: str,
    session: DBSession,
) -> DefinitionDraftValidationResponse:
    try:
        return await validate_saved_definition_draft(
            session,
            data_dir=get_settings().data_dir,
            kind=kind,
            key=key,
        )
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)


@router.post(
    "/definitions/{kind}/{key}/draft/publish",
    response_model=DefinitionDraftPublishResponse,
)
async def post_definition_draft_publish(
    kind: DefinitionKind,
    key: str,
    session: DBSession,
) -> DefinitionDraftPublishResponse:
    try:
        return await publish_definition_draft(
            session,
            data_dir=get_settings().data_dir,
            kind=kind,
            key=key,
        )
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)
