from __future__ import annotations

from collections.abc import Sequence

from banksia.operator.contracts import (
    OperatorConversationView,
    OperatorFieldError,
    OperatorProblem,
    OperatorProblemCode,
    OperatorProblemResponse,
)


class OperatorServiceError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: OperatorProblemCode,
        message: str,
        is_retryable: bool = False,
        field_errors: Sequence[OperatorFieldError] | None = None,
        current: OperatorConversationView | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = OperatorProblemResponse(
            problem=OperatorProblem.model_validate(
                {
                    "code": code,
                    "message": message,
                    "retryable": is_retryable,
                    "field_errors": tuple(field_errors) if field_errors else None,
                }
            ),
            current=current,
        )


def conversation_not_found() -> OperatorServiceError:
    return OperatorServiceError(
        status_code=404,
        code="operator_conversation_not_found",
        message="The Operator conversation does not exist.",
    )


def question_set_not_found() -> OperatorServiceError:
    return OperatorServiceError(
        status_code=404,
        code="operator_question_set_not_found",
        message="The Operator question set does not exist in this conversation.",
    )


def confirmation_not_found() -> OperatorServiceError:
    return OperatorServiceError(
        status_code=404,
        code="operator_confirmation_not_found",
        message="The Operator confirmation does not exist in this conversation.",
    )


def action_not_current(
    current: OperatorConversationView | None = None,
) -> OperatorServiceError:
    return OperatorServiceError(
        status_code=409,
        code="operator_action_not_current",
        message="The requested Operator action is no longer current.",
        current=current,
    )


def invalid_operator_answers(
    path: str,
    message: str,
) -> OperatorServiceError:
    return OperatorServiceError(
        status_code=422,
        code="invalid_operator_request",
        message="The Operator answers are invalid.",
        field_errors=(OperatorFieldError(path=path, message=message),),
    )


def idempotency_conflict() -> OperatorServiceError:
    return OperatorServiceError(
        status_code=409,
        code="idempotency_conflict",
        message="The idempotency key was already used for a different request.",
    )


def effect_in_progress(
    current: OperatorConversationView | None = None,
) -> OperatorServiceError:
    return OperatorServiceError(
        status_code=409,
        code="effect_in_progress",
        message="The confirmed effect is still executing.",
        is_retryable=True,
        current=current,
    )


def provider_unavailable(
    availability: str,
    explanation: str,
) -> OperatorServiceError:
    return OperatorServiceError(
        status_code=503,
        code="operator_provider_unavailable",
        message=f"Operator provider is {availability}: {explanation}",
        is_retryable=availability == "unavailable",
    )


__all__ = [
    "OperatorServiceError",
    "action_not_current",
    "confirmation_not_found",
    "conversation_not_found",
    "effect_in_progress",
    "idempotency_conflict",
    "invalid_operator_answers",
    "provider_unavailable",
    "question_set_not_found",
]
