from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.persistence.models import AssignmentModel, AttemptModel
from oh_my_subagents.runtime.assignment import (
    snapshot_assignment_budget,
    stage_assignment_file_references,
)
from oh_my_subagents.runtime.contracts import RuntimeBootstrapInput, RuntimeBootstrapResult


async def stage_launch_attempt_rows(
    session: AsyncSession,
    *,
    bootstrap_input: RuntimeBootstrapInput,
    result: RuntimeBootstrapResult,
) -> AssignmentModel:
    """Stage the root Assignment and Attempt for a fresh Task."""

    budget = snapshot_assignment_budget(
        child_assignment_limit=bootstrap_input.max_child_assignments_per_assignment,
        retry_limit=bootstrap_input.max_retries_per_assignment,
    )
    assignment_row = AssignmentModel(
        assignment_id=bootstrap_input.assignment_id,
        task_id=bootstrap_input.task_id,
        member_id=bootstrap_input.initial_team.root_member_id,
        parent_assignment_id=None,
        prompt=result.assignment.prompt,
        current_attempt_id=bootstrap_input.attempt_id,
        work_plan_revision=0,
        child_assignment_limit=budget.child_assignment_limit,
        child_assignments_remaining=budget.child_assignments_remaining,
        retry_limit=budget.retry_limit,
        retries_remaining=budget.retries_remaining,
        created_by_dispatch_id=None,
    )
    session.add(assignment_row)
    await session.flush()
    stage_assignment_file_references(
        session,
        assignment_id=assignment_row.assignment_id,
        files=result.assignment.files,
    )
    session.add(
        AttemptModel(
            attempt_id=bootstrap_input.attempt_id,
            assignment_id=assignment_row.assignment_id,
            task_id=bootstrap_input.task_id,
            retry_of_attempt_id=None,
            latest_checkpoint_id=None,
            current_dispatch_id=None,
            current_wait_id=None,
            status="running",
        )
    )
    await session.flush()
    return assignment_row


__all__ = ["stage_launch_attempt_rows"]
