from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentDecisionModel,
    AssignmentModel,
    AttemptCheckpointModel,
    AttemptModel,
    FlowNodeModel,
    NodePlanRevisionModel,
)
from banksia.runtime.assignment import read_assignment_file_references
from banksia.runtime.checkpoint.reads import read_checkpoint_file_references
from banksia.runtime.contracts.primitives import CheckpointOutcome, EgressBoundary
from banksia.runtime.contracts.prompt import (
    AcceptedBoundaryResult,
    AcceptedBoundarySource,
    AcceptedBoundaryTrigger,
    ChildReturnResult,
    ChildReturnSource,
    ChildReturnTrigger,
    PromptAssignment,
    PromptCheckpointSummary,
    SemanticRetryResult,
    SemanticRetrySource,
    SemanticRetryTrigger,
)
from banksia.runtime.dispatch.prompt_snapshot import BoundaryPromptTrigger


@dataclass(frozen=True, slots=True)
class BoundaryTarget:
    assignment_id: str
    attempt_id: str
    opened_reason: str
    trigger: BoundaryPromptTrigger


async def resolve_boundary_target(
    session: AsyncSession,
    *,
    boundary: AcceptedBoundaryModel,
    source_assignment: AssignmentModel,
) -> BoundaryTarget:
    if boundary.outcome == "yield":
        return await _resolve_yield_target(session, boundary)
    checkpoint = await _read_boundary_checkpoint(session, boundary)
    if boundary.outcome == "retry":
        return await _resolve_retry_target(
            session,
            boundary=boundary,
            source_assignment=source_assignment,
            checkpoint=checkpoint,
        )
    return await _resolve_child_return_target(
        session,
        boundary=boundary,
        source_assignment=source_assignment,
        checkpoint=checkpoint,
    )


def require_consistent_target_runtime_context(
    node: FlowNodeModel,
    node_plan: NodePlanRevisionModel,
    assignment: AssignmentModel,
    attempt: AttemptModel,
) -> None:
    """Reject a target whose assignment, attempt, and exact Team pins disagree."""

    if (
        node.state != "running"
        or node.current_assignment_id != assignment.assignment_id
        or assignment.current_attempt_id != attempt.attempt_id
        or assignment.superseded_at is not None
        or attempt.status != "running"
        or node_plan.task_id != node.task_id
        or node_plan.team_revision_id != node.team_revision_id
        or node_plan.member_id != node.member_id
        or node_plan.member_configuration_id != node.member_configuration_id
        or node_plan.member_branch_basis_id != node.member_branch_basis_id
        or assignment.member_id != node.member_id
        or assignment.node_key != node.node_key
        or node_plan.provider_kind != node.provider_kind
    ):
        raise ValueError("boundary target has inconsistent pinned runtime context")


async def _resolve_yield_target(
    session: AsyncSession,
    boundary: AcceptedBoundaryModel,
) -> BoundaryTarget:
    decision = await session.scalar(
        select(AssignmentDecisionModel)
        .options(raiseload("*"))
        .where(
            AssignmentDecisionModel.assignment_decision_id == boundary.assignment_decision_id,
            AssignmentDecisionModel.source_dispatch_id == boundary.source_dispatch_id,
            AssignmentDecisionModel.decision_kind == "staged_child",
        )
    )
    if (
        decision is None
        or decision.staged_child_assignment_id is None
        or decision.staged_child_attempt_id is None
    ):
        raise ValueError("yield boundary is missing its exact staged child")
    return BoundaryTarget(
        assignment_id=decision.staged_child_assignment_id,
        attempt_id=decision.staged_child_attempt_id,
        opened_reason="boundary",
        trigger=AcceptedBoundaryTrigger(
            source=AcceptedBoundarySource(
                accepted_boundary_id=boundary.accepted_boundary_id,
                source_dispatch_id=boundary.source_dispatch_id,
            ),
            result=AcceptedBoundaryResult(outcome=EgressBoundary.YIELD),
        ),
    )


