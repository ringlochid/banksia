import pytest
from autoclaw.definitions.contracts import BudgetSpec, PolicyDefinitionInput
from autoclaw.definitions.contracts.workflow import NodeKind
from autoclaw.runtime.assignment import snapshot_assignment_budget


@pytest.mark.parametrize(
    ("applies_to", "budget_spec", "expected"),
    (
        (
            [NodeKind.ROOT],
            None,
            (None, None, None, None),
        ),
        (
            [NodeKind.PARENT],
            BudgetSpec(child_assignment_limit=3),
            (3, 3, None, None),
        ),
        (
            [NodeKind.WORKER],
            BudgetSpec(retry_limit=2),
            (None, None, 2, 2),
        ),
    ),
)
def test_assignment_budget_snapshot_copies_each_applicable_limit(
    applies_to: list[NodeKind],
    budget_spec: BudgetSpec | None,
    expected: tuple[int | None, int | None, int | None, int | None],
) -> None:
    policy = PolicyDefinitionInput(
        id="policy.target",
        description="Bound assignment work.",
        applies_to=applies_to,
        budget_spec=budget_spec,
    )

    snapshot = snapshot_assignment_budget(policy)

    assert (
        snapshot.child_assignment_limit,
        snapshot.child_assignments_remaining,
        snapshot.retry_limit,
        snapshot.retries_remaining,
    ) == expected


def test_assignment_budget_snapshot_rejects_a_negative_pinned_limit() -> None:
    policy = PolicyDefinitionInput(
        id="policy.target",
        description="Invalid persisted policy input.",
        applies_to=[NodeKind.WORKER],
        budget_spec=BudgetSpec(retry_limit=-1),
    )

    with pytest.raises(ValueError, match="retry_limit must be nonnegative"):
        snapshot_assignment_budget(policy)
