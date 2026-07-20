from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from autoclaw.runtime.post_commit.health import (
    RuntimeEffectFailureKind,
    RuntimeEffectHealth,
)
from autoclaw.runtime.post_commit.router import RuntimeEffectRouter
from autoclaw.runtime.post_commit.signals import BoundaryAccepted, FlowStartCommitted
from sqlalchemy.ext.asyncio import AsyncSession


@asynccontextmanager
async def session_context() -> AsyncIterator[AsyncSession]:
    async with AsyncSession() as session:
        yield session


class RecordingRuntimeEffectHealth(RuntimeEffectHealth):
    def __init__(self) -> None:
        super().__init__()
        self.failure_recorded = asyncio.Event()

    def mark_failure(
        self,
        *,
        failure_kind: RuntimeEffectFailureKind,
        signal: object | None,
        exception_type: str | None = None,
    ) -> None:
        super().mark_failure(
            failure_kind=failure_kind,
            signal=signal,
            exception_type=exception_type,
        )
        self.failure_recorded.set()


async def test_router_runs_handlers_concurrently_with_fresh_sessions() -> None:
    both_started = asyncio.Event()
    release_handlers = asyncio.Event()
    both_finished = asyncio.Event()
    session_ids: list[int] = []
    finished_count = 0

    async def handle_flow_start(
        session: AsyncSession,
        signal: FlowStartCommitted,
    ) -> None:
        nonlocal finished_count
        assert signal.flow_id in {"flow.alpha", "flow.beta"}
        session_ids.append(id(session))
        if len(session_ids) == 2:
            both_started.set()
        await release_handlers.wait()
        finished_count += 1
        if finished_count == 2:
            both_finished.set()

    router = RuntimeEffectRouter(session_factory=session_context)
    router.register(FlowStartCommitted, handle_flow_start)

    async with router:
        assert router.publish(FlowStartCommitted("flow.alpha")) is True
        assert router.publish(FlowStartCommitted("flow.beta")) is True
        await asyncio.wait_for(both_started.wait(), timeout=1)

        assert len(set(session_ids)) == 2

        release_handlers.set()
        await asyncio.wait_for(both_finished.wait(), timeout=1)


async def test_router_isolates_handler_failure_and_keeps_routing() -> None:
    failing_signal_routed = asyncio.Event()
    successful_signal_routed = asyncio.Event()

    async def handle_flow_start(
        session: AsyncSession,
        signal: FlowStartCommitted,
    ) -> None:
        del session
        if signal.flow_id == "flow.failure":
            failing_signal_routed.set()
            raise RuntimeError("secret payload must not enter health")
        successful_signal_routed.set()

    health = RecordingRuntimeEffectHealth()
    router = RuntimeEffectRouter(session_factory=session_context, health=health)
    router.register(FlowStartCommitted, handle_flow_start)

    async with router:
        assert router.publish(FlowStartCommitted("flow.failure")) is True
        assert router.publish(FlowStartCommitted("flow.success")) is True
        await asyncio.wait_for(failing_signal_routed.wait(), timeout=1)
        await asyncio.wait_for(successful_signal_routed.wait(), timeout=1)
        await asyncio.wait_for(health.failure_recorded.wait(), timeout=1)

    snapshot = router.health.snapshot()
    assert snapshot.failure_count == 1
    assert snapshot.last_failure is not None
    assert snapshot.last_failure.failure_kind == "handler_failed"
    assert snapshot.last_failure.exception_type == "RuntimeError"
    assert "secret payload" not in repr(snapshot)


async def test_router_rejects_unregistered_and_full_queue_visibly() -> None:
    async def handle_flow_start(
        session: AsyncSession,
        signal: FlowStartCommitted,
    ) -> None:
        del session, signal

    router = RuntimeEffectRouter(
        session_factory=session_context,
        queue_capacity=1,
    )
    router.register(FlowStartCommitted, handle_flow_start)

    async with router:
        assert router.publish(BoundaryAccepted("dispatch.unregistered")) is False
        assert router.publish(FlowStartCommitted("flow.queued")) is True
        assert router.publish(FlowStartCommitted("flow.rejected")) is False

    snapshot = router.health.snapshot()
    assert snapshot.failure_count == 2
    assert snapshot.last_failure is not None
    assert snapshot.last_failure.failure_kind == "queue_full"


async def test_startup_publication_waits_only_for_queue_capacity() -> None:
    handler_started = asyncio.Event()
    release_handler = asyncio.Event()

    async def handle_flow_start(
        session: AsyncSession,
        signal: FlowStartCommitted,
    ) -> None:
        del session, signal
        handler_started.set()
        await release_handler.wait()

    router = RuntimeEffectRouter(session_factory=session_context, queue_capacity=1)
    router.register(FlowStartCommitted, handle_flow_start)

    async with router:
        assert router.publish(FlowStartCommitted("flow.first")) is True
        await asyncio.wait_for(handler_started.wait(), timeout=1)

        assert await asyncio.wait_for(
            router.publish_startup(FlowStartCommitted("flow.second")),
            timeout=1,
        )
        release_handler.set()


async def test_router_context_exit_cancels_disposable_handler_work() -> None:
    handler_started = asyncio.Event()
    handler_cancelled = asyncio.Event()
    never_release = asyncio.Event()

    async def handle_flow_start(
        session: AsyncSession,
        signal: FlowStartCommitted,
    ) -> None:
        del session, signal
        handler_started.set()
        try:
            await never_release.wait()
        finally:
            handler_cancelled.set()

    router = RuntimeEffectRouter(session_factory=session_context)
    router.register(FlowStartCommitted, handle_flow_start)

    async with router:
        assert router.publish(FlowStartCommitted("flow.alpha")) is True
        await asyncio.wait_for(handler_started.wait(), timeout=1)

    assert handler_cancelled.is_set()
    assert router.publish(FlowStartCommitted("flow.after-shutdown")) is False
    assert not hasattr(router, "start")
    assert not hasattr(router, "close")
    assert not hasattr(router, "drain")
    assert not hasattr(router, "wait_for_runtime_effects")
