from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy import case, insert, literal, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.persistence.models import (
    AssignmentDecisionModel,
    AssignmentModel,
    AttemptCheckpointModel,
    AttemptModel,
    FlowEdgeModel,
    FlowNodeModel,
)
from autoclaw.runtime.assignment import (
    AssignmentBudgetSnapshot,
    AssignmentDurableInputs,
    resolve_child_assignment_durable_inputs,
    snapshot_assignment_budget,
)
from autoclaw.runtime.clock import utc_now
from autoclaw.runtime.contracts import (
    AssignChildSuccess,
    ReleaseBlockedSuccess,
    ReleaseGreenSuccess,
    TaskEventSource,
    TaskEventType,
)
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.dispatch.authority import (
    NodeOperationAuthority,
    exact_node_operation_authority_exists,
)
from autoclaw.runtime.errors import RuntimeOperationError, budget_exhausted_error
from autoclaw.runtime.launch.bootstrap.criteria import stage_assignment_criteria_refs
from autoclaw.runtime.node_operations.contracts import (
    AssignChildRequest,
    NodeOperationName,
    ReleaseRequest,
)
from autoclaw.runtime.node_operations.follow_on import (
    CommittedNodeOperationFollowOn,
    CommittedNodeOperationResult,
)
from autoclaw.runtime.node_operations.release import (
    add_release_basis_rows,
    require_release_blocked_basis,
    require_release_green_basis,
)
from autoclaw.runtime.node_operations.result_reads import runtime_flow_read
from autoclaw.runtime.node_operations.structural_candidate.definitions import (
    resolve_pinned_policy_definition,
)
from autoclaw.runtime.projection.signals import AttemptAssignmentProjection
from autoclaw.runtime.task_events import append_task_event


async def execute_structural_node_operation(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    operation_name: NodeOperationName,
    request: BaseModel,
) -> BaseModel:
    if operation_name == NodeOperationName.ASSIGN_CHILD:
        assert isinstance(request, AssignChildRequest)
        return await _assign_child(session, authority, request)
    if operation_name in {
        NodeOperationName.ADD_CHILD,
        NodeOperationName.UPDATE_CHILD,
        NodeOperationName.REMOVE_CHILD,
    }:
        from autoclaw.runtime.node_operations.structural_revisions import (
            adopt_structural_revision,
        )

        return await adopt_structural_revision(
            session,
            authority,
            operation_name,
            request,
        )
    if operation_name == NodeOperationName.RELEASE_GREEN:
        assert isinstance(request, ReleaseRequest)
        return await _record_release(session, authority, request, blocked=False)
    if operation_name == NodeOperationName.RELEASE_BLOCKED:
        assert isinstance(request, ReleaseRequest)
        return await _record_release(session, authority, request, blocked=True)
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
    pinned_policy = await resolve_pinned_policy_definition(
        session,
        policy_key=target.policy_key,
        policy_revision_no=target.policy_revision_no,
    )
    budget = snapshot_assignment_budget(pinned_policy)
    durable_inputs = await resolve_child_assignment_durable_inputs(
        session,
        task_id=authority.task_id,
        flow_id=authority.flow_id,
        flow_revision_id=authority.flow_revision_id,
        target=target,
    )
    assignment, attempt = _build_child_assignment(
        authority,
        request,
        target,
        budget=budget,
        durable_inputs=durable_inputs,
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

    session.add_all((assignment, attempt))
    stage_assignment_criteria_refs(session, assignment)
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
            "child_node_key": target.node_key,
            "flow_revision_id": authority.flow_revision_id,
        },
    )
    await session.commit()

    flow = await runtime_flow_read(session, authority)
    response = AssignChildSuccess(
        summary="Child assignment staged for a later yield boundary.",
        target_node_key=target.node_key,
        target_assignment_key=assignment.assignment_key,
        target_attempt_id=attempt.attempt_id,
        flow=flow,
        workflow_manifest_ref=flow.workflow_manifest_ref,
    )
    return CommittedNodeOperationResult(
        response=response,
        follow_on=CommittedNodeOperationFollowOn(
            projection_signals=(
                AttemptAssignmentProjection(
                    assignment_id=assignment.assignment_id,
                    attempt_id=attempt.attempt_id,
                    flow_revision_id=authority.flow_revision_id,
                ),
            ),
        ),
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
            AssignmentModel.flow_revision_id == authority.flow_revision_id,
            AssignmentModel.current_attempt_id == authority.attempt_id,
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
        and historical_parent.flow_revision_id == authority.flow_revision_id
        and historical_parent.flow_node_id == authority.assignment.flow_node_id
        and historical_parent.node_key == authority.node_key
        and historical_parent.superseded_at is not None
    )
    if (
        previous_assignment is None
        or previous_assignment.task_id != authority.task_id
        or previous_assignment.flow_id != authority.flow_id
        or previous_assignment.flow_revision_id != authority.flow_revision_id
        or previous_assignment.flow_node_id != target.flow_node_id
        or previous_assignment.node_key != target.node_key
        or not historical_parent_is_same_node
        or previous_assignment.superseded_at is not None
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
        or previous_checkpoint.checkpoint_kind != "terminal"
        or previous_checkpoint.outcome != previous_attempt.terminal_outcome
        or target.state not in {"done", "failed"}
    ):
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="the target child already has active or inconsistent current work",
            is_retryable=False,
        )
    await _require_no_assigned_artifact_consumer(session, authority, target)
    return target, previous_assignment


