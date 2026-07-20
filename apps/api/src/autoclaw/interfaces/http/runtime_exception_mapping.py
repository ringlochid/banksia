from __future__ import annotations

from typing import NoReturn

from fastapi import HTTPException, status

from autoclaw.interfaces.http.contracts.operation_failure import OperationFailure
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.task_events import TaskEventCursorResetRequiredError

STAGED_CHILD_CONTINUATION_SUMMARY = "staged child assignment is incomplete"
STAGED_CHILD_CONTINUATION_NEXT_STEP = (
    "Inspect the current yielded dispatch and staged child assignment, then repair "
    "or restage a complete child continuation before continuing this task."
)


def raise_runtime_exception(exc: Exception) -> NoReturn:
    status_code, failure = runtime_exception_failure(exc)
    raise HTTPException(
        status_code=status_code,
        detail=failure.model_dump(mode="json"),
    ) from exc


def runtime_exception_failure(exc: Exception) -> tuple[int, OperationFailure]:
    if isinstance(exc, TaskEventCursorResetRequiredError):
        return _runtime_failure(
            status_code=status.HTTP_410_GONE,
            code=OperationFailureCode.CURSOR_RESET_REQUIRED,
            summary=str(exc),
            is_retryable=False,
            suggested_next_step=(
                "Refetch current task truth through the control API, then reconnect without "
                "the stale task-event cursor."
            ),
        )

    if isinstance(exc, RuntimeOperationError):
        exc = _normalize_runtime_operation_error(exc)
        return _runtime_failure(
            status_code=(
                exc.status_code_override
                if exc.status_code_override is not None
                else _runtime_failure_status(exc.code)
            ),
            code=exc.code,
            summary=exc.summary,
            is_retryable=exc.is_retryable,
            suggested_next_step=exc.suggested_next_step,
        )

    summary = str(exc)
    if isinstance(exc, FileNotFoundError):
        return _runtime_failure(
            status_code=status.HTTP_404_NOT_FOUND,
            code=OperationFailureCode.MISSING_RESOURCE,
            summary=summary,
            is_retryable=False,
            suggested_next_step=(
                "Verify the task, flow, or dispatch id and reread the current runtime "
                "surface before retrying this request."
            ),
        )

    return _runtime_failure(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=OperationFailureCode.INTERNAL_ERROR,
        summary=summary,
        is_retryable=False,
        suggested_next_step=(
            "Do not invent new runtime truth locally; surface the failure for operator or "
            "controller recovery and reread current runtime state before retrying."
        ),
    )


def _runtime_failure(
    *,
    status_code: int,
    code: OperationFailureCode,
    summary: str,
    is_retryable: bool,
    suggested_next_step: str | None,
) -> tuple[int, OperationFailure]:
    return status_code, OperationFailure.model_validate(
        {
            "code": code,
            "summary": summary,
            "retryable": is_retryable,
            "suggested_next_step": suggested_next_step,
        }
    )


def _runtime_failure_status(code: OperationFailureCode) -> int:
    if code == OperationFailureCode.INVALID_REQUEST_SHAPE:
        return status.HTTP_400_BAD_REQUEST
    if code == OperationFailureCode.MISSING_RESOURCE:
        return status.HTTP_404_NOT_FOUND
    if code in {
        OperationFailureCode.NAME_COLLISION,
        OperationFailureCode.STALE_DISPATCH,
        OperationFailureCode.STALE_FLOW_REVISION,
        OperationFailureCode.STALE_ASSIGNMENT,
        OperationFailureCode.STALE_CHECKPOINT,
    }:
        return status.HTTP_409_CONFLICT
    if code == OperationFailureCode.INTERNAL_ERROR:
        return status.HTTP_500_INTERNAL_SERVER_ERROR
    return status.HTTP_422_UNPROCESSABLE_CONTENT


def _normalize_runtime_operation_error(exc: RuntimeOperationError) -> RuntimeOperationError:
    if exc.summary not in {
        STAGED_CHILD_CONTINUATION_SUMMARY,
        "yield continuation basis is incomplete",
    }:
        return exc
    return RuntimeOperationError(
        code=OperationFailureCode.ILLEGAL_STATE,
        summary=STAGED_CHILD_CONTINUATION_SUMMARY,
        is_retryable=False,
        suggested_next_step=STAGED_CHILD_CONTINUATION_NEXT_STEP,
        status_code_override=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


__all__ = ["raise_runtime_exception", "runtime_exception_failure"]
