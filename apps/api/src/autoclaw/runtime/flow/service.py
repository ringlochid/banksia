from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.runtime.contracts import (
    RuntimeFlowPauseResponse,
    RuntimeFlowRead,
    RuntimeFlowSummaryListResponse,
    TaskEventSource,
)
from autoclaw.runtime.dispatch.preparation import DispatchOpeningDependencies
from autoclaw.runtime.flow.control import cancel_flow, continue_flow, pause_flow
from autoclaw.runtime.flow.reads import list_runtime_flow_summaries, read_runtime_flow
from autoclaw.runtime.post_commit import RuntimeEffectPublisher


async def runtime_flow_read(session: AsyncSession, task_id: str) -> RuntimeFlowRead:
    return await read_runtime_flow(session, task_id)


async def list_runtime_flows(
    session: AsyncSession,
    *,
    q: str | None = None,
    cursor: str | None = None,
    status: str = "any",
    limit: int = 50,
    sort: str = "updated_at_desc",
) -> RuntimeFlowSummaryListResponse:
    return await list_runtime_flow_summaries(
        session,
        q=q,
        cursor=cursor,
        status=status,
        limit=limit,
        sort=sort,
    )


async def continue_runtime_flow(
    session: AsyncSession,
    task_id: str,
    *,
    expected_active_flow_revision_id: str,
    expected_control_revision: int,
    dependencies: DispatchOpeningDependencies,
    actor_ref: str | None = None,
    event_source: TaskEventSource = TaskEventSource.CONTROL_API,
) -> RuntimeFlowRead:
    return await continue_flow(
        session,
        task_id,
        expected_active_flow_revision_id=expected_active_flow_revision_id,
        expected_control_revision=expected_control_revision,
        dependencies=dependencies,
        actor_ref=actor_ref,
        event_source=event_source,
    )


async def pause_runtime_flow(
    session: AsyncSession,
    task_id: str,
    *,
    expected_active_flow_revision_id: str,
    expected_control_revision: int,
    actor_ref: str | None = None,
    event_source: TaskEventSource = TaskEventSource.CONTROL_API,
    runtime_effect_publisher: RuntimeEffectPublisher | None = None,
) -> RuntimeFlowPauseResponse:
    return await pause_flow(
        session,
        task_id,
        expected_active_flow_revision_id=expected_active_flow_revision_id,
        expected_control_revision=expected_control_revision,
        actor_ref=actor_ref,
        event_source=event_source,
        runtime_effect_publisher=runtime_effect_publisher,
    )


async def cancel_runtime_flow(
    session: AsyncSession,
    task_id: str,
    *,
    expected_active_flow_revision_id: str,
    expected_control_revision: int,
    actor_ref: str | None = None,
    event_source: TaskEventSource = TaskEventSource.CONTROL_API,
    runtime_effect_publisher: RuntimeEffectPublisher | None = None,
) -> RuntimeFlowRead:
    return await cancel_flow(
        session,
        task_id,
        expected_active_flow_revision_id=expected_active_flow_revision_id,
        expected_control_revision=expected_control_revision,
        actor_ref=actor_ref,
        event_source=event_source,
        runtime_effect_publisher=runtime_effect_publisher,
    )


__all__ = [
    "cancel_runtime_flow",
    "continue_runtime_flow",
    "list_runtime_flows",
    "pause_runtime_flow",
    "runtime_flow_read",
]
