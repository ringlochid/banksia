import pytest

from oh_my_subagents.runtime.assignment import snapshot_assignment_budget


def test_assignment_budget_snapshot_uses_deterministic_defaults() -> None:
    snapshot = snapshot_assignment_budget()

    assert (
        snapshot.child_assignment_limit,
        snapshot.child_assignments_remaining,
        snapshot.retry_limit,
        snapshot.retries_remaining,
    ) == (20, 20, 1, 1)


def test_assignment_budget_snapshot_pins_explicit_limits() -> None:
    snapshot = snapshot_assignment_budget(
        child_assignment_limit=3,
        retry_limit=2,
    )

    assert (
        snapshot.child_assignment_limit,
        snapshot.child_assignments_remaining,
        snapshot.retry_limit,
        snapshot.retries_remaining,
    ) == (3, 3, 2, 2)


@pytest.mark.parametrize("field_name", ("child_assignment_limit", "retry_limit"))
def test_assignment_budget_snapshot_rejects_a_negative_pinned_limit(field_name: str) -> None:
    values = {"child_assignment_limit": 20, "retry_limit": 1}
    values[field_name] = -1

    with pytest.raises(ValueError, match=rf"{field_name} must be nonnegative"):
        snapshot_assignment_budget(**values)
