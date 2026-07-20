from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, suppress
from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.runtime.post_commit.health import RuntimeEffectHealth
from autoclaw.runtime.post_commit.signals import (
    ALL_RUNTIME_EFFECT_SIGNAL_TYPES,
    RuntimeEffectSignal,
    runtime_effect_source_context,
)

logger = logging.getLogger(__name__)

DEFAULT_RUNTIME_EFFECT_QUEUE_CAPACITY = 256

type AsyncSessionContextFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
type RuntimeEffectHandler[SignalT: RuntimeEffectSignal] = Callable[
    [AsyncSession, SignalT], Awaitable[None]
]
type ErasedRuntimeEffectHandler = RuntimeEffectHandler[RuntimeEffectSignal]


class RuntimeEffectRouter:
    """Lifespan-owned typed queue dispatch with no domain reconciliation logic."""

    def __init__(
        self,
        *,
        session_factory: AsyncSessionContextFactory,
        queue_capacity: int = DEFAULT_RUNTIME_EFFECT_QUEUE_CAPACITY,
        health: RuntimeEffectHealth | None = None,
    ) -> None:
        if queue_capacity <= 0:
            raise ValueError("queue_capacity must be positive")
        self._session_factory = session_factory
        self._queue_capacity = queue_capacity
        self._health = health or RuntimeEffectHealth()
        self._routes: dict[type[RuntimeEffectSignal], ErasedRuntimeEffectHandler] = {}
        self._queue: asyncio.Queue[RuntimeEffectSignal] | None = None
        self._task_group: asyncio.TaskGroup | None = None
        self._active_tasks: set[asyncio.Task[None]] = set()
        self._is_accepting = False
        self._has_entered = False

    @property
    def health(self) -> RuntimeEffectHealth:
        return self._health

    def register[SignalT: RuntimeEffectSignal](
        self,
        signal_type: type[SignalT],
        handler: RuntimeEffectHandler[SignalT],
    ) -> None:
        """Register one exact signal type before entering the lifespan context."""

        if self._has_entered:
            raise RuntimeError("runtime effect routes are immutable after lifespan entry")
        if signal_type not in ALL_RUNTIME_EFFECT_SIGNAL_TYPES:
            raise TypeError(f"unsupported runtime effect signal type: {signal_type.__name__}")
        if signal_type in self._routes:
            raise ValueError(f"runtime effect signal already registered: {signal_type.__name__}")

        async def invoke_exact_handler(
            session: AsyncSession,
            signal: RuntimeEffectSignal,
        ) -> None:
            if type(signal) is not signal_type:
                raise TypeError(
                    f"route for {signal_type.__name__} received {type(signal).__name__}"
                )
            await handler(session, signal)

        self._routes[signal_type] = invoke_exact_handler

    def publish(self, signal: RuntimeEffectSignal) -> bool:
        """Attempt nonblocking enqueue and report rejection through runtime health."""

        queue = self._publication_queue(signal)
        if queue is None:
            return False
        try:
            queue.put_nowait(signal)
        except asyncio.QueueFull:
            self._health.mark_failure(
                failure_kind="queue_full",
                signal=signal,
            )
            return False
        except Exception as exc:
            self._health.mark_failure(
                failure_kind="publish_failed",
                signal=signal,
                exception_type=type(exc).__name__,
            )
            _log_runtime_failure("runtime effect publication failed", signal, exc)
            return False
        return True

    async def publish_startup(self, signal: RuntimeEffectSignal) -> bool:
        """Await queue capacity during finite startup, never handler completion."""

        queue = self._publication_queue(signal)
        if queue is None:
            return False
        try:
            await queue.put(signal)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._health.mark_failure(
                failure_kind="publish_failed",
                signal=signal,
                exception_type=type(exc).__name__,
            )
            _log_runtime_failure("runtime startup publication failed", signal, exc)
            return False
        return True

    async def __aenter__(self) -> Self:
        if self._has_entered:
            raise RuntimeError("runtime effect router lifespan cannot be re-entered")
        self._has_entered = True
        self._queue = asyncio.Queue(maxsize=self._queue_capacity)
        self._task_group = asyncio.TaskGroup()
        await self._task_group.__aenter__()
        self._is_accepting = True
        self._track_task(
            self._task_group.create_task(
                self._run_dispatcher(),
                name="autoclaw-runtime-effect-router",
            )
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        self._is_accepting = False
        for task in tuple(self._active_tasks):
            task.cancel()

        task_group = self._task_group
        self._task_group = None
        self._queue = None
        if task_group is None:
            return None
        await task_group.__aexit__(exc_type, exc_value, traceback)
        return None

    async def _run_dispatcher(self) -> None:
        try:
            while True:
                queue = self._queue
                task_group = self._task_group
                if queue is None or task_group is None:
                    return
                signal = await queue.get()
                try:
                    handler = self._routes[type(signal)]
                    self._track_task(
                        task_group.create_task(
                            self._run_handler(handler, signal),
                            name=f"autoclaw-runtime-effect-{type(signal).__name__}",
                        )
                    )
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
            _log_runtime_failure("runtime effect dispatcher failed", None, exc)

    async def _run_handler(
        self,
        handler: ErasedRuntimeEffectHandler,
        signal: RuntimeEffectSignal,
    ) -> None:
        try:
            async with self._session_factory() as session:
                await handler(session, signal)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._health.mark_failure(
                failure_kind="handler_failed",
                signal=signal,
                exception_type=type(exc).__name__,
            )
            _log_runtime_failure("runtime effect handler failed", signal, exc)

    def _track_task(self, task: asyncio.Task[None]) -> None:
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)

    def _publication_queue(
        self,
        signal: RuntimeEffectSignal,
    ) -> asyncio.Queue[RuntimeEffectSignal] | None:
        if type(signal) not in ALL_RUNTIME_EFFECT_SIGNAL_TYPES:
            self._health.mark_failure(
                failure_kind="unsupported_signal",
                signal=signal,
            )
            return None
        if type(signal) not in self._routes:
            self._health.mark_failure(
                failure_kind="unregistered_signal",
                signal=signal,
            )
            return None
        if not self._is_accepting or self._queue is None:
            self._health.mark_failure(
                failure_kind="router_inactive",
                signal=signal,
            )
            return None
        return self._queue


def _log_runtime_failure(
    message: str,
    signal: RuntimeEffectSignal | None,
    exc: Exception,
) -> None:
    context = dict(runtime_effect_source_context(signal)) if signal is not None else {}
    with suppress(Exception):
        logger.error(
            message,
            extra={
                "runtime_effect_signal": type(signal).__name__ if signal is not None else None,
                "runtime_effect_source": context,
                "exception_type": type(exc).__name__,
            },
        )


__all__ = [
    "DEFAULT_RUNTIME_EFFECT_QUEUE_CAPACITY",
    "AsyncSessionContextFactory",
    "RuntimeEffectHandler",
    "RuntimeEffectRouter",
]
