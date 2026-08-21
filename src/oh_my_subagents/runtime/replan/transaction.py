from __future__ import annotations

from typing import cast

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.runtime.contracts import (
    AddChildRequest,
    RemoveChildRequest,
    ReplanOperation,
    UpdateChildRequest,
)
from oh_my_subagents.runtime.dispatch.authority import NodeOperationAuthority
from oh_my_subagents.runtime.dispatch.preparation import DispatchOpeningDependencies
from oh_my_subagents.runtime.node_operations.contracts import NodeOperationName
from oh_my_subagents.runtime.node_operations.follow_on import (
    CommittedNodeOperationFollowOn,
    CommittedNodeOperationResult,
)
from oh_my_subagents.runtime.post_commit import DispatchCleanupRequested, ReplanCommitted
from oh_my_subagents.runtime.replan.persistence import commit_replan_rows
from oh_my_subagents.runtime.replan.planning import ReplanRequest

_REPLAN_OPERATIONS = {
    NodeOperationName.ADD_CHILD,
    NodeOperationName.UPDATE_CHILD,
    NodeOperationName.REMOVE_CHILD,
}


async def commit_replan(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    operation_name: NodeOperationName,
    request: BaseModel,
    *,
    dependencies: DispatchOpeningDependencies,
) -> CommittedNodeOperationResult:
    """Commit one recursive subtree mutation and schedule its durable continuation."""

    if operation_name not in _REPLAN_OPERATIONS:
        raise ValueError(f"{operation_name.value} is not a replan operation")
    if not isinstance(request, (AddChildRequest, UpdateChildRequest, RemoveChildRequest)):
        raise TypeError(f"invalid {operation_name.value} request type")
    commit = await commit_replan_rows(
        session,
        authority,
        cast(ReplanOperation, operation_name.value),
        _replan_request(request),
        dependencies=dependencies,
    )
    return CommittedNodeOperationResult(
        response=commit.result,
        follow_on=CommittedNodeOperationFollowOn(
            runtime_signals=(
                ReplanCommitted(commit.transition_id),
                DispatchCleanupRequested(authority.dispatch_id),
            )
        ),
    )


def _replan_request(request: BaseModel) -> ReplanRequest:
    assert isinstance(request, (AddChildRequest, UpdateChildRequest, RemoveChildRequest))
    return request


__all__ = ["commit_replan"]
