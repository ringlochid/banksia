from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.config import Settings, get_settings
from banksia.interfaces.http.contracts.operation_failure import ProductFailureCode
from banksia.interfaces.http.contracts.workflows import (
    WorkflowPreconditionRequiredResponse,
    WorkflowStaleDraftResponse,
    WorkflowUndoRequest,
)
from banksia.interfaces.http.errors import operation_failure, runtime_exception_failure
from banksia.persistence.session import get_db_session
from banksia.persistence.session_operations import write_session_operation
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.product.paths import build_product_api_path
from banksia.workflows import DRAFT_OPERATION_ADAPTER, DraftOperation, WorkflowInputError
from banksia.workflows.authoring import (
    build_workflow_authoring_options,
    discard_workflow_draft,
    edit_workflow_draft,
    open_workflow_draft,
    publish_workflow_draft,
    read_workflow_catalog_entry,
    read_workflow_draft,
    remove_workflow,
    search_workflow_catalog,
    undo_workflow_draft,
    validate_workflow_draft,
)
from banksia.workflows.authoring_contracts import (
    WORKFLOW_DRAFT_OPEN_REQUEST_ADAPTER,
    WorkflowAuthoringOptions,
    WorkflowDraftDiscardResult,
    WorkflowDraftMutationResult,
    WorkflowDraftOpenRequest,
    WorkflowDraftOpenResult,
    WorkflowDraftReadback,
    WorkflowDraftValidationResult,
    WorkflowGetResponse,
    WorkflowPublishedReadback,
    WorkflowRemovalResult,
    WorkflowSearchResponse,
    map_workflow_published_readback,
)
from banksia.workflows.service_errors import (
    WorkflowDraftConflictError,
    WorkflowNotFoundError,
    WorkflowStaleDraftError,
    WorkflowUndoReceiptError,
)

router = APIRouter(tags=["workflows"])
type DBSession = Annotated[AsyncSession, Depends(get_db_session)]
type ControllerSettings = Annotated[Settings, Depends(get_settings)]
type IfMatch = Annotated[str | None, Header(alias="If-Match")]

_DRAFT_MUTATION_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_412_PRECONDITION_FAILED: {"model": WorkflowStaleDraftResponse},
    status.HTTP_428_PRECONDITION_REQUIRED: {"model": WorkflowPreconditionRequiredResponse},
}
_DRAFT_ETAG_HEADER = {
    "description": "Opaque version of the returned draft.",
    "schema": {"type": "string"},
}
_DRAFT_OPEN_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_200_OK: {
        "model": WorkflowDraftOpenResult,
        "description": "The existing active draft was reused.",
        "headers": {"ETag": _DRAFT_ETAG_HEADER},
    },
    status.HTTP_201_CREATED: {
        "model": WorkflowDraftOpenResult,
        "description": "A new active draft was created.",
        "headers": {
            "ETag": _DRAFT_ETAG_HEADER,
            "Location": {
                "description": "Canonical path of the newly created draft.",
                "schema": {"type": "string"},
            },
        },
    },
}