async def _resolve_retry_target(
    session: AsyncSession,
    *,
    boundary: AcceptedBoundaryModel,
    source_assignment: AssignmentModel,
    checkpoint: PromptCheckpointSummary,
) -> BoundaryTarget:
    retry_attempt_id = source_assignment.current_attempt_id
    if retry_attempt_id is None or retry_attempt_id == boundary.attempt_id:
        raise ValueError("retry boundary is missing its new semantic attempt")
    retry_attempt = await session.scalar(
        select(AttemptModel.attempt_id).where(
            AttemptModel.attempt_id == retry_attempt_id,
            AttemptModel.assignment_id == source_assignment.assignment_id,
            AttemptModel.retry_of_attempt_id == boundary.attempt_id,
            AttemptModel.status == "running",
        )
    )
    if retry_attempt is None:
        raise ValueError("retry boundary does not point to its exact retry attempt")
    return BoundaryTarget(
        assignment_id=source_assignment.assignment_id,
        attempt_id=retry_attempt_id,
        opened_reason="semantic_retry",
        trigger=SemanticRetryTrigger(
            source=SemanticRetrySource(
                accepted_boundary_id=boundary.accepted_boundary_id,
                source_dispatch_id=boundary.source_dispatch_id,
                previous_attempt_id=boundary.attempt_id,
            ),
            result=SemanticRetryResult(checkpoint=checkpoint),
        ),
    )


async def _resolve_child_return_target(
    session: AsyncSession,
    *,
    boundary: AcceptedBoundaryModel,
    source_assignment: AssignmentModel,
    checkpoint: PromptCheckpointSummary,
) -> BoundaryTarget:
    parent_assignment_id = source_assignment.parent_assignment_id
    if parent_assignment_id is None:
        raise ValueError("nonterminal boundary routing is missing parent lineage")
    parent = await session.scalar(
        select(AssignmentModel)
        .options(raiseload("*"))
        .where(
            AssignmentModel.assignment_id == parent_assignment_id,
            AssignmentModel.task_id == boundary.task_id,
            AssignmentModel.flow_id == boundary.flow_id,
            AssignmentModel.superseded_at.is_(None),
        )
    )
    if parent is None or parent.current_attempt_id is None:
        raise ValueError("child return is missing its exact current parent")
    if boundary.outcome == "green":
        child_outcome = EgressBoundary.GREEN
    elif boundary.outcome == "blocked":
        child_outcome = EgressBoundary.BLOCKED
    else:
        raise ValueError("child return boundary has an unsupported outcome")
    child_files = await read_assignment_file_references(
        session,
        assignment_id=source_assignment.assignment_id,
    )
    return BoundaryTarget(
        assignment_id=parent.assignment_id,
        attempt_id=parent.current_attempt_id,
        opened_reason="child_return",
        trigger=ChildReturnTrigger(
            source=ChildReturnSource(
                child_assignment_id=boundary.assignment_id,
                child_attempt_id=boundary.attempt_id,
                source_dispatch_id=boundary.source_dispatch_id,
                accepted_boundary_id=boundary.accepted_boundary_id,
            ),
            result=ChildReturnResult(
                assignment=PromptAssignment(
                    id=source_assignment.assignment_id,
                    prompt=source_assignment.prompt,
                    files=child_files,
                ),
                outcome=child_outcome,
                checkpoint=checkpoint,
            ),
        ),
    )


async def _read_boundary_checkpoint(
    session: AsyncSession,
    boundary: AcceptedBoundaryModel,
) -> PromptCheckpointSummary:
    if boundary.checkpoint_id is None:
        raise ValueError("terminal boundary is missing its checkpoint identity")
    checkpoint = await session.scalar(
        select(AttemptCheckpointModel)
        .options(raiseload("*"))
        .where(
            AttemptCheckpointModel.checkpoint_id == boundary.checkpoint_id,
            AttemptCheckpointModel.task_id == boundary.task_id,
            AttemptCheckpointModel.flow_id == boundary.flow_id,
            AttemptCheckpointModel.assignment_id == boundary.assignment_id,
            AttemptCheckpointModel.attempt_id == boundary.attempt_id,
            AttemptCheckpointModel.authoring_dispatch_id == boundary.source_dispatch_id,
            AttemptCheckpointModel.outcome == boundary.outcome,
        )
    )
    if checkpoint is None or checkpoint.outcome is None:
        raise ValueError("accepted boundary checkpoint no longer matches its source")
    files = await read_checkpoint_file_references(
        session,
        checkpoint_id=checkpoint.checkpoint_id,
    )
    return PromptCheckpointSummary(
        id=checkpoint.checkpoint_id,
        summary=checkpoint.summary,
        details=checkpoint.details,
        files=files,
        outcome=CheckpointOutcome(checkpoint.outcome),
    )


__all__ = [
    "BoundaryTarget",
    "require_consistent_target_runtime_context",
    "resolve_boundary_target",
]
