from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import TaskModel
from banksia.runtime.assignment.budget import (
    AssignmentBudgetSnapshot,
    snapshot_assignment_budget,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.authority import (
    NodeOperationAuthority,
    exact_node_operation_authority_exists,
)
from banksia.runtime.errors import RuntimeOperationError


async def read_task_assignment_budget_snapshot(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> AssignmentBudgetSnapshot:
    """Read Task-admitted child and retry limits under exact dispatch authority."""

    task = await session.scalar(
        select(TaskModel).where(
            TaskModel.task_id == authority.task_id,
            exact_node_operation_authority_exists(authority),
        )
    )
    if task is None:
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="another transition changed exact dispatch authority",
            is_retryable=False,
        )
    return snapshot_assignment_budget(
        child_assignment_limit=task.max_child_assignments_per_assignment,
        retry_limit=task.max_retries_per_assignment,
    )


__all__ = ["read_task_assignment_budget_snapshot"]
