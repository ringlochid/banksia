from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentModel,
    AttemptCheckpointModel,
    CommandRunModel,
    DelegationWaveModel,
    HumanRequestModel,
    TaskModel,
    TeamRevisionMemberModel,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.errors import RuntimeOperationError, illegal_state_error
from banksia.runtime.node_operations.catalog import (
    NodeOperationSelection,
    select_node_operation_descriptors,
)
from banksia.runtime.node_operations.contracts import (
    NodeOperationDescriptor,
    NodeOperationName,
)

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
_STRUCTURAL_OPERATIONS = _REPLAN_OPERATIONS | {NodeOperationName.DELEGATE}
_TRANSITION_OPERATIONS = _STRUCTURAL_OPERATIONS | {
    NodeOperationName.CHECKPOINT,
    NodeOperationName.OPEN_HUMAN_REQUEST,
    NodeOperationName.START_COMMAND_RUN,
}


@dataclass(frozen=True, slots=True)
class NodeOperationStateToken:
    task_control_revision: int
    team_revision_id: str
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
    task_state = (
        await session.execute(
            select(
                TaskModel.control_revision,
                TaskModel.current_team_revision_id,
            ).where(
                TaskModel.task_id == authority.task_id,
            )
        )
    ).one_or_none()
    if task_state is None or task_state.current_team_revision_id is None:
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="another transition changed current Task authority",
            is_retryable=False,
        )
    checkpoint_scope = (
        AttemptCheckpointModel.task_id == authority.task_id,
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
        task_control_revision=int(task_state.control_revision),
        team_revision_id=str(task_state.current_team_revision_id),
        checkpoint_count=int(checkpoint_count or 0),
        latest_checkpoint_id=latest_checkpoint_id,
    )


async def read_state_legal_node_operations(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> frozenset[NodeOperationName]:
    return await _read_state_legal_node_operations(session, authority)


async def read_available_node_operation_descriptors(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> tuple[NodeOperationDescriptor, ...]:
    """Return one ordered catalog selection for the exact current Dispatch."""

    legal_operations = await _read_state_legal_node_operations(session, authority)
    capabilities = authority.capabilities
    return select_node_operation_descriptors(
        NodeOperationSelection(
            has_direct_team=authority.has_direct_team,
            is_human_request_allowed=any(
                getattr(capabilities, field_name) == "allow"
                for field_name in (
                    "human_direction",
                    "human_approval",
                    "human_input",
                    "human_review",
                )
            ),
            is_command_run_allowed=capabilities.command_run == "allow",
            legal_operations=legal_operations,
        )
    )


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
        for descriptor in select_node_operation_descriptors(
            NodeOperationSelection(
                has_direct_team=authority.has_direct_team,
                is_human_request_allowed=True,
                is_command_run_allowed=True,
            )
        )
    }
    if candidates is not None:
        operations.intersection_update(candidates)
    if not operations:
        return frozenset()
    if await _dispatch_already_owns_source(session, authority):
        return frozenset(operations & _READ_OPERATIONS)

    legal = set(operations)
    await _narrow_structural_operations(session, authority, legal=legal)
    return frozenset(legal)


async def _narrow_structural_operations(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    legal: set[NodeOperationName],
) -> None:
    if not legal & _STRUCTURAL_OPERATIONS or not authority.has_direct_team:
        return
    direct_team_members = tuple(
        await session.scalars(
            select(TeamRevisionMemberModel).where(
                TeamRevisionMemberModel.task_id == authority.task_id,
                TeamRevisionMemberModel.team_revision_id == authority.current_team_revision_id,
                TeamRevisionMemberModel.parent_member_id == authority.member_id,
            )
        )
    )
    if not direct_team_members:
        legal.discard(NodeOperationName.UPDATE_CHILD)
        legal.discard(NodeOperationName.REMOVE_CHILD)
    if NodeOperationName.DELEGATE in legal:
        has_available_child = False
        for child in direct_team_members:
            is_busy = await session.scalar(
                select(
                    exists().where(
                        AssignmentModel.task_id == authority.task_id,
                        AssignmentModel.member_id == child.member_id,
                        AssignmentModel.terminal_outcome.is_(None),
                    )
                )
            )
            if not is_busy:
                has_available_child = True
                break
        if not has_available_child:
            legal.discard(NodeOperationName.DELEGATE)


async def _dispatch_already_owns_source(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> bool:
    for model in (
        AcceptedBoundaryModel,
        DelegationWaveModel,
        HumanRequestModel,
        CommandRunModel,
    ):
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
    "read_available_node_operation_descriptors",
    "read_node_operation_state_token",
    "read_state_legal_node_operations",
    "require_state_legal_node_operation",
]
