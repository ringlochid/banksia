from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.runtime.contracts import RuntimeFlowRead
from autoclaw.runtime.dispatch.authority import NodeOperationAuthority
from autoclaw.runtime.flow.reads import read_runtime_flow as read_controller_runtime_flow


async def runtime_flow_read(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> RuntimeFlowRead:
    return await read_controller_runtime_flow(session, authority.task_id)


__all__ = ["runtime_flow_read"]
