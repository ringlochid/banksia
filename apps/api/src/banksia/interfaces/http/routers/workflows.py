from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.interfaces.http.errors import operation_failure
from banksia.persistence.session import get_db_session
from banksia.persistence.session_operations import write_session_operation
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.workflows import (
    DRAFT_OPERATION_ADAPTER,
    DraftOperation,
    WorkflowInputError,
    parse_workflow,
)
from banksia.workflows.authoring import (
    create_workflow_draft,
    discard_workflow_draft,
    edit_workflow_draft,
    publish_workflow_draft,
    read_workflow_catalog_entry,
    read_workflow_draft,
    search_workflow_catalog,
    undo_workflow_draft,
    validate_workflow_draft,
)
from banksia.workflows.authoring_contracts import (
    WorkflowDraftMutationResult,
    WorkflowDraftReadback,
    WorkflowDraftValidationResult,
    WorkflowGetResponse,
    WorkflowPublishedReadback,
    WorkflowRevisionReadback,
    WorkflowSearchItem,
    map_workflow_published_readback,
    map_workflow_revision_readback,
)
from banksia.workflows.catalog import (
    list_workflow_revisions,
    read_published_workflow_revision,
)
from banksia.workflows.service_errors import (
    WorkflowDraftConflictError,
    WorkflowNotFoundError,
    WorkflowStaleDraftError,
    WorkflowUndoReceiptError,
)

router = APIRouter(tags=["workflows"])
type DBSession = Annotated[AsyncSession, Depends(get_db_session)]
type IfMatch = Annotated[str | None, Header(alias="If-Match")]


class WorkflowUndoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt_id: str


class WorkflowPreconditionRequiredDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str


class WorkflowPreconditionRequiredResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    detail: WorkflowPreconditionRequiredDetail


class WorkflowStaleDraftDetail(WorkflowPreconditionRequiredDetail):
    current: WorkflowDraftReadback


class WorkflowStaleDraftResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    detail: WorkflowStaleDraftDetail


_DRAFT_MUTATION_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_412_PRECONDITION_FAILED: {"model": WorkflowStaleDraftResponse},
    status.HTTP_428_PRECONDITION_REQUIRED: {"model": WorkflowPreconditionRequiredResponse},
}


@router.get("/workflows", response_model=list[WorkflowSearchItem])
async def get_workflows(
    session: DBSession,
    query: Annotated[str | None, Query(alias="q")] = None,
) -> list[WorkflowSearchItem]:
    return list(await search_workflow_catalog(session, query=query))


