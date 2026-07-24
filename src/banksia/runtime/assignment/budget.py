from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AssignmentBudgetSnapshot:
    child_assignment_limit: int
    child_assignments_remaining: int
    retry_limit: int
    retries_remaining: int


def snapshot_assignment_budget(
    *,
    child_assignment_limit: int = 20,
    retry_limit: int = 1,
) -> AssignmentBudgetSnapshot:
    _require_nonnegative(child_assignment_limit, field_name="child_assignment_limit")
    _require_nonnegative(retry_limit, field_name="retry_limit")
    return AssignmentBudgetSnapshot(
        child_assignment_limit=child_assignment_limit,
        child_assignments_remaining=child_assignment_limit,
        retry_limit=retry_limit,
        retries_remaining=retry_limit,
    )


def _require_nonnegative(value: int, *, field_name: str) -> None:
    if value < 0:
        raise ValueError(f"{field_name} must be nonnegative")


__all__ = ["AssignmentBudgetSnapshot", "snapshot_assignment_budget"]
