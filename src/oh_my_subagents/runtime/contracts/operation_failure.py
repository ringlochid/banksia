from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from oh_my_subagents.runtime.contracts.common import RuntimeSchemaText


class OperationFailureCode(StrEnum):
    INVALID_REQUEST_SHAPE = "invalid_request_shape"
    LOCAL_ADMISSION_DENIED = "local_admission_denied"
    AUTHENTICATION_FAILED = "authentication_failed"
    SCOPE_MISMATCH = "scope_mismatch"
    ILLEGAL_CALLER = "illegal_caller"
    ILLEGAL_TARGET_RELATION = "illegal_target_relation"
    ILLEGAL_STATE = "illegal_state"
    STALE_DISPATCH = "stale_dispatch"
    STALE_TEAM_REVISION = "stale_team_revision"
    STALE_ASSIGNMENT = "stale_assignment"
    NAME_COLLISION = "name_collision"
    MISSING_RESOURCE = "missing_resource"
    CONFLICTING_CONTINUATION = "conflicting_continuation"
    CURSOR_RESET_REQUIRED = "cursor_reset_required"
    BOUNDARY_PRECONDITION_FAILED = "boundary_precondition_failed"
    CAPABILITY_REJECTED = "capability_rejected"
    CONFLICT = "conflict"
    INVALID_TASK_PATH = "invalid_task_path"
    INVALID_TASK_ROOT = "invalid_task_root"
    BUDGET_EXHAUSTED = "budget_exhausted"
    INTERNAL_ERROR = "internal_error"


class OperationFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: Literal[False] = False
    code: OperationFailureCode
    summary: RuntimeSchemaText
    retryable: bool
    field_path: RuntimeSchemaText | None = None
    suggested_next_step: RuntimeSchemaText | None = None


__all__ = ["OperationFailure", "OperationFailureCode"]
