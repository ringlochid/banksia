from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.runtime.checkpoint import commit_checkpoint
from banksia.runtime.contracts import CheckpointRequest
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.node_operations.contracts import (
    NodeOperationName,
    OpenHumanRequestRequest,
    StartCommandRunRequest,
)
from banksia.runtime.node_operations.external_wait_handlers import (
    open_human_request,
    start_command_run,
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

    from banksia.runtime.node_operations.structural_handlers import (
        execute_structural_node_operation,
    )

    return await execute_structural_node_operation(
        session,
        authority,
        operation_name,
        request,
        dispatch_opening_dependencies=dispatch_opening_dependencies,
    )


__all__ = ["execute_controller_node_operation"]
