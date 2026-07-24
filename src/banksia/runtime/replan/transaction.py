from __future__ import annotations

from typing import cast

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.runtime.contracts import (
    AddChildRequest,
    RemoveChildRequest,
    ReplanOperation,
    UpdateChildRequest,
)
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.node_operations.contracts import NodeOperationName
from banksia.runtime.node_operations.follow_on import (
    CommittedNodeOperationFollowOn,
    CommittedNodeOperationResult,
)
from banksia.runtime.post_commit import DispatchCleanupRequested, ReplanCommitted
from banksia.runtime.replan.persistence import commit_replan_rows
from banksia.runtime.replan.planning import ReplanRequest

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
