from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, status

from banksia.interfaces.http.dependencies import read_operator_conversation_service
from banksia.operator.contracts import (
    OperatorConversationPage,
    OperatorConversationView,
    OperatorEmptyRequest,
    OperatorFieldError,
    OperatorMessageRequest,
    OperatorProblemResponse,
    OperatorQuestionAnswersRequest,
    OperatorStatusResponse,
)
from banksia.operator.errors import OperatorServiceError
from banksia.operator.service import OperatorConversationService

router = APIRouter(prefix="/operator", tags=["operator"])
type OperatorService = Annotated[
    OperatorConversationService,
    Depends(read_operator_conversation_service),
]
type IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=200,
        pattern=r".*\S.*",
    ),
]
type PageLimit = Annotated[int, Query(ge=1, le=100)]


_LIST_PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {422: {"model": OperatorProblemResponse}}
_CREATE_PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": OperatorProblemResponse} for code in (422, 503)
}
_DETAIL_PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": OperatorProblemResponse} for code in (404, 422)
}
_TURN_PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": OperatorProblemResponse} for code in (404, 409, 422, 503)
}
_CONFIRMATION_PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": OperatorProblemResponse} for code in (404, 409, 422)
}


@router.get("/status", response_model=OperatorStatusResponse)
async def get_operator_status(service: OperatorService) -> OperatorStatusResponse:
    return await service.read_status()


@router.get(
    "/conversations",
    response_model=OperatorConversationPage,
    responses=_LIST_PROBLEM_RESPONSES,
)
async def get_operator_conversations(
    service: OperatorService,
    cursor: str | None = None,
    limit: PageLimit = 50,
) -> OperatorConversationPage:
    try:
        return await service.list_conversations(cursor=cursor, limit=limit)
    except ValueError as exc:
        raise _invalid_operator_request("cursor", str(exc)) from exc


@router.post(
    "/conversations",
    response_model=OperatorConversationView,
    status_code=status.HTTP_201_CREATED,
    responses=_CREATE_PROBLEM_RESPONSES,
)
async def post_operator_conversation(
    request_body: OperatorEmptyRequest,
    idempotency_key: IdempotencyKey,
    service: OperatorService,
) -> OperatorConversationView:
    del request_body
    return await service.create_conversation(idempotency_key=idempotency_key)


@router.get(
    "/conversations/{conversation_id}",
    response_model=OperatorConversationView,
    responses=_DETAIL_PROBLEM_RESPONSES,
)
async def get_operator_conversation(
    conversation_id: str,
    service: OperatorService,
    before_entry: str | None = None,
    limit: PageLimit = 50,
) -> OperatorConversationView:
    try:
        return await service.read_conversation(
            conversation_id,
            before_entry=before_entry,
            limit=limit,
        )
    except ValueError as exc:
        raise _invalid_operator_request("before_entry", str(exc)) from exc


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=OperatorConversationView,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_TURN_PROBLEM_RESPONSES,
)
async def post_operator_message(
    conversation_id: str,
    request_body: OperatorMessageRequest,
    idempotency_key: IdempotencyKey,
    service: OperatorService,
) -> OperatorConversationView:
    return await service.submit_message(
        conversation_id=conversation_id,
        request=request_body,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/conversations/{conversation_id}/question-sets/{question_set_id}/answers",
    response_model=OperatorConversationView,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_TURN_PROBLEM_RESPONSES,
)
async def post_operator_answers(
    conversation_id: str,
    question_set_id: str,
    request_body: OperatorQuestionAnswersRequest,
    idempotency_key: IdempotencyKey,
    service: OperatorService,
) -> OperatorConversationView:
    return await service.answer_question_set(
        conversation_id=conversation_id,
        question_set_id=question_set_id,
        request=request_body,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/conversations/{conversation_id}/confirmations/{confirmation_id}",
    response_model=OperatorConversationView,
    responses=_CONFIRMATION_PROBLEM_RESPONSES,
)
async def post_operator_confirmation(
    conversation_id: str,
    confirmation_id: str,
    request_body: OperatorEmptyRequest,
    idempotency_key: IdempotencyKey,
    service: OperatorService,
) -> OperatorConversationView:
    del request_body
    return await service.confirm_effect(
        conversation_id=conversation_id,
        confirmation_id=confirmation_id,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/conversations/{conversation_id}/retries",
    response_model=OperatorConversationView,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_TURN_PROBLEM_RESPONSES,
)
async def post_operator_retry(
    conversation_id: str,
    request_body: OperatorEmptyRequest,
    idempotency_key: IdempotencyKey,
    service: OperatorService,
) -> OperatorConversationView:
    del request_body
    return await service.retry_provider_invocation(
        conversation_id=conversation_id,
        idempotency_key=idempotency_key,
    )


def _invalid_operator_request(path: str, message: str) -> OperatorServiceError:
    return OperatorServiceError(
        status_code=422,
        code="invalid_operator_request",
        message="The Operator request is invalid.",
        field_errors=(OperatorFieldError(path=path, message=message),),
    )


__all__ = ["router"]
