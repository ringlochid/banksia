from __future__ import annotations

from typing import cast

from autoclaw.runtime.dispatch.cleanup import create_dispatch_binding_cleanup_handler
from autoclaw.runtime.node_mcp import DispatchMcpBindingRegistry
from autoclaw.runtime.post_commit import DispatchCleanupRequested
from sqlalchemy.ext.asyncio import AsyncSession


class DispatchStatusSession:
    def __init__(self, status: str | None) -> None:
        self._status = status

    async def scalar(self, statement: object) -> str | None:
        del statement
        return self._status


async def test_dispatch_cleanup_revokes_only_closed_dispatch_bindings() -> None:
    registry = DispatchMcpBindingRegistry()
    issued = registry.issue_binding(
        task_id="task.alpha",
        dispatch_id="dispatch.alpha",
        provider_start_revision=1,
        exposure_ceiling=("get_current_context",),
    )
    handler = create_dispatch_binding_cleanup_handler(registry)

    await handler(
        cast(AsyncSession, DispatchStatusSession("open")),
        DispatchCleanupRequested("dispatch.alpha"),
    )
    assert registry.authenticate(issued.credential) == issued.binding

    await handler(
        cast(AsyncSession, DispatchStatusSession("closed")),
        DispatchCleanupRequested("dispatch.alpha"),
    )
    assert registry.authenticate(issued.credential) is None


__all__ = []
