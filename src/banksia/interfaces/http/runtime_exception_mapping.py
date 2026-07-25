from __future__ import annotations

from typing import NoReturn

from fastapi import HTTPException, status

from banksia.interfaces.http.contracts.operation_failure import (
    OperationFailure,
    ProductFailureCode,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.task_events import TaskEventCursorResetRequiredError
from banksia.workflows.errors import WorkflowInputError
from banksia.workflows.service_errors import (
    WorkflowDraftConflictError,
    WorkflowIntegrityError,
    WorkflowNotFoundError,
    WorkflowPreconditionRequiredError,
    WorkflowStaleDraftError,
    WorkflowUndoReceiptError,
)


class _ProductFailureMapping:
    def __init__(
        self,
        *,
        code: ProductFailureCode,
        status_code: int,
        summary: str,
        is_retryable: bool,
        suggested_next_step: str,
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.summary = summary
        self.is_retryable = is_retryable
        self.suggested_next_step = suggested_next_step


_INVALID = _ProductFailureMapping(
    code=ProductFailureCode.INVALID_REQUEST,
    status_code=status.HTTP_400_BAD_REQUEST,
    summary="The request cannot be applied.",
    is_retryable=False,
    suggested_next_step="Check the request fields against the current action and try again.",
)
_NOT_FOUND = _ProductFailureMapping(
    code=ProductFailureCode.NOT_FOUND,
    status_code=status.HTTP_404_NOT_FOUND,
    summary="The requested item could not be found.",
    is_retryable=False,
    suggested_next_step="Reload current information and check the selected item.",
)
_CONFLICT = _ProductFailureMapping(
    code=ProductFailureCode.CONFLICT,
    status_code=status.HTTP_409_CONFLICT,
    summary="The item changed before this request could be applied.",
    is_retryable=False,
    suggested_next_step="Reload current information and use one of the actions now available.",
)
_ACCESS_DENIED = _ProductFailureMapping(
    code=ProductFailureCode.ACCESS_DENIED,
    status_code=status.HTTP_403_FORBIDDEN,
    summary="This request is not allowed.",
    is_retryable=False,
    suggested_next_step="Use an available product action from the current item.",
)
_INTERNAL = _ProductFailureMapping(
    code=ProductFailureCode.INTERNAL_ERROR,
    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    summary="Banksia could not complete this request.",
    is_retryable=False,
    suggested_next_step=(
        "Reload current information. If the problem continues, use the support reference."
    ),
)

_PRODUCT_FAILURES: dict[OperationFailureCode, _ProductFailureMapping] = {
    OperationFailureCode.INVALID_REQUEST_SHAPE: _INVALID,
    OperationFailureCode.INVALID_TASK_PATH: _INVALID,
    OperationFailureCode.INVALID_TASK_ROOT: _INVALID,
    OperationFailureCode.ILLEGAL_TARGET_RELATION: _INVALID,
    OperationFailureCode.CAPABILITY_REJECTED: _INVALID,
    OperationFailureCode.BUDGET_EXHAUSTED: _INVALID,
    OperationFailureCode.BOUNDARY_PRECONDITION_FAILED: _INVALID,
    OperationFailureCode.MISSING_RESOURCE: _NOT_FOUND,
    OperationFailureCode.CONFLICT: _CONFLICT,
    OperationFailureCode.CONFLICTING_CONTINUATION: _CONFLICT,
    OperationFailureCode.ILLEGAL_STATE: _CONFLICT,
    OperationFailureCode.NAME_COLLISION: _CONFLICT,
    OperationFailureCode.STALE_ASSIGNMENT: _CONFLICT,
    OperationFailureCode.STALE_DISPATCH: _CONFLICT,
    OperationFailureCode.STALE_TEAM_REVISION: _CONFLICT,
    OperationFailureCode.LOCAL_ADMISSION_DENIED: _ACCESS_DENIED,
    OperationFailureCode.AUTHENTICATION_FAILED: _ACCESS_DENIED,
    OperationFailureCode.SCOPE_MISMATCH: _ACCESS_DENIED,
    OperationFailureCode.ILLEGAL_CALLER: _ACCESS_DENIED,
    OperationFailureCode.CURSOR_RESET_REQUIRED: _ProductFailureMapping(
        code=ProductFailureCode.CURSOR_RESET_REQUIRED,
        status_code=status.HTTP_410_GONE,
        summary="Saved live-update position is no longer available.",
        is_retryable=False,
        suggested_next_step="Reload the item and reconnect from the newest available position.",
    ),
    OperationFailureCode.INTERNAL_ERROR: _INTERNAL,
}


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
            code=ProductFailureCode.CURSOR_RESET_REQUIRED,
            summary="Live updates are no longer available from that cursor.",
            is_retryable=False,
            suggested_next_step=(
                "Reload the run, backfill its Activity, and reconnect from the current cursor."
            ),
        )
    if isinstance(exc, RuntimeOperationError):
        return _mapped_runtime_failure(exc)
    workflow_failure = _workflow_exception_failure(exc)
    if workflow_failure is not None:
        return workflow_failure
    if isinstance(exc, ValueError):
        return _runtime_failure(
            status_code=status.HTTP_400_BAD_REQUEST,
            code=ProductFailureCode.INVALID_REQUEST,
            summary="The request contains an unsupported or invalid value.",
            is_retryable=False,
            suggested_next_step="Check the current input contract and try again.",
        )
    if isinstance(exc, FileNotFoundError):
        return _runtime_failure(
            status_code=status.HTTP_404_NOT_FOUND,
            code=ProductFailureCode.NOT_FOUND,
            summary="The requested item could not be found.",
            is_retryable=False,
            suggested_next_step="Reload current product information and check the selected item.",
        )
    return _runtime_failure(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=ProductFailureCode.INTERNAL_ERROR,
        summary="Banksia could not complete this request.",
        is_retryable=False,
        suggested_next_step=(
            "Reload current information. If the problem continues, use the support reference."
        ),
    )


def _mapped_runtime_failure(exc: RuntimeOperationError) -> tuple[int, OperationFailure]:
    mapped = _PRODUCT_FAILURES[exc.code]
    return _runtime_failure(
        status_code=exc.status_code_override or mapped.status_code,
        code=mapped.code,
        summary=mapped.summary,
        is_retryable=mapped.is_retryable,
        suggested_next_step=mapped.suggested_next_step,
    )


def _workflow_exception_failure(exc: Exception) -> tuple[int, OperationFailure] | None:
    if isinstance(exc, WorkflowIntegrityError):
        return _runtime_failure(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code=ProductFailureCode.INTERNAL_ERROR,
            summary="Stored Workflow truth failed its integrity check.",
            is_retryable=False,
            suggested_next_step="Use the support reference before retrying this action.",
        )
    if isinstance(exc, WorkflowNotFoundError):
        return _runtime_failure(
            status_code=status.HTTP_404_NOT_FOUND,
            code=ProductFailureCode.NOT_FOUND,
            summary="The requested Workflow item could not be found.",
            is_retryable=False,
            suggested_next_step="Reload the Workflow catalog and check the selected item.",
        )
    if isinstance(
        exc,
        (WorkflowDraftConflictError, WorkflowStaleDraftError, WorkflowUndoReceiptError),
    ):
        return _runtime_failure(
            status_code=status.HTTP_409_CONFLICT,
            code=ProductFailureCode.CONFLICT,
            summary="The Workflow changed before this request could be applied.",
            is_retryable=False,
            suggested_next_step="Reload the Workflow and use one of its current actions.",
        )
    if isinstance(exc, WorkflowPreconditionRequiredError):
        return _runtime_failure(
            status_code=status.HTTP_400_BAD_REQUEST,
            code=ProductFailureCode.INVALID_REQUEST,
            summary="The request is missing its current Workflow version.",
            is_retryable=False,
            suggested_next_step="Reload the Workflow and resend its current version reference.",
        )
    if isinstance(exc, WorkflowInputError):
        first_issue = exc.issues[0] if exc.issues else None
        return _runtime_failure(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code=ProductFailureCode.INVALID_REQUEST,
            summary="The Workflow contains an unsupported or invalid field.",
            is_retryable=False,
            field_path=first_issue.path if first_issue is not None else None,
            suggested_next_step="Correct the highlighted Workflow field and try again.",
        )
    return None


def _runtime_failure(
    *,
    status_code: int,
    code: ProductFailureCode,
    summary: str,
    is_retryable: bool,
    suggested_next_step: str | None,
    field_path: str | None = None,
) -> tuple[int, OperationFailure]:
    return status_code, OperationFailure.model_validate(
        {
            "code": code,
            "summary": summary,
            "retryable": is_retryable,
            "field_path": field_path,
            "suggested_next_step": suggested_next_step,
        }
    )


__all__ = ["raise_runtime_exception", "runtime_exception_failure"]
