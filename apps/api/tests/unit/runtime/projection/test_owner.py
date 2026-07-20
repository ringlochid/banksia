from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from autoclaw.runtime.projection import (
    SupportProjectionOwner,
    WorkflowManifestProjection,
)
from sqlalchemy.ext.asyncio import AsyncSession


@asynccontextmanager
async def session_context() -> AsyncIterator[AsyncSession]:
    async with AsyncSession() as session:
        yield session


async def test_owner_retries_failure_without_stopping_later_projection() -> None:
    completed = asyncio.Event()
    attempts: dict[str, int] = {}

    async def project(session: AsyncSession, signal: object) -> None:
        del session
        assert isinstance(signal, WorkflowManifestProjection)
        attempts[signal.flow_id] = attempts.get(signal.flow_id, 0) + 1
        if signal.flow_id == "flow.retry" and attempts[signal.flow_id] == 1:
            raise RuntimeError("sensitive filesystem detail")
        if attempts.get("flow.retry") == 2 and attempts.get("flow.next") == 1:
            completed.set()

    owner = SupportProjectionOwner(session_factory=session_context, handler=project)
    async with owner:
        assert owner.publish(WorkflowManifestProjection("flow.retry", "revision.1"))
        assert owner.publish(WorkflowManifestProjection("flow.next", "revision.1"))
        await asyncio.wait_for(completed.wait(), timeout=1)

    snapshot = owner.health.snapshot()
    assert attempts == {"flow.retry": 2, "flow.next": 1}
    assert snapshot.failure_count == 1
    assert snapshot.last_failure is not None
    assert snapshot.last_failure.failure_kind == "handler_failed"
    assert "sensitive filesystem detail" not in repr(snapshot)
    assert not owner.is_accepting
    assert not hasattr(owner, "start")
    assert not hasattr(owner, "close")
    assert not hasattr(owner, "drain")
    assert not hasattr(owner, "wait")


async def test_owner_rejects_overflow_and_post_shutdown_publish_visibly() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def project(session: AsyncSession, signal: object) -> None:
        del session, signal
        started.set()
        await release.wait()

    owner = SupportProjectionOwner(
        session_factory=session_context,
        queue_capacity=1,
        handler=project,
    )
    async with owner:
        assert owner.publish(WorkflowManifestProjection("flow.active", "revision.1"))
        await asyncio.wait_for(started.wait(), timeout=1)
        assert owner.publish(WorkflowManifestProjection("flow.queued", "revision.1"))
        assert not owner.publish(WorkflowManifestProjection("flow.full", "revision.1"))
        release.set()

    assert not owner.publish(WorkflowManifestProjection("flow.closed", "revision.1"))
    snapshot = owner.health.snapshot()
    assert snapshot.failure_count == 2
    assert snapshot.last_failure is not None
    assert snapshot.last_failure.failure_kind == "owner_inactive"


async def test_startup_publish_waits_only_for_queue_capacity() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    all_completed = asyncio.Event()
    completed: list[str] = []

    async def project(session: AsyncSession, signal: object) -> None:
        del session
        assert isinstance(signal, WorkflowManifestProjection)
        started.set()
        if signal.flow_id == "flow.active":
            await release.wait()
        completed.append(signal.flow_id)
        if len(completed) == 3:
            all_completed.set()

    owner = SupportProjectionOwner(
        session_factory=session_context,
        queue_capacity=1,
        handler=project,
    )
    async with owner:
        assert owner.publish(WorkflowManifestProjection("flow.active", "revision.1"))
        await asyncio.wait_for(started.wait(), timeout=1)
        assert owner.publish(WorkflowManifestProjection("flow.queued", "revision.1"))
        admission = asyncio.create_task(
            owner.publish_startup(WorkflowManifestProjection("flow.backpressured", "revision.1"))
        )
        await asyncio.sleep(0)
        assert not admission.done()
        release.set()
        assert await asyncio.wait_for(admission, timeout=1)
        await asyncio.wait_for(all_completed.wait(), timeout=1)

    assert completed == ["flow.active", "flow.queued", "flow.backpressured"]
