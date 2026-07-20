from __future__ import annotations

from autoclaw.runtime.contracts.operation_failure import OperationFailureCode

ILLEGAL_CALLER_NEXT_STEP = (
    "Reread the current dispatch context and use only the tools or boundaries legal "
    "for this node and this open dispatch."
)
ILLEGAL_STATE_NEXT_STEP = (
    "Reread the current manifest, assignment, checkpoint, and surfaced refs, then "
    "choose a tool or boundary that matches the current state."
)
STALE_ASSIGNMENT_NEXT_STEP = (
    "Reread the current assignment projection and resend the request only if the "
    "same assignment is still current."
)
STALE_FLOW_REVISION_NEXT_STEP = (
    "Reread the regenerated workflow manifest and current structural revision, "
    "then rebuild the request against that newer structure."
)
MISSING_RESOURCE_NEXT_STEP = (
    "Verify the task, flow, or dispatch id and reread the current runtime surface "
    "before retrying this request."
)
SEMANTIC_MISSING_RESOURCE_NEXT_STEP = (
    "Reread the current manifest, assignment, and surfaced refs, then stage or "
    "publish the missing dependency basis before retrying this request."
)
MISSING_REQUIRED_PUBLICATION_NEXT_STEP = (
    "Publish or republish the missing durable or surfaced release basis first, then "
    "retry the control action or reread the surfaced release inputs."
)
BUDGET_EXHAUSTED_NEXT_STEP = (
    "Surface the latest terminal checkpoint to the relevant parent or root so it can "
    "choose a fresh assignment or another legal path."
)
BOUNDARY_PRECONDITION_NEXT_STEP = (
    "Reread the current checkpoint, release basis, and staged continuation state, "
    "then publish or commit the missing prerequisite before retrying the boundary."
)
CONFLICTING_CONTINUATION_NEXT_STEP = (
    "Publish a progress checkpoint if later readers need the reasoning, then close "
    "with the matching boundary instead of staging another outcome."
)
INVALID_REQUEST_SHAPE_NEXT_STEP = (
    "Reread the canonical request shape and resend the request with only the live required fields."
)
ILLEGAL_TARGET_RELATION_NEXT_STEP = (
    "Reread the current workflow manifest and owned subtree, then target only "
    "a node this caller may edit or choose a different legal action."
)
STALE_CHECKPOINT_NEXT_STEP = (
    "Reread the latest relevant checkpoint and current surfaced refs, then decide "
    "again from that newer handover."
)
STALE_DISPATCH_NEXT_STEP = (
    "Reread the current dispatch context and retry only if this node is still "
    "the current caller for an open dispatch."
)
NAME_COLLISION_NEXT_STEP = (
    "Choose a different definition key, or open the existing definition in update mode "
    "before publishing a new revision."
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


def illegal_target_relation_error(
    summary: str,
    *,
    suggested_next_step: str = ILLEGAL_TARGET_RELATION_NEXT_STEP,
) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.ILLEGAL_TARGET_RELATION,
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


def stale_flow_revision_error(
    summary: str,
    *,
    suggested_next_step: str = STALE_FLOW_REVISION_NEXT_STEP,
) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.STALE_FLOW_REVISION,
        summary=summary,
        is_retryable=True,
        suggested_next_step=suggested_next_step,
    )


def stale_checkpoint_error(
    summary: str,
    *,
    suggested_next_step: str = STALE_CHECKPOINT_NEXT_STEP,
) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.STALE_CHECKPOINT,
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


def name_collision_error(
    summary: str,
    *,
    suggested_next_step: str = NAME_COLLISION_NEXT_STEP,
) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.NAME_COLLISION,
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


def semantic_missing_resource_error(
    summary: str,
    *,
    suggested_next_step: str = SEMANTIC_MISSING_RESOURCE_NEXT_STEP,
) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.MISSING_RESOURCE,
        summary=summary,
        is_retryable=False,
        suggested_next_step=suggested_next_step,
        status_code_override=422,
    )


def missing_required_publication_error(
    summary: str,
    *,
    suggested_next_step: str = MISSING_REQUIRED_PUBLICATION_NEXT_STEP,
) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.MISSING_REQUIRED_PUBLICATION,
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


def boundary_precondition_error(
    summary: str,
    *,
    suggested_next_step: str = BOUNDARY_PRECONDITION_NEXT_STEP,
) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.BOUNDARY_PRECONDITION_FAILED,
        summary=summary,
        is_retryable=False,
        suggested_next_step=suggested_next_step,
    )


def conflicting_continuation_error(
    summary: str,
    *,
    suggested_next_step: str = CONFLICTING_CONTINUATION_NEXT_STEP,
) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICTING_CONTINUATION,
        summary=summary,
        is_retryable=False,
        suggested_next_step=suggested_next_step,
    )


__all__ = [
    "BOUNDARY_PRECONDITION_NEXT_STEP",
    "BUDGET_EXHAUSTED_NEXT_STEP",
    "CONFLICTING_CONTINUATION_NEXT_STEP",
    "ILLEGAL_CALLER_NEXT_STEP",
    "ILLEGAL_STATE_NEXT_STEP",
    "ILLEGAL_TARGET_RELATION_NEXT_STEP",
    "INVALID_REQUEST_SHAPE_NEXT_STEP",
    "MISSING_REQUIRED_PUBLICATION_NEXT_STEP",
    "MISSING_RESOURCE_NEXT_STEP",
    "SEMANTIC_MISSING_RESOURCE_NEXT_STEP",
    "STALE_ASSIGNMENT_NEXT_STEP",
    "STALE_CHECKPOINT_NEXT_STEP",
    "STALE_DISPATCH_NEXT_STEP",
    "STALE_FLOW_REVISION_NEXT_STEP",
    "RuntimeOperationError",
    "boundary_precondition_error",
    "budget_exhausted_error",
    "conflicting_continuation_error",
    "illegal_caller_error",
    "illegal_state_error",
    "illegal_target_relation_error",
    "invalid_request_shape_error",
    "missing_required_publication_error",
    "missing_resource_error",
    "semantic_missing_resource_error",
    "stale_assignment_error",
    "stale_checkpoint_error",
    "stale_dispatch_error",
    "stale_flow_revision_error",
]
