"""Task lifecycle service boundary."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.runtime.contracts import TaskEventSource
from oh_my_subagents.runtime.dispatch.preparation import DispatchOpeningDependencies
from oh_my_subagents.runtime.post_commit import RuntimeEffectPublisher
from oh_my_subagents.runtime.task_control.contracts import (
    ControllerTaskPauseResult,
    ControllerTaskState,
    ControllerTaskSummaryPage,
)
from oh_my_subagents.runtime.task_control.control import cancel_task, continue_task, pause_task
from oh_my_subagents.runtime.task_control.reads import (
    list_runtime_task_summaries,
    read_runtime_task,
)


async def runtime_task_read(session: AsyncSession, task_id: str) -> ControllerTaskState:
    return await read_runtime_task(session, task_id)


async def list_runtime_tasks(
    session: AsyncSession,
    *,
    q: str | None = None,
    cursor: str | None = None,
    status: str = "any",
    limit: int = 50,
    sort: str = "updated_at_desc",
) -> ControllerTaskSummaryPage:
    return await list_runtime_task_summaries(
        session,
        q=q,
        cursor=cursor,
        status=status,
        limit=limit,
        sort=sort,
    )


async def continue_runtime_task(
    session: AsyncSession,
    task_id: str,
    *,
    expected_team_revision_id: str,
    expected_control_revision: int,
    dependencies: DispatchOpeningDependencies,
    actor_ref: str | None = None,
    event_source: TaskEventSource = TaskEventSource.CONTROL_API,
) -> ControllerTaskState:
    return await continue_task(
        session,
        task_id,
        expected_team_revision_id=expected_team_revision_id,
        expected_control_revision=expected_control_revision,
        dependencies=dependencies,
        actor_ref=actor_ref,
        event_source=event_source,
    )


async def pause_runtime_task(
    session: AsyncSession,
    task_id: str,
    *,
    expected_team_revision_id: str,
    expected_control_revision: int,
    actor_ref: str | None = None,
    event_source: TaskEventSource = TaskEventSource.CONTROL_API,
    runtime_effect_publisher: RuntimeEffectPublisher | None = None,
) -> ControllerTaskPauseResult:
    return await pause_task(
        session,
        task_id,
        expected_team_revision_id=expected_team_revision_id,
        expected_control_revision=expected_control_revision,
        actor_ref=actor_ref,
        event_source=event_source,
        runtime_effect_publisher=runtime_effect_publisher,
    )


async def cancel_runtime_task(
    session: AsyncSession,
    task_id: str,
    *,
    expected_team_revision_id: str,
    expected_control_revision: int,
    actor_ref: str | None = None,
    event_source: TaskEventSource = TaskEventSource.CONTROL_API,
    runtime_effect_publisher: RuntimeEffectPublisher | None = None,
) -> ControllerTaskState:
    return await cancel_task(
        session,
        task_id,
        expected_team_revision_id=expected_team_revision_id,
        expected_control_revision=expected_control_revision,
        actor_ref=actor_ref,
        event_source=event_source,
        runtime_effect_publisher=runtime_effect_publisher,
    )


__all__ = [
    "cancel_runtime_task",
    "continue_runtime_task",
    "list_runtime_tasks",
    "pause_runtime_task",
    "runtime_task_read",
]
