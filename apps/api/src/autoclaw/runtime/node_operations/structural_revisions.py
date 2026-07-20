from __future__ import annotations

from dataclasses import replace

from pydantic import BaseModel, ValidationError
from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from autoclaw.persistence.models import (
    AssignmentDecisionModel,
    AssignmentModel,
    AttemptModel,
    DispatchTurnModel,
    FlowEdgeModel,
    FlowModel,
    FlowNodeModel,
    FlowRevisionModel,
    NodePlanRevisionModel,
)
from autoclaw.runtime.contracts import (
    AddChildSuccess,
    RemoveChildSuccess,
    TaskEventSource,
    TaskEventType,
    UpdateChildSuccess,
)
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.dispatch.authority import NodeOperationAuthority
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.ids import (
    flow_edge_id,
    flow_node_id,
    flow_revision_id,
    node_plan_revision_id,
)
from autoclaw.runtime.node_operations.contracts import NodeOperationName
from autoclaw.runtime.node_operations.follow_on import (
    CommittedNodeOperationFollowOn,
    CommittedNodeOperationResult,
)
from autoclaw.runtime.node_operations.result_reads import runtime_flow_read
from autoclaw.runtime.node_operations.structural_candidate.definitions import (
    validate_candidate_definition_references,
)
from autoclaw.runtime.node_operations.structural_candidate.models import (
    StructuralNodeCandidate,
    StructuralRevisionCandidate,
    criteria_history,
    load_structural_nodes,
)
from autoclaw.runtime.node_operations.structural_candidate.mutations import (
    mutate_structural_candidate,
    read_open_work_node_keys,
    validate_open_work_preserved,
)
from autoclaw.runtime.node_operations.structural_candidate.validation import (
    build_structural_revision_candidate,
)
from autoclaw.runtime.projection.signals import (
    CriteriaProjection,
    SupportProjectionSignal,
    WorkflowManifestProjection,
)
from autoclaw.runtime.task_events import append_task_event


async def adopt_structural_revision(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    operation_name: NodeOperationName,
    request: BaseModel,
) -> CommittedNodeOperationResult:
    _require_expected_revision(authority, request)
    await _require_no_decision(session, authority)
    source_revision, source_rows = await _load_source_revision(session, authority)
    candidate, target_node_key, cause = await _prepare_structural_candidate(
        session,
        authority,
        operation_name=operation_name,
        request=request,
        source_rows=source_rows,
    )
    next_revision_id = flow_revision_id(
        authority.flow_id,
        source_revision.revision_index + 1,
    )
    follow_on = CommittedNodeOperationFollowOn(
        projection_signals=_build_structural_projection_signals(
            authority=authority,
            next_revision_id=next_revision_id,
            candidate=candidate,
        ),
    )
    await _persist_structural_revision(
        session,
        authority,
        source_revision=source_revision,
        source_rows=source_rows,
        next_revision_id=next_revision_id,
        cause=cause,
        candidate=candidate,
    )
    await _append_structural_revision_event(
        session,
        authority,
        operation_name=operation_name,
        next_revision_id=next_revision_id,
        target_node_key=target_node_key,
        cause=cause,
    )
    await session.commit()
    response = await _success_result(
        session,
        authority,
        operation_name=operation_name,
        cause=cause,
        target_node_key=target_node_key,
        next_revision_id=next_revision_id,
    )
    return CommittedNodeOperationResult(response=response, follow_on=follow_on)


async def _prepare_structural_candidate(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    operation_name: NodeOperationName,
    request: BaseModel,
    source_rows: list[FlowNodeModel],
) -> tuple[StructuralRevisionCandidate, str, str]:
    try:
        loaded_nodes = load_structural_nodes(source_rows)
        previous_criteria = criteria_history(loaded_nodes)
        source_candidate = build_structural_revision_candidate(
            loaded_nodes,
            previous_criteria=previous_criteria,
        )
    except (ValueError, ValidationError) as exc:
        raise _candidate_failure(exc) from exc

    open_work = await read_open_work_node_keys(session, authority)
    working_nodes = source_candidate.nodes_by_key
    target_node_key, cause = await mutate_structural_candidate(
        session,
        authority,
        working_nodes,
        open_work,
        operation_name,
        request,
    )
    try:
        candidate = build_structural_revision_candidate(
            working_nodes,
            previous_criteria=previous_criteria,
        )
    except (ValueError, ValidationError) as exc:
        raise _candidate_failure(exc) from exc
    validate_open_work_preserved(source_candidate, candidate, open_work)
    await validate_candidate_definition_references(session, candidate)
    return candidate, target_node_key, cause


