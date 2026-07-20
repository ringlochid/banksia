from __future__ import annotations

from typing import NoReturn

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

import autoclaw.interfaces.http.runtime_exception_mapping as runtime_exception_mapping
from autoclaw.interfaces.http.contracts.operation_failure import OperationFailure
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode


def raise_operation_failure(
    *,
    status_code: int,
    code: OperationFailureCode,
    summary: str,
    is_retryable: bool,
    field_path: str | None = None,
    suggested_next_step: str | None = None,
) -> NoReturn:
    raise HTTPException(
        status_code=status_code,
        detail=operation_failure(
            code=code,
            summary=summary,
            is_retryable=is_retryable,
            field_path=field_path,
            suggested_next_step=suggested_next_step,
        ).model_dump(mode="json"),
    )


def request_validation_failure(exc: RequestValidationError) -> OperationFailure:
    first_error = exc.errors()[0] if exc.errors() else {}
    loc = first_error.get("loc", ())
    field_path = ".".join(str(part) for part in loc if part != "body") or None
    return operation_failure(
        code=OperationFailureCode.INVALID_REQUEST_SHAPE,
        summary="request shape does not match the canonical runtime surface",
        is_retryable=False,
        field_path=field_path,
        suggested_next_step=(
            "Reread the canonical request shape and resend the request with only the live "
            "required fields."
        ),
    )


def operation_failure_from_http_exception(
    exc: HTTPException,
) -> OperationFailure | None:
    """Recover the shared failure contract from a FastAPI exception detail."""

    try:
        return OperationFailure.model_validate(exc.detail)
    except ValidationError:
        return None


def runtime_exception_failure(exc: Exception) -> tuple[int, OperationFailure]:
    return runtime_exception_mapping.runtime_exception_failure(exc)


def raise_runtime_exception(exc: Exception) -> NoReturn:
    runtime_exception_mapping.raise_runtime_exception(exc)


def operation_failure(
    *,
    code: OperationFailureCode,
    summary: str,
    is_retryable: bool,
    field_path: str | None = None,
    suggested_next_step: str | None = None,
) -> OperationFailure:
    return OperationFailure.model_validate(
        {
            "code": code,
            "summary": summary,
            "retryable": is_retryable,
            "field_path": field_path,
            "suggested_next_step": suggested_next_step,
        }
    )
