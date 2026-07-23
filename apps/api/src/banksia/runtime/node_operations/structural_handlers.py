from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AssignmentDecisionModel,
    AssignmentModel,
    AttemptCheckpointModel,
    AttemptModel,
    FlowNodeModel,
)
from banksia.runtime.assignment import (
    AssignmentBudgetSnapshot,
    read_task_assignment_budget_snapshot,
    stage_assignment_file_references,
)
from banksia.runtime.clock import utc_now
from banksia.runtime.contracts import (
    AssignChildSuccess,
    FileReference,
    TaskEventSource,
    TaskEventType,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.authority import (
    NodeOperationAuthority,
    exact_node_operation_authority_exists,
)
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError, budget_exhausted_error
from banksia.runtime.file_references import validate_file_references
from banksia.runtime.node_operations.contracts import (
    AssignChildRequest,
    NodeOperationName,
)
from banksia.runtime.node_operations.follow_on import (
    CommittedNodeOperationFollowOn,
    CommittedNodeOperationResult,
)
from banksia.runtime.node_operations.result_reads import runtime_flow_read
from banksia.runtime.replan import commit_replan
from banksia.runtime.task_events import append_task_event
from banksia.runtime.task_root.reads import read_task_root_paths


async def execute_structural_node_operation(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    operation_name: NodeOperationName,
    request: BaseModel,
    *,
    dispatch_opening_dependencies: DispatchOpeningDependencies | None,
) -> BaseModel:
    if operation_name in {
        NodeOperationName.ADD_CHILD,
        NodeOperationName.UPDATE_CHILD,
        NodeOperationName.REMOVE_CHILD,
    }:
        if dispatch_opening_dependencies is None:
            raise RuntimeOperationError(
                code=OperationFailureCode.INTERNAL_ERROR,
                summary="replan provider resolution is not configured",
                is_retryable=False,
            )
        return await commit_replan(
            session,
            authority,
            operation_name,
            request,
            dependencies=dispatch_opening_dependencies,
        )
    if operation_name == NodeOperationName.ASSIGN_CHILD:
        assert isinstance(request, AssignChildRequest)
        return await _assign_child(session, authority, request)
    raise RuntimeOperationError(
        code=OperationFailureCode.INVALID_REQUEST_SHAPE,
        summary=f"unsupported Node operation '{operation_name.value}'",
        is_retryable=False,
    )


async def _assign_child(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    request: AssignChildRequest,
) -> CommittedNodeOperationResult:
    _require_expected_revision(authority, request.expected_structural_revision_id)
    await _require_no_staged_decision(session, authority)

    target, previous_assignment = await _read_assignable_direct_child(
        session,
        authority,
        request,
    )
    budget = await read_task_assignment_budget_snapshot(session, authority)
    paths = await read_task_root_paths(session, authority.task_id)
    files = validate_file_references(
        paths.workspace_path,
        request.payload.assignment.files,
    )
    assignment, attempt = _build_child_assignment(
        authority,
        request,
        target,
        budget=budget,
    )
    await _consume_child_assignment_budget(session, authority)
    await _claim_child_node(
        session,
        authority,
        target,
        assignment.assignment_id,
        previous_assignment_id=(
            previous_assignment.assignment_id if previous_assignment is not None else None
        ),
    )
    if previous_assignment is not None:
        await _supersede_child_assignment(session, authority, previous_assignment)

    await _stage_child_assignment_records(
        session,
        authority,
        assignment,
        attempt,
        files=files,
    )
    await session.commit()

    flow = await runtime_flow_read(session, authority)
    response = AssignChildSuccess(
        summary="Child assignment staged for the selected direct child.",
        target_node_key=target.node_key,
        target_assignment_key=assignment.assignment_key,
        target_attempt_id=attempt.attempt_id,
        flow=flow,
        workflow_manifest_ref=flow.workflow_manifest_ref,
    )
    return CommittedNodeOperationResult(
        response=response,
        follow_on=CommittedNodeOperationFollowOn(),
    )


async def _stage_child_assignment_records(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    assignment: AssignmentModel,
    attempt: AttemptModel,
    *,
    files: tuple[FileReference, ...],
) -> None:
    session.add_all((assignment, attempt))
    stage_assignment_file_references(
        session,
        assignment_id=assignment.assignment_id,
        files=files,
    )
    _stage_child_assignment_decision(session, authority, assignment, attempt)
    await append_task_event(
        session,
        task_id=authority.task_id,
        event_type=TaskEventType.CHILD_ASSIGNMENT_STAGED,
        event_source=TaskEventSource.NODE,
        flow_revision_id=authority.flow_revision_id,
        dispatch_id=authority.dispatch_id,
        attempt_id=authority.attempt_id,
        node_key=authority.node_key,
        payload={
            "source_dispatch_id": authority.dispatch_id,
            "parent_assignment_id": authority.assignment_id,
            "child_assignment_id": assignment.assignment_id,
            "child_attempt_id": attempt.attempt_id,
            "child_node_key": assignment.node_key,
            "flow_revision_id": authority.flow_revision_id,
        },
    )


async def _consume_child_assignment_budget(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> None:
    consumed = await session.scalar(
        update(AssignmentModel)
        .where(
            AssignmentModel.assignment_id == authority.assignment_id,
            AssignmentModel.task_id == authority.task_id,
            AssignmentModel.flow_id == authority.flow_id,
            AssignmentModel.member_id == authority.flow_node.member_id,
            AssignmentModel.current_attempt_id == authority.attempt_id,
            AssignmentModel.closed_at.is_(None),
            AssignmentModel.superseded_at.is_(None),
            (AssignmentModel.child_assignments_remaining.is_(None))
            | (AssignmentModel.child_assignments_remaining > 0),
            exact_node_operation_authority_exists(authority),
        )
        .values(
            child_assignments_remaining=case(
                (
                    AssignmentModel.child_assignments_remaining.is_not(None),
                    AssignmentModel.child_assignments_remaining - 1,
                ),
                else_=None,
            )
        )
        .returning(AssignmentModel.assignment_id)
    )
    if consumed is None:
        raise budget_exhausted_error("the current assignment has no child assignments remaining")


async def _read_assignable_direct_child(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    request: AssignChildRequest,
) -> tuple[FlowNodeModel, AssignmentModel | None]:
    target = await session.scalar(
        select(FlowNodeModel).where(
            FlowNodeModel.flow_revision_id == authority.flow_revision_id,
            FlowNodeModel.node_key == request.payload.child_node_key,
            FlowNodeModel.parent_node_key == authority.node_key,
        )
    )
    if target is None:
        raise RuntimeOperationError(
            code=OperationFailureCode.ILLEGAL_TARGET_RELATION,
            summary="assign_child must target one direct child of the current node",
            is_retryable=False,
        )
    if target.current_assignment_id is None:
        if target.state != "ready":
            raise RuntimeOperationError(
                code=OperationFailureCode.ILLEGAL_STATE,
                summary="the target child is not ready for an assignment",
                is_retryable=False,
            )
        return target, None

    previous_assignment = await session.get(
        AssignmentModel,
        target.current_assignment_id,
    )
    previous_attempt = (
        await session.get(AttemptModel, previous_assignment.current_attempt_id)
        if previous_assignment is not None and previous_assignment.current_attempt_id is not None
        else None
    )
    previous_checkpoint = (
        await session.get(AttemptCheckpointModel, previous_attempt.latest_checkpoint_id)
        if previous_attempt is not None and previous_attempt.latest_checkpoint_id is not None
        else None
    )
    historical_parent_is_current = (
        previous_assignment is not None
        and previous_assignment.parent_assignment_id == authority.assignment_id
    )
    historical_parent = (
        await session.get(AssignmentModel, previous_assignment.parent_assignment_id)
        if previous_assignment is not None
        and previous_assignment.parent_assignment_id is not None
        and not historical_parent_is_current
        else None
    )
    historical_parent_is_same_node = historical_parent_is_current or (
        historical_parent is not None
        and historical_parent.task_id == authority.task_id
        and historical_parent.flow_id == authority.flow_id
        and historical_parent.member_id == authority.assignment.member_id
        and historical_parent.node_key == authority.node_key
        and historical_parent.superseded_at is not None
    )
    if (
        previous_assignment is None
        or previous_assignment.task_id != authority.task_id
        or previous_assignment.flow_id != authority.flow_id
        or previous_assignment.member_id != target.member_id
        or previous_assignment.node_key != target.node_key
        or not historical_parent_is_same_node
        or previous_assignment.superseded_at is not None
        or previous_assignment.closed_at is None
        or previous_assignment.terminal_outcome not in {"green", "blocked"}
        or previous_attempt is None
        or previous_attempt.task_id != authority.task_id
        or previous_attempt.flow_id != authority.flow_id
        or previous_attempt.assignment_id != previous_assignment.assignment_id
        or previous_attempt.node_key != target.node_key
        or previous_attempt.status != "completed"
        or previous_attempt.terminal_outcome not in {"green", "blocked"}
        or previous_checkpoint is None
        or previous_checkpoint.task_id != authority.task_id
        or previous_checkpoint.flow_id != authority.flow_id
        or previous_checkpoint.assignment_id != previous_assignment.assignment_id
        or previous_checkpoint.attempt_id != previous_attempt.attempt_id
        or previous_checkpoint.outcome != previous_attempt.terminal_outcome
        or target.state not in {"done", "failed"}
    ):
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="the target child already has active or inconsistent current work",
            is_retryable=False,
        )
    return target, previous_assignment


def _build_child_assignment(
    authority: NodeOperationAuthority,
    request: AssignChildRequest,
    target: FlowNodeModel,
    *,
    budget: AssignmentBudgetSnapshot,
) -> tuple[AssignmentModel, AttemptModel]:
    suffix = uuid4().hex
    assignment_id = f"assignment.{authority.task_id}.{target.node_key}.{suffix}"
    attempt_id = f"attempt.{authority.task_id}.{target.node_key}.{suffix}"
    assignment = AssignmentModel(
        assignment_id=assignment_id,
        task_id=authority.task_id,
        member_id=target.member_id,
        flow_id=authority.flow_id,
        assignment_key=f"{authority.task_id}.{target.node_key}.{suffix}",
        node_key=target.node_key,
        parent_assignment_id=authority.assignment_id,
        prompt=request.payload.assignment.prompt,
        current_attempt_id=attempt_id,
        work_plan_revision=0,
        child_assignment_limit=budget.child_assignment_limit,
        child_assignments_remaining=budget.child_assignments_remaining,
        retry_limit=budget.retry_limit,
        retries_remaining=budget.retries_remaining,
        created_by_dispatch_id=authority.dispatch_id,
    )
    attempt = AttemptModel(
        attempt_id=attempt_id,
        assignment_id=assignment_id,
        task_id=authority.task_id,
        flow_id=authority.flow_id,
        node_key=target.node_key,
        retry_of_attempt_id=None,
        latest_checkpoint_id=None,
        status="pending",
    )
    return assignment, attempt


async def _claim_child_node(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    target: FlowNodeModel,
    assignment_id: str,
    *,
    previous_assignment_id: str | None,
) -> None:
    current_assignment_predicate = (
        FlowNodeModel.current_assignment_id.is_(None)
        if previous_assignment_id is None
        else FlowNodeModel.current_assignment_id == previous_assignment_id
    )
    updated_node = await session.scalar(
        update(FlowNodeModel)
        .where(
            FlowNodeModel.flow_node_id == target.flow_node_id,
            current_assignment_predicate,
            FlowNodeModel.state == target.state,
            exact_node_operation_authority_exists(authority),
        )
        .values(current_assignment_id=assignment_id, state="waiting")
        .returning(FlowNodeModel.flow_node_id)
    )
    if updated_node is None:
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="another child assignment won the target node",
            is_retryable=False,
        )