@router.get("/workflows/{workflow_id}", response_model=WorkflowGetResponse)
async def get_workflow(
    workflow_id: str,
    response: Response,
    session: DBSession,
) -> WorkflowGetResponse:
    try:
        workflow = await read_workflow_catalog_entry(session, workflow_id=workflow_id)
        if workflow.active_draft is not None:
            response.headers["ETag"] = workflow.active_draft.etag
        return workflow
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workflows/{workflow_id}/revisions",
    response_model=list[WorkflowRevisionReadback],
)
async def get_workflow_revisions(
    workflow_id: str,
    session: DBSession,
) -> list[WorkflowRevisionReadback]:
    try:
        revisions = await list_workflow_revisions(session, workflow_id=workflow_id)
        return [map_workflow_revision_readback(revision) for revision in revisions]
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workflows/{workflow_id}/revisions/{revision_no}",
    response_model=WorkflowPublishedReadback,
)
async def get_workflow_revision(
    workflow_id: str,
    revision_no: int,
    session: DBSession,
) -> WorkflowPublishedReadback:
    try:
        return map_workflow_published_readback(
            await read_published_workflow_revision(
                session,
                workflow_id=workflow_id,
                revision_no=revision_no,
            )
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/workflow-drafts",
    response_model=WorkflowDraftReadback,
    status_code=status.HTTP_201_CREATED,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/NormalizedWorkflow"}}
            },
        }
    },
)
async def post_workflow_draft(
    request: Request,
    response: Response,
    session: DBSession,
) -> WorkflowDraftReadback:
    try:
        _require_json(request)
        workflow = parse_workflow(await request.body(), source_format="json")
        draft = await write_session_operation(
            lambda db: create_workflow_draft(db, workflow=workflow),
            session=session,
        )
        response.headers["ETag"] = draft.etag
        return draft
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/workflow-drafts/{draft_id}", response_model=WorkflowDraftReadback)
async def get_workflow_draft(
    draft_id: str,
    response: Response,
    session: DBSession,
) -> WorkflowDraftReadback:
    try:
        draft = await read_workflow_draft(session, draft_id=draft_id)
        response.headers["ETag"] = draft.etag
        return draft
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/workflow-drafts/{draft_id}",
    response_model=WorkflowDraftMutationResult,
    responses=_DRAFT_MUTATION_RESPONSES,
)
async def patch_workflow_draft(
    draft_id: str,
    operation: DraftOperation,
    request: Request,
    response: Response,
    session: DBSession,
    if_match: IfMatch = None,
) -> WorkflowDraftMutationResult:
    try:
        _require_json(request)
        expected_etag = _require_if_match(if_match)
        result = await write_session_operation(
            lambda db: edit_workflow_draft(
                db,
                draft_id=draft_id,
                expected_etag=expected_etag,
                operation=DRAFT_OPERATION_ADAPTER.validate_python(operation),
            ),
            session=session,
        )
        response.headers["ETag"] = result.draft.etag
        return result
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/workflow-drafts/{draft_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_DRAFT_MUTATION_RESPONSES,
)
async def delete_workflow_draft(
    draft_id: str,
    session: DBSession,
    if_match: IfMatch = None,
) -> Response:
    try:
        expected_etag = _require_if_match(if_match)
        await write_session_operation(
            lambda db: discard_workflow_draft(
                db,
                draft_id=draft_id,
                expected_etag=expected_etag,
            ),
            session=session,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/workflow-drafts/{draft_id}/validate",
    response_model=WorkflowDraftValidationResult,
)
async def post_workflow_draft_validate(
    draft_id: str,
    session: DBSession,
) -> WorkflowDraftValidationResult:
    try:
        return await validate_workflow_draft(session, draft_id=draft_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/workflow-drafts/{draft_id}/undo",
    response_model=WorkflowDraftReadback,
    responses=_DRAFT_MUTATION_RESPONSES,
)
async def post_workflow_draft_undo(
    draft_id: str,
    undo_request: WorkflowUndoRequest,
    request: Request,
    response: Response,
    session: DBSession,
    if_match: IfMatch = None,
) -> WorkflowDraftReadback:
    try:
        _require_json(request)
        expected_etag = _require_if_match(if_match)
        draft = await write_session_operation(
            lambda db: undo_workflow_draft(
                db,
                draft_id=draft_id,
                expected_etag=expected_etag,
                receipt_id=undo_request.receipt_id,
            ),
            session=session,
        )
        response.headers["ETag"] = draft.etag
        return draft
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/workflow-drafts/{draft_id}/publish",
    response_model=WorkflowPublishedReadback,
    responses=_DRAFT_MUTATION_RESPONSES,
)
async def post_workflow_draft_publish(
    draft_id: str,
    session: DBSession,
    if_match: IfMatch = None,
) -> WorkflowPublishedReadback:
    try:
        expected_etag = _require_if_match(if_match)
        return map_workflow_published_readback(
            await write_session_operation(
                lambda db: publish_workflow_draft(
                    db,
                    draft_id=draft_id,
                    expected_etag=expected_etag,
                ),
                session=session,
            ),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


def _require_if_match(value: str | None) -> str:
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={"code": "precondition_required", "message": "If-Match is required"},
        )
    return value


def _require_json(request: Request) -> None:
    content_type = request.headers.get("content-type", "").partition(";")[0].strip().casefold()
    if content_type != "application/json":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"code": "json_required", "message": "Workflow draft bodies must be JSON"},
        )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, WorkflowStaleDraftError):
        return HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail={
                "code": "stale_draft",
                "message": str(exc),
                "current": exc.current.model_dump(mode="json"),
            },
        )
    if isinstance(exc, WorkflowNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=operation_failure(
                code=OperationFailureCode.MISSING_RESOURCE,
                summary=str(exc),
                is_retryable=False,
            ).model_dump(mode="json"),
        )
    if isinstance(exc, (WorkflowDraftConflictError, WorkflowUndoReceiptError)):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=operation_failure(
                code=OperationFailureCode.CONFLICT,
                summary=str(exc),
                is_retryable=False,
            ).model_dump(mode="json"),
        )
    if isinstance(exc, WorkflowInputError):
        first_issue = exc.issues[0]
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=operation_failure(
                code=OperationFailureCode.INVALID_REQUEST_SHAPE,
                summary=f"{first_issue.source}: {first_issue.message}",
                is_retryable=False,
                field_path=first_issue.path,
            ).model_dump(mode="json"),
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=operation_failure(
            code=OperationFailureCode.INTERNAL_ERROR,
            summary="Workflow operation failed",
            is_retryable=False,
        ).model_dump(mode="json"),
    )


__all__ = ["router"]
