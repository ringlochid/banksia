from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, suppress
from dataclasses import dataclass
from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.runtime.projection.health import SupportProjectionHealth
from autoclaw.runtime.projection.materialization import project_support_signal
from autoclaw.runtime.projection.signals import (
    ALL_SUPPORT_PROJECTION_SIGNAL_TYPES,
    SupportProjectionSignal,
    support_projection_source_context,
)

logger = logging.getLogger(__name__)

DEFAULT_SUPPORT_PROJECTION_QUEUE_CAPACITY = 256
DEFAULT_SUPPORT_PROJECTION_RETRY_LIMIT = 1

type AsyncSessionContextFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
type SupportProjectionHandler = Callable[
    [AsyncSession, SupportProjectionSignal],
    Awaitable[None],
]


@dataclass(frozen=True, slots=True)
class _QueuedProjection:
    signal: SupportProjectionSignal
    attempt: int = 0


class SupportProjectionOwner:
    """Lifespan-owned bounded queue for non-authoritative support files."""

    def __init__(
        self,
        *,
        session_factory: AsyncSessionContextFactory,
        queue_capacity: int = DEFAULT_SUPPORT_PROJECTION_QUEUE_CAPACITY,
        retry_limit: int = DEFAULT_SUPPORT_PROJECTION_RETRY_LIMIT,
        health: SupportProjectionHealth | None = None,
        handler: SupportProjectionHandler = project_support_signal,
    ) -> None:
        if queue_capacity <= 0:
            raise ValueError("queue_capacity must be positive")
        if retry_limit < 0:
            raise ValueError("retry_limit must not be negative")
        self._session_factory = session_factory
        self._queue_capacity = queue_capacity
        self._retry_limit = retry_limit
        self._health = health or SupportProjectionHealth()
        self._handler = handler
        self._queue: asyncio.Queue[_QueuedProjection] | None = None
        self._dispatcher: asyncio.Task[None] | None = None
        self._is_accepting = False
        self._has_entered = False

    @property
    def health(self) -> SupportProjectionHealth:
        return self._health

    @property
    def is_accepting(self) -> bool:
        return self._is_accepting

    def publish(self, signal: SupportProjectionSignal) -> bool:
        """Attempt a nonblocking enqueue without waiting for projection work."""

        queue = self._admission_queue(signal)
        if queue is None:
            return False
        try:
            queue.put_nowait(_QueuedProjection(signal))
        except asyncio.QueueFull:
            self._health.mark_failure(failure_kind="queue_full", signal=signal)
            return False
        except Exception as exc:
            self._health.mark_failure(
                failure_kind="publish_failed",
                signal=signal,
                exception_type=type(exc).__name__,
            )
            _log_projection_failure("support projection publication failed", signal, exc)
            return False
        return True

    async def publish_startup(self, signal: SupportProjectionSignal) -> bool:
        """Await startup queue capacity without waiting for projection completion."""

        queue = self._admission_queue(signal)
        if queue is None:
            return False
        try:
            await queue.put(_QueuedProjection(signal))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._health.mark_failure(
                failure_kind="publish_failed",
                signal=signal,
                exception_type=type(exc).__name__,
            )
            _log_projection_failure("support projection publication failed", signal, exc)
            return False
        return True

    async def __aenter__(self) -> Self:
        if self._has_entered:
            raise RuntimeError("support projection owner lifespan cannot be re-entered")
        self._has_entered = True
        self._queue = asyncio.Queue(maxsize=self._queue_capacity)
        self._is_accepting = True
        self._dispatcher = asyncio.create_task(
            self._run_dispatcher(),
            name="autoclaw-support-projection-owner",
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        del exc_type, exc_value, traceback
        self._is_accepting = False
        dispatcher = self._dispatcher
        self._dispatcher = None
        self._queue = None
        if dispatcher is None:
            return None
        dispatcher.cancel()
        with suppress(asyncio.CancelledError):
            await dispatcher
        return None

    async def _run_dispatcher(self) -> None:
        try:
            while True:
                queue = self._queue
                if queue is None:
                    return
                queued = await queue.get()
                try:
                    await self._run_projection(queued)
                finally:
                    queue.task_done()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._is_accepting = False
            self._health.mark_failure(
                failure_kind="dispatcher_failed",
                signal=None,
                exception_type=type(exc).__name__,
            )
            _log_projection_failure("support projection dispatcher failed", None, exc)

    def _admission_queue(
        self,
        signal: SupportProjectionSignal,
    ) -> asyncio.Queue[_QueuedProjection] | None:
        if type(signal) not in ALL_SUPPORT_PROJECTION_SIGNAL_TYPES:
            self._health.mark_failure(failure_kind="unsupported_signal", signal=signal)
            return None
        if not self._is_accepting or self._queue is None:
            self._health.mark_failure(failure_kind="owner_inactive", signal=signal)
            return None
        return self._queue

    async def _run_projection(self, queued: _QueuedProjection) -> None:
        try:
            async with self._session_factory() as session:
                await self._handler(session, queued.signal)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._health.mark_failure(
                failure_kind="handler_failed",
                signal=queued.signal,
                exception_type=type(exc).__name__,
            )
            _log_projection_failure("support projection handler failed", queued.signal, exc)
            self._schedule_retry(queued)

    def _schedule_retry(self, queued: _QueuedProjection) -> None:
        if queued.attempt >= self._retry_limit:
            self._health.mark_failure(
                failure_kind="retry_exhausted",
                signal=queued.signal,
            )
            return
        queue = self._queue
        if queue is None or not self._is_accepting:
            return
        try:
            queue.put_nowait(_QueuedProjection(queued.signal, queued.attempt + 1))
        except asyncio.QueueFull:
            self._health.mark_failure(failure_kind="queue_full", signal=queued.signal)


def _log_projection_failure(
    message: str,
    signal: SupportProjectionSignal | None,
    exc: Exception,
) -> None:
    context = dict(support_projection_source_context(signal)) if signal is not None else {}
    with suppress(Exception):
        logger.error(
            message,
            extra={
                "support_projection_signal": (
                    type(signal).__name__ if signal is not None else None
                ),
                "support_projection_source": context,
                "exception_type": type(exc).__name__,
            },
        )


__all__ = [
    "DEFAULT_SUPPORT_PROJECTION_QUEUE_CAPACITY",
    "DEFAULT_SUPPORT_PROJECTION_RETRY_LIMIT",
    "AsyncSessionContextFactory",
    "SupportProjectionHandler",
    "SupportProjectionOwner",
]
