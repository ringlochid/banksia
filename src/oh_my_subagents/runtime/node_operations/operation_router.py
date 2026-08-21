from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.runtime.checkpoint import commit_checkpoint
from oh_my_subagents.runtime.contracts import CheckpointRequest, DelegateRequest
from oh_my_subagents.runtime.contracts.operation_failure import OperationFailureCode
from oh_my_subagents.runtime.delegation import commit_delegation_wave
from oh_my_subagents.runtime.dispatch.authority import NodeOperationAuthority
from oh_my_subagents.runtime.dispatch.preparation import DispatchOpeningDependencies
from oh_my_subagents.runtime.errors import RuntimeOperationError
from oh_my_subagents.runtime.node_operations.contracts import (
    NodeOperationName,
    OpenHumanRequestRequest,
    StartCommandRunRequest,
)
from oh_my_subagents.runtime.node_operations.external_wait_handlers import (
    open_human_request,
    start_command_run,
)
from oh_my_subagents.runtime.replan import commit_replan

_REPLAN_OPERATIONS = frozenset(
    {
        NodeOperationName.ADD_CHILD,
        NodeOperationName.UPDATE_CHILD,
        NodeOperationName.REMOVE_CHILD,
    }
)


async def execute_controller_node_operation(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    operation_name: NodeOperationName,
    request: BaseModel,
    *,
    dispatch_opening_dependencies: DispatchOpeningDependencies | None = None,
) -> BaseModel:
    if operation_name == NodeOperationName.CHECKPOINT:
        assert isinstance(request, CheckpointRequest)
        return await commit_checkpoint(
            session,
            authority,
            request,
            dispatch_opening_dependencies=dispatch_opening_dependencies,
        )
    if operation_name == NodeOperationName.OPEN_HUMAN_REQUEST:
        assert isinstance(request, OpenHumanRequestRequest)
        return await open_human_request(session, authority, request)
    if operation_name == NodeOperationName.START_COMMAND_RUN:
        assert isinstance(request, StartCommandRunRequest)
        return await start_command_run(session, authority, request)
    if dispatch_opening_dependencies is None:
        raise RuntimeOperationError(
            code=OperationFailureCode.INTERNAL_ERROR,
            summary="provider resolution is not configured for this operation",
            is_retryable=False,
        )
    if operation_name == NodeOperationName.DELEGATE:
        assert isinstance(request, DelegateRequest)
        return await commit_delegation_wave(
            session,
            authority,
            request,
            dependencies=dispatch_opening_dependencies,
        )
    if operation_name in _REPLAN_OPERATIONS:
        return await commit_replan(
            session,
            authority,
            operation_name,
            request,
            dependencies=dispatch_opening_dependencies,
        )
    raise RuntimeOperationError(
        code=OperationFailureCode.INVALID_REQUEST_SHAPE,
        summary=f"unsupported Node operation '{operation_name.value}'",
        is_retryable=False,
    )


__all__ = ["execute_controller_node_operation"]
