from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentDecisionModel,
    AttemptCheckpointModel,
    CommandRunModel,
    FlowModel,
    FlowNodeModel,
    HumanRequestModel,
)
from banksia.runtime.contracts.member import NodeKind
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.errors import RuntimeOperationError, illegal_state_error
from banksia.runtime.node_operations.catalog import (
    list_node_operation_descriptors_for_kind,
)
from banksia.runtime.node_operations.contracts import NodeOperationName

_READ_OPERATIONS = frozenset(
    {
        NodeOperationName.GET_CURRENT_CONTEXT,
    }
)
_REPLAN_OPERATIONS = frozenset(
    {
        NodeOperationName.ADD_CHILD,
        NodeOperationName.UPDATE_CHILD,
        NodeOperationName.REMOVE_CHILD,
    }
)
_STRUCTURAL_OPERATIONS = _REPLAN_OPERATIONS | {NodeOperationName.ASSIGN_CHILD}
_TRANSITION_OPERATIONS = _STRUCTURAL_OPERATIONS | {
    NodeOperationName.CHECKPOINT,
    NodeOperationName.RETURN_BOUNDARY,
    NodeOperationName.OPEN_HUMAN_REQUEST,
    NodeOperationName.START_COMMAND_RUN,
}


@dataclass(frozen=True, slots=True)
class NodeOperationStateToken:
    flow_control_revision: int
    flow_revision_id: str
    assignment_decision_id: str | None
    checkpoint_count: int
    latest_checkpoint_id: str | None


def node_operation_requires_transition_claim(
    operation_name: NodeOperationName,
) -> bool:
    return operation_name in _TRANSITION_OPERATIONS


async def read_node_operation_state_token(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> NodeOperationStateToken:
    flow_state = (
        await session.execute(
            select(
                FlowModel.control_revision,
                FlowModel.active_flow_revision_id,
            ).where(
                FlowModel.flow_id == authority.flow_id,
                FlowModel.task_id == authority.task_id,
            )
        )
    ).one_or_none()
    if flow_state is None or flow_state.active_flow_revision_id is None:
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="another transition changed current Flow authority",
            is_retryable=False,
        )
    decision_id = await session.scalar(
        select(AssignmentDecisionModel.assignment_decision_id).where(
            AssignmentDecisionModel.source_dispatch_id == authority.dispatch_id
        )
    )
    checkpoint_scope = (
        AttemptCheckpointModel.task_id == authority.task_id,
        AttemptCheckpointModel.flow_id == authority.flow_id,
        AttemptCheckpointModel.assignment_id == authority.assignment_id,
        AttemptCheckpointModel.attempt_id == authority.attempt_id,
        AttemptCheckpointModel.authoring_dispatch_id == authority.dispatch_id,
    )
    checkpoint_count = await session.scalar(
        select(func.count()).select_from(AttemptCheckpointModel).where(*checkpoint_scope)
    )
    latest_checkpoint_id = await session.scalar(
        select(AttemptCheckpointModel.checkpoint_id).where(
            *checkpoint_scope,
            AttemptCheckpointModel.checkpoint_id == authority.attempt.latest_checkpoint_id,
        )
    )
    return NodeOperationStateToken(
        flow_control_revision=int(flow_state.control_revision),
        flow_revision_id=str(flow_state.active_flow_revision_id),
        assignment_decision_id=decision_id,
        checkpoint_count=int(checkpoint_count or 0),
        latest_checkpoint_id=latest_checkpoint_id,
    )


async def read_state_legal_node_operations(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> frozenset[NodeOperationName]:
    return await _read_state_legal_node_operations(session, authority)


async def require_state_legal_node_operation(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    operation_name: NodeOperationName,
) -> None:
    if operation_name in _READ_OPERATIONS:
        return
    legal_operations = await _read_state_legal_node_operations(
        session,
        authority,
        candidates=frozenset((operation_name,)),
    )
    if operation_name not in legal_operations:
        raise illegal_state_error(
            f"{operation_name.value} is not legal in the current source state"
        )


async def _read_state_legal_node_operations(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    candidates: frozenset[NodeOperationName] | None = None,
) -> frozenset[NodeOperationName]:
    operations = {
        descriptor.name
        for descriptor in list_node_operation_descriptors_for_kind(authority.node_kind)
    }
    if candidates is not None:
        operations.intersection_update(candidates)
    if not operations:
        return frozenset()
    if await _dispatch_already_owns_source(session, authority):
        return frozenset(operations & _READ_OPERATIONS)

    decision = await session.scalar(
        select(AssignmentDecisionModel).where(
            AssignmentDecisionModel.source_dispatch_id == authority.dispatch_id
        )
    )
    legal = set(operations)
    legal.discard(NodeOperationName.RETURN_BOUNDARY)
    if decision is not None:
        legal.difference_update(_STRUCTURAL_OPERATIONS)
        legal.discard(NodeOperationName.OPEN_HUMAN_REQUEST)
        legal.discard(NodeOperationName.START_COMMAND_RUN)
        if decision.decision_kind == "staged_child":
            legal.add(NodeOperationName.RETURN_BOUNDARY)
        return frozenset(legal)

    await _narrow_structural_operations(session, authority, legal=legal)
    return frozenset(legal)


async def _narrow_structural_operations(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    legal: set[NodeOperationName],
) -> None:
    if not legal & _STRUCTURAL_OPERATIONS or authority.node_kind == NodeKind.WORKER:
        return
    descendants = tuple(
        await session.scalars(
            select(FlowNodeModel).where(
                FlowNodeModel.flow_id == authority.flow_id,
                FlowNodeModel.flow_revision_id == authority.flow_revision_id,
                FlowNodeModel.node_key != authority.node_key,
            )
        )
    )
    direct_children = tuple(
        node for node in descendants if node.parent_node_key == authority.node_key
    )
    if not direct_children:
        legal.discard(NodeOperationName.UPDATE_CHILD)
        legal.discard(NodeOperationName.REMOVE_CHILD)
    if NodeOperationName.ASSIGN_CHILD in legal and not any(
        (child.current_assignment_id is None and child.state == "ready")
        or (child.current_assignment_id is not None and child.state in {"done", "failed"})
        for child in direct_children
    ):
        legal.discard(NodeOperationName.ASSIGN_CHILD)


async def _dispatch_already_owns_source(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> bool:
    for model in (AcceptedBoundaryModel, HumanRequestModel, CommandRunModel):
        source_id = await session.scalar(
            select(model.source_dispatch_id)
            .where(model.source_dispatch_id == authority.dispatch_id)
            .limit(1)
        )
        if source_id is not None:
            return True
    return False


__all__ = [
    "NodeOperationStateToken",
    "node_operation_requires_transition_claim",
    "read_node_operation_state_token",
    "read_state_legal_node_operations",
    "require_state_legal_node_operation",
]
