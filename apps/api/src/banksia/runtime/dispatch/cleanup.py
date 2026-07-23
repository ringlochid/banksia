from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import DispatchTurnModel
from banksia.runtime.node_mcp import DispatchMcpBindingRegistry
from banksia.runtime.post_commit.signals import DispatchCleanupRequested

type DispatchBindingCleanupHandler = Callable[
    [AsyncSession, DispatchCleanupRequested], Awaitable[None]
]


def create_dispatch_binding_cleanup_handler(
    binding_registry: DispatchMcpBindingRegistry,
) -> DispatchBindingCleanupHandler:
    """Create exact closed-dispatch cleanup for process-local MCP authority."""

    async def revoke_closed_dispatch_binding(
        session: AsyncSession,
        signal: DispatchCleanupRequested,
    ) -> None:
        status = await session.scalar(
            select(DispatchTurnModel.status).where(
                DispatchTurnModel.dispatch_id == signal.dispatch_id
            )
        )
        if status == "closed":
            binding_registry.revoke_dispatch(signal.dispatch_id)

    return revoke_closed_dispatch_binding


__all__ = ["create_dispatch_binding_cleanup_handler"]
