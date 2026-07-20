from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.persistence.models import AssignmentModel, AttemptModel
from autoclaw.runtime.assignment import (
    AssignmentBudgetSnapshot,
    snapshot_assignment_budget,
)
from autoclaw.runtime.contracts import (
    EvidenceRef,
    NodeRuntimeFileRef,
    RuntimeBootstrapInput,
    RuntimeBootstrapResult,
)
from autoclaw.runtime.ids import assignment_id, flow_node_id
from autoclaw.runtime.launch.bootstrap.criteria import stage_assignment_criteria_refs
from autoclaw.runtime.launch.bootstrap.revisions import resolve_pinned_role_policy


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
    budget = _resolve_assignment_budget(
        bootstrap_input=bootstrap_input,
        node_key=result.assignment.node_key,
    )
    return AssignmentModel(
        assignment_id=assignment_id(result.assignment.assignment_key),
        task_id=bootstrap_input.task_id,
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
    _, policy = resolve_pinned_role_policy(
        bootstrap_input.role_policy_lookup,
        role_key=node.role,
        role_revision_no=node.role_revision_no,
        policy_key=node.policy,
        policy_revision_no=node.policy_revision_no,
    )
    return snapshot_assignment_budget(policy.definition)


def _ref_json(ref: EvidenceRef | NodeRuntimeFileRef) -> dict[str, Any]:
    return ref.model_dump(mode="json")


__all__ = ["stage_launch_attempt_rows"]
