from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.runtime.contracts import DelegateRequest
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.delegation import commit_delegation_wave
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.node_operations.contracts import NodeOperationName
from banksia.runtime.replan import commit_replan


async def execute_structural_node_operation(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    operation_name: NodeOperationName,
    request: BaseModel,
    *,
    dispatch_opening_dependencies: DispatchOpeningDependencies | None,
) -> BaseModel:
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
    if operation_name in {
        NodeOperationName.ADD_CHILD,
        NodeOperationName.UPDATE_CHILD,
        NodeOperationName.REMOVE_CHILD,
    }:
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


__all__ = ["execute_structural_node_operation"]