async def _supersede_child_assignment(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    assignment: AssignmentModel,
) -> None:
    superseded = await session.scalar(
        update(AssignmentModel)
        .where(
            AssignmentModel.assignment_id == assignment.assignment_id,
            AssignmentModel.task_id == authority.task_id,
            AssignmentModel.flow_id == authority.flow_id,
            AssignmentModel.member_id == assignment.member_id,
            AssignmentModel.current_attempt_id == assignment.current_attempt_id,
            AssignmentModel.superseded_at.is_(None),
            exact_node_operation_authority_exists(authority),
        )
        .values(superseded_at=utc_now())
        .returning(AssignmentModel.assignment_id)
    )
    if superseded is None:
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="another transition changed the target child's prior assignment",
            is_retryable=False,
        )


def _stage_child_assignment_decision(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    assignment: AssignmentModel,
    attempt: AttemptModel,
) -> None:
    session.add(
        AssignmentDecisionModel(
            assignment_decision_id=f"assignment-decision.{authority.dispatch_id}",
            source_dispatch_id=authority.dispatch_id,
            task_id=authority.task_id,
            flow_id=authority.flow_id,
            assignment_id=authority.assignment_id,
            attempt_id=authority.attempt_id,
            source_flow_revision_id=authority.flow_revision_id,
            decision_kind="staged_child",
            staged_child_assignment_id=assignment.assignment_id,
            staged_child_attempt_id=attempt.attempt_id,
        )
    )


async def _require_no_staged_decision(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> None:
    existing = await session.scalar(
        select(AssignmentDecisionModel.assignment_decision_id).where(
            AssignmentDecisionModel.source_dispatch_id == authority.dispatch_id
        )
    )
    if existing is not None:
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICTING_CONTINUATION,
            summary="the current dispatch already owns a staged continuation decision",
            is_retryable=False,
        )


def _require_expected_revision(
    authority: NodeOperationAuthority,
    expected_revision: str,
) -> None:
    if expected_revision != authority.flow_revision_id:
        raise RuntimeOperationError(
            code=OperationFailureCode.STALE_FLOW_REVISION,
            summary="the structural revision changed before this operation",
            is_retryable=True,
        )


__all__ = ["execute_structural_node_operation"]