async def _persist_structural_revision(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    source_revision: FlowRevisionModel,
    source_rows: list[FlowNodeModel],
    next_revision_id: str,
    cause: str,
    candidate: StructuralRevisionCandidate,
) -> None:
    await _adopt_candidate_head(session, authority, next_revision_id=next_revision_id)
    await _stage_revision_rows(
        session,
        authority,
        source_revision=source_revision,
        next_revision_id=next_revision_id,
        cause=cause,
        candidate=candidate,
    )
    await _rebind_assignments(
        session,
        authority,
        source_rows=source_rows,
        next_revision_id=next_revision_id,
        candidate=candidate,
    )


async def _append_structural_revision_event(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    operation_name: NodeOperationName,
    next_revision_id: str,
    target_node_key: str,
    cause: str,
) -> None:
    await append_task_event(
        session,
        task_id=authority.task_id,
        event_type=TaskEventType.STRUCTURAL_REVISION_ADOPTED,
        event_source=TaskEventSource.NODE,
        flow_revision_id=next_revision_id,
        dispatch_id=authority.dispatch_id,
        attempt_id=authority.attempt_id,
        node_key=authority.node_key,
        payload={
            "source_flow_revision_id": authority.flow_revision_id,
            "adopted_flow_revision_id": next_revision_id,
            "operation": operation_name.value,
            "target_node_key": target_node_key,
            "cause": cause,
            "adopted_by_dispatch_id": authority.dispatch_id,
        },
    )


def _build_structural_projection_signals(
    *,
    authority: NodeOperationAuthority,
    next_revision_id: str,
    candidate: StructuralRevisionCandidate,
) -> tuple[SupportProjectionSignal, ...]:
    criteria_signals: dict[tuple[str, str, int], CriteriaProjection] = {}
    for node in candidate.nodes:
        for criterion in node.criteria:
            if criterion.version is None:
                raise _failure(
                    OperationFailureCode.ILLEGAL_STATE,
                    "adopted structural criteria generation has no version",
                )
            key = (criterion.owner_node_key, criterion.slot, criterion.version)
            criteria_signals[key] = CriteriaProjection(
                flow_revision_id=next_revision_id,
                owner_node_key=criterion.owner_node_key,
                slot=criterion.slot,
                version=criterion.version,
            )
    return (
        WorkflowManifestProjection(
            flow_id=authority.flow_id,
            active_flow_revision_id=next_revision_id,
        ),
        *criteria_signals.values(),
    )


def _require_expected_revision(
    authority: NodeOperationAuthority,
    request: BaseModel,
) -> None:
    expected_revision = getattr(request, "expected_structural_revision_id", None)
    if expected_revision != authority.flow_revision_id:
        raise _failure(
            OperationFailureCode.STALE_FLOW_REVISION,
            "the structural revision changed before this operation",
            retryable=True,
        )