async def _require_no_assigned_artifact_consumer(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    target: FlowNodeModel,
) -> None:
    assigned_consumer = await session.scalar(
        select(FlowNodeModel.node_key)
        .join(
            FlowEdgeModel,
            (FlowEdgeModel.flow_revision_id == FlowNodeModel.flow_revision_id)
            & (FlowEdgeModel.consumer_node_key == FlowNodeModel.node_key),
        )
        .where(
            FlowEdgeModel.flow_revision_id == authority.flow_revision_id,
            FlowEdgeModel.provider_node_key == target.node_key,
            FlowEdgeModel.kind == "artifact",
            FlowNodeModel.current_assignment_id.is_not(None),
        )
        .limit(1)
    )
    if assigned_consumer is not None:
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary=(
                f"cannot replace '{target.node_key}' while downstream artifact consumer "
                f"'{assigned_consumer}' has current work"
            ),
            is_retryable=False,
        )


def _build_child_assignment(
    authority: NodeOperationAuthority,
    request: AssignChildRequest,
    target: FlowNodeModel,
    *,
    budget: AssignmentBudgetSnapshot,
    durable_inputs: AssignmentDurableInputs,
) -> tuple[AssignmentModel, AttemptModel]:
    suffix = uuid4().hex
    assignment_id = f"assignment.{authority.task_id}.{target.node_key}.{suffix}"
    attempt_id = f"attempt.{authority.task_id}.{target.node_key}.{suffix}"
    assignment = AssignmentModel(
        assignment_id=assignment_id,
        task_id=authority.task_id,
        flow_id=authority.flow_id,
        flow_revision_id=authority.flow_revision_id,
        flow_node_id=target.flow_node_id,
        assignment_key=f"{authority.task_id}.{target.node_key}.{suffix}",
        node_key=target.node_key,
        parent_assignment_id=authority.assignment_id,
        summary=request.payload.assignment_intent.summary,
        instruction=request.payload.assignment_intent.instruction,
        criteria_json=list(durable_inputs.criteria),
        consumes_json=list(durable_inputs.consumes),
        produces_json=_flatten_slots(target.produces_json),
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
            AssignmentModel.flow_revision_id == authority.flow_revision_id,
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


async def _record_release(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    request: ReleaseRequest,
    *,
    blocked: bool,
) -> ReleaseGreenSuccess | ReleaseBlockedSuccess:
    _require_expected_revision(authority, request.expected_structural_revision_id)
    await _require_no_staged_decision(session, authority)
    decision_kind = "release_blocked" if blocked else "release_green"
    basis = (
        await require_release_blocked_basis(session, authority)
        if blocked
        else await require_release_green_basis(session, authority)
    )
    decision_id = f"assignment-decision.{authority.dispatch_id}"
    await _insert_release_decision_if_current(
        session,
        authority,
        assignment_decision_id=decision_id,
        decision_kind=decision_kind,
    )
    add_release_basis_rows(
        session,
        authority=authority,
        assignment_decision_id=decision_id,
        basis=basis,
    )
    await session.commit()
    flow = await runtime_flow_read(session, authority)
    result_type = ReleaseBlockedSuccess if blocked else ReleaseGreenSuccess
    return result_type(
        summary=f"Recorded {decision_kind} readiness for the current assignment.",
        target_node_key=authority.node_key,
        flow=flow,
        workflow_manifest_ref=flow.workflow_manifest_ref,
    )


async def _insert_release_decision_if_current(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    assignment_decision_id: str,
    decision_kind: str,
) -> None:
    table = AssignmentDecisionModel.__table__
    inserted_id = await session.scalar(
        insert(AssignmentDecisionModel)
        .from_select(
            (
                "assignment_decision_id",
                "source_dispatch_id",
                "task_id",
                "flow_id",
                "assignment_id",
                "attempt_id",
                "source_flow_revision_id",
                "decision_kind",
                "staged_child_assignment_id",
                "staged_child_attempt_id",
                "recorded_at",
            ),
            select(
                literal(assignment_decision_id),
                literal(authority.dispatch_id),
                literal(authority.task_id),
                literal(authority.flow_id),
                literal(authority.assignment_id),
                literal(authority.attempt_id),
                literal(authority.flow_revision_id),
                literal(decision_kind),
                literal(None, type_=table.c.staged_child_assignment_id.type),
                literal(None, type_=table.c.staged_child_attempt_id.type),
                literal(utc_now(), type_=table.c.recorded_at.type),
            ).where(exact_node_operation_authority_exists(authority)),
        )
        .returning(table.c.assignment_decision_id)
    )
    if inserted_id is None:
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="another transition changed current release authority",
            is_retryable=False,
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


def _flatten_slots(value: dict[str, object] | None) -> list[dict[str, object]]:
    if value is None:
        return []
    flattened: list[dict[str, object]] = []
    for kind, entries in value.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict):
                flattened.append({"kind": kind.removesuffix("s"), **entry})
    return flattened


__all__ = ["execute_structural_node_operation"]
