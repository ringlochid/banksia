from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.definitions.contracts.workflow import NodeKind
from autoclaw.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentDecisionModel,
    AttemptCheckpointModel,
    CommandRunModel,
    FlowModel,
    FlowNodeModel,
    HumanRequestModel,
)
from autoclaw.runtime.checkpoint import read_exact_latest_checkpoint
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.dispatch.authority import NodeOperationAuthority
from autoclaw.runtime.errors import RuntimeOperationError, illegal_state_error
from autoclaw.runtime.node_operations.catalog import (
    list_node_operation_descriptors_for_kind,
)
from autoclaw.runtime.node_operations.contracts import NodeOperationName
from autoclaw.runtime.node_operations.release import (
    release_blocked_is_ready,
    release_green_is_ready,
)

_READ_OPERATIONS = frozenset(
    {
        NodeOperationName.GET_CURRENT_CONTEXT,
        NodeOperationName.LIST_FILES,
        NodeOperationName.READ_FILE,
        NodeOperationName.SEARCH_DEFINITIONS,
        NodeOperationName.GET_DEFINITION,
    }
)
_STRUCTURAL_OPERATIONS = frozenset(
    {
        NodeOperationName.ASSIGN_CHILD,
        NodeOperationName.ADD_CHILD,
        NodeOperationName.UPDATE_CHILD,
        NodeOperationName.REMOVE_CHILD,
        NodeOperationName.RELEASE_GREEN,
        NodeOperationName.RELEASE_BLOCKED,
    }
)
_DECISION_SENSITIVE_OPERATIONS = _STRUCTURAL_OPERATIONS | {
    NodeOperationName.RETURN_BOUNDARY,
    NodeOperationName.OPEN_HUMAN_REQUEST,
    NodeOperationName.START_COMMAND_RUN,
}
_CHECKPOINT_SENSITIVE_OPERATIONS = _STRUCTURAL_OPERATIONS | {
    NodeOperationName.RECORD_CHECKPOINT,
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
    terminal_checkpoint_id: str | None


def node_operation_requires_transition_claim(
    operation_name: NodeOperationName,
) -> bool:
    return operation_name in _CHECKPOINT_SENSITIVE_OPERATIONS


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
            summary="another transition changed current flow authority",
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
    terminal_checkpoint_id = await session.scalar(
        select(AttemptCheckpointModel.checkpoint_id).where(
            *checkpoint_scope,
            AttemptCheckpointModel.checkpoint_kind == "terminal",
        )
    )
    return NodeOperationStateToken(
        flow_control_revision=int(flow_state.control_revision),
        flow_revision_id=str(flow_state.active_flow_revision_id),
        assignment_decision_id=decision_id,
        checkpoint_count=int(checkpoint_count or 0),
        terminal_checkpoint_id=terminal_checkpoint_id,
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
    role_operations = {
        descriptor.name
        for descriptor in list_node_operation_descriptors_for_kind(authority.node_kind)
    }
    if candidates is not None:
        role_operations.intersection_update(candidates)
    if not role_operations:
        return frozenset()
    if await _dispatch_already_owns_source(session, authority):
        return frozenset(role_operations & _READ_OPERATIONS)

    if role_operations <= _READ_OPERATIONS | {NodeOperationName.SET_WORK_PLAN}:
        return frozenset(role_operations)

    decision = (
        await session.scalar(
            select(AssignmentDecisionModel).where(
                AssignmentDecisionModel.source_dispatch_id == authority.dispatch_id
            )
        )
        if role_operations & _DECISION_SENSITIVE_OPERATIONS
        else None
    )
    checkpoint = (
        await _latest_dispatch_checkpoint(session, authority)
        if role_operations & _CHECKPOINT_SENSITIVE_OPERATIONS
        else None
    )
    terminal_checkpoint = checkpoint is not None and checkpoint.checkpoint_kind == "terminal"

    legal = set(role_operations)
    legal.discard(NodeOperationName.RETURN_BOUNDARY)
    if terminal_checkpoint:
        legal.discard(NodeOperationName.RECORD_CHECKPOINT)
        legal.discard(NodeOperationName.OPEN_HUMAN_REQUEST)
        legal.discard(NodeOperationName.START_COMMAND_RUN)

    if decision is not None:
        legal.difference_update(_STRUCTURAL_OPERATIONS)
        legal.discard(NodeOperationName.OPEN_HUMAN_REQUEST)
        legal.discard(NodeOperationName.START_COMMAND_RUN)
    else:
        await _narrow_uncommitted_structural_operations(
            session,
            authority,
            legal=legal,
            terminal_checkpoint=terminal_checkpoint,
        )

    if NodeOperationName.RETURN_BOUNDARY in role_operations and _boundary_is_ready(
        authority, checkpoint, decision
    ):
        legal.add(NodeOperationName.RETURN_BOUNDARY)
    return frozenset(legal)


async def _narrow_uncommitted_structural_operations(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    legal: set[NodeOperationName],
    terminal_checkpoint: bool,
) -> None:
    structural_operations = legal & _STRUCTURAL_OPERATIONS
    if authority.node_kind == NodeKind.WORKER or not structural_operations:
        return
    descendants: tuple[FlowNodeModel, ...] = ()
    if structural_operations & {
        NodeOperationName.ASSIGN_CHILD,
        NodeOperationName.UPDATE_CHILD,
        NodeOperationName.REMOVE_CHILD,
    }:
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
    if NodeOperationName.ASSIGN_CHILD in structural_operations and not any(
        child.current_assignment_id is None for child in direct_children
    ):
        legal.discard(NodeOperationName.ASSIGN_CHILD)
    if not descendants and structural_operations & {
        NodeOperationName.UPDATE_CHILD,
        NodeOperationName.REMOVE_CHILD,
    }:
        legal.discard(NodeOperationName.UPDATE_CHILD)
        legal.discard(NodeOperationName.REMOVE_CHILD)
    if terminal_checkpoint:
        legal.discard(NodeOperationName.ASSIGN_CHILD)
        legal.discard(NodeOperationName.ADD_CHILD)
        legal.discard(NodeOperationName.UPDATE_CHILD)
        legal.discard(NodeOperationName.REMOVE_CHILD)
    if (
        NodeOperationName.RELEASE_GREEN in structural_operations
        and not await release_green_is_ready(session, authority)
    ):
        legal.discard(NodeOperationName.RELEASE_GREEN)
    if NodeOperationName.RELEASE_BLOCKED in structural_operations and (
        authority.node_kind != NodeKind.ROOT
        or not await release_blocked_is_ready(session, authority)
    ):
        legal.discard(NodeOperationName.RELEASE_BLOCKED)


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


async def _latest_dispatch_checkpoint(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> AttemptCheckpointModel | None:
    return await read_exact_latest_checkpoint(session, authority)


def _boundary_is_ready(
    authority: NodeOperationAuthority,
    checkpoint: AttemptCheckpointModel | None,
    decision: AssignmentDecisionModel | None,
) -> bool:
    if decision is not None and decision.decision_kind == "staged_child":
        return True
    if checkpoint is None or checkpoint.checkpoint_kind != "terminal":
        return False
    if authority.node_kind == NodeKind.WORKER:
        return checkpoint.outcome in {"green", "retry", "blocked"}
    if authority.node_kind == NodeKind.PARENT:
        return checkpoint.outcome == "blocked" or (
            checkpoint.outcome == "green"
            and decision is not None
            and decision.decision_kind == "release_green"
        )
    return decision is not None and (
        (checkpoint.outcome == "green" and decision.decision_kind == "release_green")
        or (checkpoint.outcome == "blocked" and decision.decision_kind == "release_blocked")
    )


__all__ = [
    "NodeOperationStateToken",
    "node_operation_requires_transition_claim",
    "read_node_operation_state_token",
    "read_state_legal_node_operations",
    "require_state_legal_node_operation",
]