async def _load_source_revision(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> tuple[FlowRevisionModel, list[FlowNodeModel]]:
    source_revision = await session.get(FlowRevisionModel, authority.flow_revision_id)
    if source_revision is None or source_revision.flow_id != authority.flow_id:
        raise _failure(OperationFailureCode.MISSING_RESOURCE, "active flow revision is missing")
    rows = list(
        await session.scalars(
            select(FlowNodeModel)
            .where(
                FlowNodeModel.flow_id == authority.flow_id,
                FlowNodeModel.flow_revision_id == authority.flow_revision_id,
            )
            .order_by(FlowNodeModel.order_index, FlowNodeModel.node_key)
        )
    )
    return source_revision, rows


async def _adopt_candidate_head(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    next_revision_id: str,
) -> None:
    adopted = await session.scalar(
        update(FlowModel)
        .where(
            FlowModel.flow_id == authority.flow_id,
            FlowModel.task_id == authority.task_id,
            FlowModel.status == "running",
            FlowModel.active_flow_revision_id == authority.flow_revision_id,
            FlowModel.current_dispatch_id == authority.dispatch_id,
            _exact_dispatch_exists(authority),
            _exact_assignment_exists(authority),
            _exact_flow_node_exists(authority),
        )
        .values(
            active_flow_revision_id=next_revision_id,
            control_revision=FlowModel.control_revision + 1,
        )
        .returning(FlowModel.flow_id)
    )
    if adopted is None:
        raise _failure(
            OperationFailureCode.CONFLICT,
            "another transition won exact structural revision adoption",
        )


def _exact_dispatch_exists(authority: NodeOperationAuthority) -> ColumnElement[bool]:
    return exists(
        select(DispatchTurnModel.dispatch_id).where(
            DispatchTurnModel.dispatch_id == authority.dispatch_id,
            DispatchTurnModel.task_id == authority.task_id,
            DispatchTurnModel.flow_id == authority.flow_id,
            DispatchTurnModel.assignment_id == authority.assignment_id,
            DispatchTurnModel.attempt_id == authority.attempt_id,
            DispatchTurnModel.node_key == authority.node_key,
            DispatchTurnModel.status.in_(("starting", "open")),
        )
    )


def _exact_assignment_exists(authority: NodeOperationAuthority) -> ColumnElement[bool]:
    return exists(
        select(AssignmentModel.assignment_id)
        .join(AttemptModel, AttemptModel.attempt_id == AssignmentModel.current_attempt_id)
        .where(
            AssignmentModel.assignment_id == authority.assignment_id,
            AssignmentModel.task_id == authority.task_id,
            AssignmentModel.flow_id == authority.flow_id,
            AssignmentModel.flow_revision_id == authority.flow_revision_id,
            AssignmentModel.node_key == authority.node_key,
            AssignmentModel.current_attempt_id == authority.attempt_id,
            AttemptModel.status.in_(("pending", "running")),
        )
    )


def _exact_flow_node_exists(authority: NodeOperationAuthority) -> ColumnElement[bool]:
    return exists(
        select(FlowNodeModel.flow_node_id).where(
            FlowNodeModel.flow_node_id == authority.flow_node.flow_node_id,
            FlowNodeModel.flow_id == authority.flow_id,
            FlowNodeModel.flow_revision_id == authority.flow_revision_id,
            FlowNodeModel.node_key == authority.node_key,
            FlowNodeModel.current_assignment_id == authority.assignment_id,
        )
    )


async def _stage_revision_rows(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    source_revision: FlowRevisionModel,
    next_revision_id: str,
    cause: str,
    candidate: StructuralRevisionCandidate,
) -> None:
    session.add(
        FlowRevisionModel(
            flow_revision_id=next_revision_id,
            flow_id=authority.flow_id,
            revision_index=source_revision.revision_index + 1,
            parent_flow_revision_id=authority.flow_revision_id,
            source_compiled_plan_id=source_revision.source_compiled_plan_id,
            cause=cause,
            created_by_dispatch_id=authority.dispatch_id,
            snapshot_json=candidate.snapshot_json(),
        )
    )
    for node in candidate.nodes:
        _stage_node(session, authority.flow_id, next_revision_id, node)
    await session.flush()
    for edge in candidate.dependency_edges:
        session.add(
            FlowEdgeModel(
                flow_edge_id=flow_edge_id(
                    next_revision_id,
                    edge.consumer_node_key,
                    edge.kind.value,
                    edge.slot,
                ),
                flow_revision_id=next_revision_id,
                provider_node_key=edge.provider_node_key,
                consumer_node_key=edge.consumer_node_key,
                kind=edge.kind.value,
                slot=edge.slot,
                description=edge.description,
                order_index=edge.order_index,
            )
        )


def _stage_node(
    session: AsyncSession,
    flow_id: str,
    next_revision_id: str,
    node: StructuralNodeCandidate,
) -> None:
    next_node_id = flow_node_id(next_revision_id, node.node_key)
    session.add(
        FlowNodeModel(
            flow_node_id=next_node_id,
            flow_id=flow_id,
            flow_revision_id=next_revision_id,
            node_key=node.node_key,
            parent_node_key=node.parent_node_key,
            structural_kind=node.structural_kind.value,
            role_key=node.role_key,
            role_revision_no=node.role_revision_no,
            role_description=node.role_description,
            role_instruction=node.role_instruction,
            policy_key=node.policy_key,
            policy_revision_no=node.policy_revision_no,
            policy_description=node.policy_description,
            policy_instruction=node.policy_instruction,
            provider_kind=node.provider.kind.value if node.provider is not None else None,
            description=node.description,
            node_instruction=node.node_instruction,
            child_node_keys_json=list(node.child_node_keys),
            consumes_json=node.consumes_json(),
            produces_json=node.produces_json(),
            criteria_json=[criterion.as_json() for criterion in node.criteria],
            child_defaults_json=node.child_defaults_json(),
            state=node.state,
            current_assignment_id=node.current_assignment_id,
            order_index=node.order_index,
        )
    )
    session.add(
        NodePlanRevisionModel(
            node_plan_revision_id=node_plan_revision_id(next_revision_id, node.node_key),
            flow_id=flow_id,
            flow_revision_id=next_revision_id,
            flow_node_id=next_node_id,
            role_key=node.role_key,
            role_revision_no=node.role_revision_no,
            role_description=node.role_description,
            role_instruction=node.role_instruction,
            policy_key=node.policy_key,
            policy_revision_no=node.policy_revision_no,
            policy_description=node.policy_description,
            policy_instruction=node.policy_instruction,
            provider_kind=node.provider.kind.value if node.provider is not None else None,
        )
    )


async def _rebind_assignments(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    source_rows: list[FlowNodeModel],
    next_revision_id: str,
    candidate: StructuralRevisionCandidate,
) -> None:
    for source_node in source_rows:
        source_node.current_assignment_id = None
    for node in candidate.nodes:
        if node.current_assignment_id is None:
            continue
        await session.execute(
            update(AssignmentModel)
            .where(
                AssignmentModel.assignment_id == node.current_assignment_id,
                AssignmentModel.task_id == authority.task_id,
                AssignmentModel.flow_id == authority.flow_id,
                AssignmentModel.flow_revision_id == authority.flow_revision_id,
                AssignmentModel.node_key == node.node_key,
            )
            .values(
                flow_revision_id=next_revision_id,
                flow_node_id=flow_node_id(next_revision_id, node.node_key),
            )
        )


async def _require_no_decision(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> None:
    existing = await session.scalar(
        select(AssignmentDecisionModel.assignment_decision_id).where(
            AssignmentDecisionModel.source_dispatch_id == authority.dispatch_id
        )
    )
    if existing is not None:
        raise _failure(
            OperationFailureCode.CONFLICTING_CONTINUATION,
            "structural edits are illegal after staging a continuation decision",
        )


async def _success_result(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    operation_name: NodeOperationName,
    cause: str,
    target_node_key: str,
    next_revision_id: str,
) -> BaseModel:
    flow = await runtime_flow_read(
        session,
        replace(authority, flow_revision_id=next_revision_id),
    )
    result_kwargs = {
        "summary": f"Adopted {cause} as structural revision {next_revision_id}.",
        "target_node_key": target_node_key,
        "flow": flow,
        "workflow_manifest_ref": flow.workflow_manifest_ref,
    }
    if operation_name == NodeOperationName.ADD_CHILD:
        return AddChildSuccess(**result_kwargs)
    if operation_name == NodeOperationName.UPDATE_CHILD:
        return UpdateChildSuccess(**result_kwargs)
    return RemoveChildSuccess(**result_kwargs)


def _candidate_failure(exc: Exception) -> RuntimeOperationError:
    return _failure(OperationFailureCode.ILLEGAL_STATE, str(exc))


def _failure(
    code: OperationFailureCode,
    summary: str,
    *,
    retryable: bool = False,
) -> RuntimeOperationError:
    return RuntimeOperationError(code=code, summary=summary, is_retryable=retryable)


__all__ = ["adopt_structural_revision"]
