from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from autoclaw.runtime.contracts.common import RuntimeSchemaText


class OperationFailureCode(StrEnum):
    INVALID_REQUEST_SHAPE = "invalid_request_shape"
    LOCAL_ADMISSION_DENIED = "local_admission_denied"
    AUTHENTICATION_FAILED = "authentication_failed"
    SCOPE_MISMATCH = "scope_mismatch"
    ILLEGAL_CALLER = "illegal_caller"
    ILLEGAL_TARGET_RELATION = "illegal_target_relation"
    ILLEGAL_STATE = "illegal_state"
    STALE_DISPATCH = "stale_dispatch"
    STALE_FLOW_REVISION = "stale_flow_revision"
    STALE_ASSIGNMENT = "stale_assignment"
    STALE_CHECKPOINT = "stale_checkpoint"
    NAME_COLLISION = "name_collision"
    MISSING_RESOURCE = "missing_resource"
    MISSING_REQUIRED_PUBLICATION = "missing_required_publication"
    CONFLICTING_CONTINUATION = "conflicting_continuation"
    CURSOR_RESET_REQUIRED = "cursor_reset_required"
    BOUNDARY_PRECONDITION_FAILED = "boundary_precondition_failed"
    CAPABILITY_REJECTED = "capability_rejected"
    CONFLICT = "conflict"
    INVALID_TASK_PATH = "invalid_task_path"
    INVALID_TASK_ROOT = "invalid_task_root"
    PATH_ESCAPE = "path_escape"
    NOT_A_DIRECTORY = "not_a_directory"
    NOT_A_FILE = "not_a_file"
    BINARY_FILE = "binary_file"
    FILE_READ_LIMIT_EXCEEDED = "file_read_limit_exceeded"
    DIRECTORY_LIMIT_EXCEEDED = "directory_limit_exceeded"
    REMOVED_SURFACE = "removed_surface"
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
