from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import AssignmentModel, AttemptModel
from banksia.runtime.assignment import (
    AssignmentBudgetSnapshot,
    snapshot_assignment_budget,
)
from banksia.runtime.contracts import (
    EvidenceRef,
    NodeRuntimeFileRef,
    RuntimeBootstrapInput,
    RuntimeBootstrapResult,
)
from banksia.runtime.ids import assignment_id, flow_node_id
from banksia.runtime.launch.bootstrap.criteria import stage_assignment_criteria_refs


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
    stage_assignment_criteria_refs(session, assignment_row)

    session.add(
        AttemptModel(
            attempt_id=bootstrap_input.attempt_id,
            assignment_id=assignment_row.assignment_id,
            task_id=bootstrap_input.task_id,
            flow_id=flow_id,
            node_key=result.assignment.node_key,
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
            if item.node_key == result.assignment.node_key
        ),
        None,
    )
    if node is None:
        raise ValueError(
            f"legacy Team plan is missing assignment Member {result.assignment.node_key!r}"
        )
    budget = _resolve_assignment_budget(
        bootstrap_input=bootstrap_input,
        node_key=result.assignment.node_key,
    )
    return AssignmentModel(
        assignment_id=assignment_id(result.assignment.assignment_key),
        task_id=bootstrap_input.task_id,
        team_revision_id=bootstrap_input.initial_team.team_revision_id,
        member_id=node.member_id,
        member_configuration_id=node.member_configuration_id,
        member_branch_basis_id=node.member_branch_basis_id,
        flow_id=flow_id,
        flow_revision_id=bootstrap_input.active_flow_revision_id,
        flow_node_id=flow_node_id(
            bootstrap_input.active_flow_revision_id,
            result.assignment.node_key,
        ),
        assignment_key=result.assignment.assignment_key,
        node_key=result.assignment.node_key,
        parent_assignment_id=None,
        summary=result.assignment.summary,
        instruction=result.assignment.instruction,
        criteria_json=[ref.model_dump(mode="json") for ref in result.assignment.criteria],
        consumes_json=[_ref_json(ref) for ref in result.assignment.consumes],
        produces_json=[
            requirement.model_dump(mode="json") for requirement in result.assignment.produces
        ],
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


def _ref_json(ref: EvidenceRef | NodeRuntimeFileRef) -> dict[str, Any]:
    return ref.model_dump(mode="json")


__all__ = ["stage_launch_attempt_rows"]
