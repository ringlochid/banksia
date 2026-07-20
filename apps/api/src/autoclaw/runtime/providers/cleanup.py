from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.persistence.models import DispatchTurnModel
from autoclaw.runtime.post_commit import DispatchCleanupRequested
from autoclaw.runtime.providers.contracts import DEFAULT_PROVIDER_STOP_TIMEOUT_SECONDS
from autoclaw.runtime.providers.registry import ProviderAdapterRegistry

logger = logging.getLogger(__name__)

_PROVIDER_STOP_REASONS = frozenset(
    {
        "paused",
        "cancelled",
        "control_failed",
        "task_terminal",
    }
)

type ProviderDispatchCleanupHandler = Callable[
    [AsyncSession, DispatchCleanupRequested], Awaitable[None]
]


def create_provider_dispatch_cleanup_handler(
    adapters: ProviderAdapterRegistry,
    *,
    stop_timeout_seconds: float = DEFAULT_PROVIDER_STOP_TIMEOUT_SECONDS,
) -> ProviderDispatchCleanupHandler:
    """Create best-effort provider stop for exact committed cleanup reasons."""
    if stop_timeout_seconds <= 0:
        raise ValueError("provider stop timeout must be positive")

    async def stop_closed_dispatch(
        session: AsyncSession,
        signal: DispatchCleanupRequested,
    ) -> None:
        row = (
            await session.execute(
                select(
                    DispatchTurnModel.status,
                    DispatchTurnModel.closed_reason,
                    DispatchTurnModel.provider_route_kind,
                ).where(DispatchTurnModel.dispatch_id == signal.dispatch_id)
            )
        ).one_or_none()
        await session.rollback()
        if row is None or row.status != "closed" or row.closed_reason not in _PROVIDER_STOP_REASONS:
            return
        try:
            adapter = adapters.get(ProviderKind(row.provider_route_kind))
        except (LookupError, ValueError):
            return
        try:
            async with asyncio.timeout(stop_timeout_seconds):
                await adapter.stop(signal.dispatch_id)
        except Exception as exc:
            logger.warning(
                "provider cleanup did not complete cleanly",
                extra={
                    "provider_kind": adapter.kind.value,
                    "dispatch_id": signal.dispatch_id,
                    "exception_type": type(exc).__name__,
                },
            )

    return stop_closed_dispatch


__all__ = [
    "ProviderDispatchCleanupHandler",
    "create_provider_dispatch_cleanup_handler",
]
