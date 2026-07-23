from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import AssignmentModel, AttemptModel
from banksia.runtime.assignment import (
    AssignmentBudgetSnapshot,
    snapshot_assignment_budget,
    stage_assignment_file_references,
)
from banksia.runtime.contracts import RuntimeBootstrapInput, RuntimeBootstrapResult
from banksia.runtime.ids import assignment_id


async def stage_launch_attempt_rows(
    session: AsyncSession,
    *,
    bootstrap_input: RuntimeBootstrapInput,
    result: RuntimeBootstrapResult,
    flow_id: str,
) -> None:
    """Stage the initial target assignment and attempt for a fresh task."""

    assignment_row = _build_assignment_row(
        bootstrap_input=bootstrap_input,
        result=result,
        flow_id=flow_id,
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
            flow_id=flow_id,
            node_key=bootstrap_input.initial_team.root_member_id,
            retry_of_attempt_id=None,
            latest_checkpoint_id=None,
            status="running",
        )
    )
    await session.flush()


def _build_assignment_row(
    *,
    bootstrap_input: RuntimeBootstrapInput,
    result: RuntimeBootstrapResult,
    flow_id: str,
) -> AssignmentModel:
    node = next(
        (
            item
            for item in bootstrap_input.compiled_plan.nodes
            if item.node_key == bootstrap_input.initial_team.root_member_id
        ),
        None,
    )
    if node is None:
        raise ValueError("legacy Team plan is missing its root assignment Member")
    budget = _resolve_assignment_budget(
        bootstrap_input=bootstrap_input,
        node_key=bootstrap_input.initial_team.root_member_id,
    )
    return AssignmentModel(
        assignment_id=assignment_id(bootstrap_input.assignment_key),
        task_id=bootstrap_input.task_id,
        member_id=node.member_id,
        flow_id=flow_id,
        assignment_key=bootstrap_input.assignment_key,
        node_key=bootstrap_input.initial_team.root_member_id,
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


def _resolve_assignment_budget(
    *,
    bootstrap_input: RuntimeBootstrapInput,
    node_key: str,
) -> AssignmentBudgetSnapshot:
    node = next(
        (item for item in bootstrap_input.compiled_plan.nodes if item.node_key == node_key),
        None,
    )
    if node is None:
        raise ValueError(f"compiled plan is missing assignment node '{node_key}'")
    return snapshot_assignment_budget(
        child_assignment_limit=bootstrap_input.max_child_assignments_per_assignment,
        retry_limit=bootstrap_input.max_retries_per_assignment,
    )


__all__ = ["stage_launch_attempt_rows"]