@router.get("/workflows", response_model=WorkflowSearchResponse)
async def get_workflows(
    session: DBSession,
    query: Annotated[str | None, Query(alias="q")] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> WorkflowSearchResponse:
    try:
        return await search_workflow_catalog(
            session,
            query=query,
            cursor=cursor,
            limit=limit,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workflows/authoring-options",
    response_model=WorkflowAuthoringOptions,
)
async def get_workflow_authoring_options(
    settings: ControllerSettings,
) -> WorkflowAuthoringOptions:
    return build_workflow_authoring_options(settings)


@router.get("/workflows/{workflow_id}", response_model=WorkflowGetResponse)
async def get_workflow(
    workflow_id: str,
    response: Response,
    session: DBSession,
    revision_no: Annotated[int | None, Query(ge=1)] = None,
    should_include_revisions: Annotated[bool, Query(alias="include_revisions")] = True,
    revision_cursor: str | None = None,
    revision_limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> WorkflowGetResponse:
    try:
        workflow = await read_workflow_catalog_entry(
            session,
            workflow_id=workflow_id,
            revision_no=revision_no,
            should_include_revisions=should_include_revisions,
            revision_cursor=revision_cursor,
            revision_limit=revision_limit,
        )
        if workflow.active_draft is not None:
            response.headers["ETag"] = workflow.active_draft.etag
        return workflow
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete("/workflows/{workflow_id}", response_model=WorkflowRemovalResult)
async def delete_workflow(
    workflow_id: str,
    session: DBSession,
) -> WorkflowRemovalResult:
    try:
        return await write_session_operation(
            lambda db: remove_workflow(db, workflow_id=workflow_id),
            session=session,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/workflow-drafts",
    response_model=WorkflowDraftOpenResult,
    responses=_DRAFT_OPEN_RESPONSES,
)
async def post_workflow_draft(
    draft_request: WorkflowDraftOpenRequest,
    request: Request,
    response: Response,
    session: DBSession,
) -> WorkflowDraftOpenResult:
    try:
        _require_json(request)
        result = await write_session_operation(
            lambda db: open_workflow_draft(
                db,
                request=WORKFLOW_DRAFT_OPEN_REQUEST_ADAPTER.validate_python(draft_request),
            ),
            session=session,
        )
        response.headers["ETag"] = result.draft.etag
        if result.is_created:
            response.status_code = status.HTTP_201_CREATED
            response.headers["Location"] = build_product_api_path(
                f"/workflow-drafts/{result.draft.draft_id}"
            )
        return result
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
        result = await write_session_operation(
            lambda db: edit_workflow_draft(
                db,
                draft_id=draft_id,
                expected_etag=_require_if_match(if_match),
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
    response_model=WorkflowDraftDiscardResult,
    responses=_DRAFT_MUTATION_RESPONSES,
)
async def delete_workflow_draft(
    draft_id: str,
    session: DBSession,
    if_match: IfMatch = None,
) -> WorkflowDraftDiscardResult:
    try:
        await write_session_operation(
            lambda db: discard_workflow_draft(
                db,
                draft_id=draft_id,
                expected_etag=_require_if_match(if_match),
            ),
            session=session,
        )
        return WorkflowDraftDiscardResult(is_discarded=True, draft_id=draft_id)
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
        draft = await write_session_operation(
            lambda db: undo_workflow_draft(
                db,
                draft_id=draft_id,
                expected_etag=_require_if_match(if_match),
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
        published = await write_session_operation(
            lambda db: publish_workflow_draft(
                db,
                draft_id=draft_id,
                expected_etag=_require_if_match(if_match),
            ),
            session=session,
        )
        return map_workflow_published_readback(published)
    except Exception as exc:
        raise _http_error(exc) from exc


def _require_if_match(value: str | None) -> str:
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={
                "code": ProductFailureCode.INVALID_REQUEST,
                "message": "The current draft version is required.",
            },
        )
    return value


def _require_json(request: Request) -> None:
    content_type = request.headers.get("content-type", "").partition(";")[0].strip().casefold()
    if content_type != "application/json":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=operation_failure(
                code=ProductFailureCode.INVALID_REQUEST,
                summary="Workflow draft bodies must use JSON.",
                is_retryable=False,
                suggested_next_step="Send the request again with a JSON content type.",
            ).model_dump(mode="json"),
        )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, RuntimeOperationError):
        status_code, failure = runtime_exception_failure(exc)
        return HTTPException(
            status_code=status_code,
            detail=failure.model_dump(mode="json"),
        )
    if isinstance(exc, WorkflowStaleDraftError):
        return HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail={
                "code": ProductFailureCode.CONFLICT,
                "message": "The draft changed before this request could be applied.",
                "current": exc.current.model_dump(mode="json"),
            },
        )
    if isinstance(exc, WorkflowNotFoundError):
        return _failure(
            status_code=status.HTTP_404_NOT_FOUND,
            code=ProductFailureCode.NOT_FOUND,
            summary="That Workflow or draft could not be found.",
        )
    if isinstance(exc, (WorkflowDraftConflictError, WorkflowUndoReceiptError)):
        return _failure(
            status_code=status.HTTP_409_CONFLICT,
            code=ProductFailureCode.CONFLICT,
            summary="The draft action is no longer available. Reload the Workflow.",
        )
    if isinstance(exc, WorkflowInputError):
        first_issue = exc.issues[0]
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=operation_failure(
                code=ProductFailureCode.INVALID_REQUEST,
                summary="The Workflow contains an unsupported or invalid field.",
                is_retryable=False,
                field_path=first_issue.path,
                suggested_next_step="Correct the highlighted Workflow field and try again.",
            ).model_dump(mode="json"),
        )
    return _failure(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=ProductFailureCode.INTERNAL_ERROR,
        summary="Banksia could not complete the Workflow action.",
    )


def _failure(
    *,
    status_code: int,
    code: ProductFailureCode,
    summary: str,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=operation_failure(
            code=code,
            summary=summary,
            is_retryable=False,
            suggested_next_step="Reload current Workflow information before trying again.",
        ).model_dump(mode="json"),
    )


__all__ = ["router"]
