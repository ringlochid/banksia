"""Internal records for resumable paused Task Attempt lanes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.ordinary_context import (
    OrdinaryContinuationBasis,
    OrdinaryDispatchSnapshot,
)
from banksia.runtime.dispatch.preparation import (
    PreparedDispatchRequest,
)
from banksia.runtime.errors import RuntimeOperationError

type OperatorContinueSourceClaim = Callable[
    [AsyncSession, OrdinaryDispatchSnapshot, PreparedDispatchRequest],
    Awaitable[bool],
]


@dataclass(frozen=True, slots=True)
class PausedAttemptLane:
    assignment_id: str
    attempt_id: str
    current_wait_id: str | None


@dataclass(frozen=True, slots=True)
class PausedTaskSnapshot:
    task_id: str
    current_team_revision_id: str
    control_revision: int
    pause_reason: str
    lanes: tuple[PausedAttemptLane, ...]


@dataclass(frozen=True, slots=True)
class OperatorContinueSource:
    basis: OrdinaryContinuationBasis
    claim: OperatorContinueSourceClaim

    @property
    def lane_key(self) -> tuple[str, str]:
        return self.basis.assignment_id, self.basis.attempt_id


@dataclass(frozen=True, slots=True)
class PausedTaskContinuationPlan:
    task: PausedTaskSnapshot
    sources: tuple[OperatorContinueSource, ...]
    has_unconsumed_task_start: bool


@dataclass(frozen=True, slots=True)
class PreparedPausedContinuation:
    snapshot: OrdinaryDispatchSnapshot
    prepared: PreparedDispatchRequest
    claim: OperatorContinueSourceClaim


@dataclass(frozen=True, slots=True)
class PausedTaskContinuationResult:
    outcome: Literal["resumed"]
    dispatch_ids: tuple[str, ...] = ()


def paused_continuation_preparation_error(exc: Exception) -> RuntimeOperationError:
    code = str(getattr(exc, "code", "operator_continue_preparation_failed"))
    return RuntimeOperationError(
        code=OperationFailureCode.ILLEGAL_STATE,
        summary=f"operator continue preparation failed: {code}",
        is_retryable=False,
        suggested_next_step="Repair the exact source or provider route, then retry continue.",
    )


def paused_continuation_conflict(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary=summary,
        is_retryable=False,
        suggested_next_step="Reread the Task and retry only from the same paused revision.",
        status_code_override=409,
    )


__all__ = [
    "OperatorContinueSource",
    "OperatorContinueSourceClaim",
    "PausedAttemptLane",
    "PausedTaskContinuationPlan",
    "PausedTaskContinuationResult",
    "PausedTaskSnapshot",
    "PreparedPausedContinuation",
    "paused_continuation_conflict",
    "paused_continuation_preparation_error",
]
