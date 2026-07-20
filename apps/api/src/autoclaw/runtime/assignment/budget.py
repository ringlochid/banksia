from __future__ import annotations

from dataclasses import dataclass

from autoclaw.definitions.contracts import PolicyDefinitionInput


@dataclass(frozen=True)
class AssignmentBudgetSnapshot:
    child_assignment_limit: int | None
    child_assignments_remaining: int | None
    retry_limit: int | None
    retries_remaining: int | None


def snapshot_assignment_budget(
    policy: PolicyDefinitionInput,
) -> AssignmentBudgetSnapshot:
    budget = policy.budget_spec
    child_limit = budget.child_assignment_limit if budget is not None else None
    retry_limit = budget.retry_limit if budget is not None else None
    _require_nonnegative(child_limit, field_name="child_assignment_limit")
    _require_nonnegative(retry_limit, field_name="retry_limit")
    return AssignmentBudgetSnapshot(
        child_assignment_limit=child_limit,
        child_assignments_remaining=child_limit,
        retry_limit=retry_limit,
        retries_remaining=retry_limit,
    )


def _require_nonnegative(value: int | None, *, field_name: str) -> None:
    if value is not None and value < 0:
        raise ValueError(f"policy budget_spec.{field_name} must be nonnegative")


__all__ = ["AssignmentBudgetSnapshot", "snapshot_assignment_budget"]
