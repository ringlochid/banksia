from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.task_control.contracts import ControllerTaskState
from banksia.runtime.task_control.reads import read_runtime_task as read_controller_runtime_task


async def runtime_task_read(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> ControllerTaskState:
    return await read_controller_runtime_task(session, authority.task_id)


__all__ = ["runtime_task_read"]
