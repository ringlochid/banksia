from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from banksia.interfaces.http.contracts.operation_failure import (
    OperationFailure,
    ProductFailureCode,
)
from banksia.interfaces.http.dependencies import read_operator_conversation_service
from banksia.interfaces.http.errors import operation_failure
from banksia.operator import (
    OperatorAnswerValidationError,
    OperatorConversationConflictError,
    OperatorConversationNotFoundError,
    OperatorConversationPage,
    OperatorConversationService,
    OperatorConversationView,
    OperatorCursorValidationError,
    OperatorEmptyRequest,
    OperatorIdempotencyConflictError,
    OperatorIdempotencyKeyValidationError,
    OperatorMessageRequest,
    OperatorQuestionAnswersRequest,
    OperatorQuestionSetNotFoundError,
    OperatorStatusResponse,
    OperatorUnavailableError,
)

router = APIRouter(tags=["operator"])
type OperatorService = Annotated[
    OperatorConversationService,
    Depends(read_operator_conversation_service),
]
type IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=200),
]
type ConversationLimit = Annotated[int, Query(ge=1, le=100)]


@router.get("/operator/status", response_model=OperatorStatusResponse)
async def get_operator_status(service: OperatorService) -> OperatorStatusResponse:
    return service.read_status()


@router.get(
    "/operator/conversations",
    response_model=OperatorConversationPage,
)
async def get_operator_conversations(
    service: OperatorService,
    cursor: str | None = None,
    limit: ConversationLimit = 50,
) -> OperatorConversationPage:
    try:
        return await service.list_conversations(cursor=cursor, limit=limit)
    except Exception as exc:
        raise map_operator_http_error(exc) from exc


@router.post(
    "/operator/conversations",
    response_model=OperatorConversationView,
    status_code=status.HTTP_201_CREATED,
    responses={503: {"model": OperationFailure}},
)
async def post_operator_conversation(
    request_body: OperatorEmptyRequest,
    service: OperatorService,
    idempotency_key: IdempotencyKey,
) -> OperatorConversationView:
    del request_body
    try:
        return await service.create_conversation(idempotency_key=idempotency_key)
    except Exception as exc:
        raise map_operator_http_error(exc) from exc


@router.get(
    "/operator/conversations/{conversation_id}",
    response_model=OperatorConversationView,
)
async def get_operator_conversation(
    conversation_id: str,
    service: OperatorService,
    cursor: str | None = None,
    limit: ConversationLimit = 100,
) -> OperatorConversationView:
    try:
        return await service.read_conversation(
            conversation_id,
            cursor=cursor,
            limit=limit,
        )
    except Exception as exc:
        raise map_operator_http_error(exc) from exc


@router.post(
    "/operator/conversations/{conversation_id}/messages",
    response_model=OperatorConversationView,
)
async def post_operator_message(
    conversation_id: str,
    request_body: OperatorMessageRequest,
    service: OperatorService,
    idempotency_key: IdempotencyKey,
) -> OperatorConversationView:
    try:
        return await service.submit_message(
            conversation_id,
            request_body,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        raise map_operator_http_error(exc) from exc


@router.post(
    ("/operator/conversations/{conversation_id}/question-sets/{question_set_id}/answers"),
    response_model=OperatorConversationView,
)
async def post_operator_question_answers(
    conversation_id: str,
    question_set_id: str,
    request_body: OperatorQuestionAnswersRequest,
    service: OperatorService,
    idempotency_key: IdempotencyKey,
) -> OperatorConversationView:
    try:
        return await service.submit_question_answers(
            conversation_id,
            question_set_id,
            request_body,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        raise map_operator_http_error(exc) from exc


def map_operator_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(
        exc,
        (OperatorConversationNotFoundError, OperatorQuestionSetNotFoundError),
    ):
        return operator_http_failure(
            status_code=status.HTTP_404_NOT_FOUND,
            code=ProductFailureCode.NOT_FOUND,
            summary="That Operator conversation item could not be found.",
            suggested_next_step="Reload the conversation list and check the selected item.",
        )
    if isinstance(
        exc,
        (OperatorConversationConflictError, OperatorIdempotencyConflictError),
    ):
        return operator_http_failure(
            status_code=status.HTTP_409_CONFLICT,
            code=ProductFailureCode.CONFLICT,
            summary="The Operator conversation changed before this request could be applied.",
            suggested_next_step="Reload the conversation and use one of its current actions.",
        )
    if isinstance(exc, OperatorAnswerValidationError):
        return operator_http_failure(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code=ProductFailureCode.INVALID_REQUEST,
            summary="The answers do not match the current Operator question set.",
            suggested_next_step="Answer each current question once, in the displayed order.",
        )
    if isinstance(exc, OperatorUnavailableError):
        return operator_http_failure(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code=ProductFailureCode.UNAVAILABLE,
            summary="Operator is not available with the current configuration.",
            suggested_next_step="Read Operator status for the required setup action.",
        )
    if isinstance(
        exc,
        (OperatorCursorValidationError, OperatorIdempotencyKeyValidationError),
    ):
        return operator_http_failure(
            status_code=status.HTTP_400_BAD_REQUEST,
            code=ProductFailureCode.INVALID_REQUEST,
            summary="The Operator request contains an unsupported or invalid value.",
            suggested_next_step="Reload current conversation truth and correct the request.",
        )
    return operator_http_failure(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=ProductFailureCode.INTERNAL_ERROR,
        summary="Oh My Subagents could not complete the Operator request.",
        suggested_next_step="Reload the conversation before trying another explicit message.",
    )


def operator_http_failure(
    *,
    status_code: int,
    code: ProductFailureCode,
    summary: str,
    suggested_next_step: str,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=operation_failure(
            code=code,
            summary=summary,
            is_retryable=False,
            suggested_next_step=suggested_next_step,
        ).model_dump(mode="json"),
    )


__all__ = ["router"]
