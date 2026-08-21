from __future__ import annotations

from oh_my_subagents.runtime.contracts.operation_failure import OperationFailureCode

ILLEGAL_CALLER_NEXT_STEP = (
    "Reread the current dispatch context and use only the tools or boundaries legal "
    "for this node and this open dispatch."
)
ILLEGAL_STATE_NEXT_STEP = (
    "Reread the current manifest, assignment, checkpoint, and surfaced refs, then "
    "choose a tool or boundary that matches the current state."
)
STALE_ASSIGNMENT_NEXT_STEP = (
    "Reread the current dispatch context and resend the request only if the "
    "same assignment is still current."
)
STALE_TEAM_REVISION_NEXT_STEP = (
    "Reread the regenerated workflow manifest and current structural revision, "
    "then rebuild the request against that newer structure."
)
MISSING_RESOURCE_NEXT_STEP = (
    "Verify the supplied resource identifier and reread the current runtime surface "
    "before retrying this request."
)
BUDGET_EXHAUSTED_NEXT_STEP = (
    "Surface the latest terminal checkpoint to the relevant parent or root so it can "
    "choose a fresh assignment or another legal path."
)
INVALID_REQUEST_SHAPE_NEXT_STEP = (
    "Reread the canonical request shape and resend the request with only the live required fields."
)
STALE_DISPATCH_NEXT_STEP = (
    "Reread the current dispatch context and retry only if this node is still "
    "the current caller for an open dispatch."
)


class RuntimeOperationError(ValueError):
    code: OperationFailureCode
    summary: str
    is_retryable: bool
    suggested_next_step: str | None
    status_code_override: int | None

    def __init__(
        self,
        *,
        code: OperationFailureCode,
        summary: str,
        is_retryable: bool,
        suggested_next_step: str | None = None,
        status_code_override: int | None = None,
    ) -> None:
        super().__init__(summary)
        self.code = code
        self.summary = summary
        self.is_retryable = is_retryable
        self.suggested_next_step = suggested_next_step
        self.status_code_override = status_code_override


def illegal_caller_error(
    summary: str,
    *,
    suggested_next_step: str = ILLEGAL_CALLER_NEXT_STEP,
) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.ILLEGAL_CALLER,
        summary=summary,
        is_retryable=False,
        suggested_next_step=suggested_next_step,
    )


def illegal_state_error(
    summary: str,
    *,
    suggested_next_step: str = ILLEGAL_STATE_NEXT_STEP,
) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.ILLEGAL_STATE,
        summary=summary,
        is_retryable=False,
        suggested_next_step=suggested_next_step,
    )


def invalid_request_shape_error(
    summary: str,
    *,
    suggested_next_step: str = INVALID_REQUEST_SHAPE_NEXT_STEP,
) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.INVALID_REQUEST_SHAPE,
        summary=summary,
        is_retryable=False,
        suggested_next_step=suggested_next_step,
    )


def stale_assignment_error(
    summary: str,
    *,
    suggested_next_step: str = STALE_ASSIGNMENT_NEXT_STEP,
) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.STALE_ASSIGNMENT,
        summary=summary,
        is_retryable=True,
        suggested_next_step=suggested_next_step,
    )


def stale_team_revision_error(
    summary: str,
    *,
    suggested_next_step: str = STALE_TEAM_REVISION_NEXT_STEP,
) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.STALE_TEAM_REVISION,
        summary=summary,
        is_retryable=True,
        suggested_next_step=suggested_next_step,
    )


def stale_dispatch_error(
    summary: str,
    *,
    suggested_next_step: str = STALE_DISPATCH_NEXT_STEP,
) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.STALE_DISPATCH,
        summary=summary,
        is_retryable=False,
        suggested_next_step=suggested_next_step,
    )


def missing_resource_error(
    summary: str,
    *,
    suggested_next_step: str = MISSING_RESOURCE_NEXT_STEP,
) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.MISSING_RESOURCE,
        summary=summary,
        is_retryable=False,
        suggested_next_step=suggested_next_step,
    )


def budget_exhausted_error(
    summary: str,
    *,
    suggested_next_step: str = BUDGET_EXHAUSTED_NEXT_STEP,
) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.BUDGET_EXHAUSTED,
        summary=summary,
        is_retryable=False,
        suggested_next_step=suggested_next_step,
    )


__all__ = [
    "BUDGET_EXHAUSTED_NEXT_STEP",
    "ILLEGAL_CALLER_NEXT_STEP",
    "ILLEGAL_STATE_NEXT_STEP",
    "INVALID_REQUEST_SHAPE_NEXT_STEP",
    "MISSING_RESOURCE_NEXT_STEP",
    "STALE_ASSIGNMENT_NEXT_STEP",
    "STALE_DISPATCH_NEXT_STEP",
    "STALE_TEAM_REVISION_NEXT_STEP",
    "RuntimeOperationError",
    "budget_exhausted_error",
    "illegal_caller_error",
    "illegal_state_error",
    "invalid_request_shape_error",
    "missing_resource_error",
    "stale_assignment_error",
    "stale_dispatch_error",
    "stale_team_revision_error",
]
