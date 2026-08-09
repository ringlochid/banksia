from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    MemberConfigurationModel,
    TaskModel,
    TeamRevisionMemberModel,
)
from banksia.runtime.clock import utc_now
from banksia.runtime.contracts import TaskEventSource, TaskEventType
from banksia.runtime.control_transitions import close_current_task_dispatches
from banksia.runtime.task_events import append_task_event

_RETIRED_PROVIDER_KIND = "openclaw"


async def pause_tasks_using_retired_providers(
    session: AsyncSession,
    *,
    paused_at: datetime | None = None,
) -> int:
    """Pause nonterminal Tasks whose current Team still selects a retired provider."""

    affected = await _read_affected_tasks(session)
    if not affected:
        await session.rollback()
        return 0

    transition_time = paused_at or utc_now()
    for task in affected.values():
        await _pause_affected_task(session, task=task, paused_at=transition_time)
    await session.commit()
    return len(affected)


async def _read_affected_tasks(session: AsyncSession) -> dict[str, TaskModel]:
    task_rows = (
        await session.execute(
            select(TaskModel, MemberConfigurationModel.requested_provider_json)
            .join(
                TeamRevisionMemberModel,
                (TeamRevisionMemberModel.task_id == TaskModel.task_id)
                & (TeamRevisionMemberModel.team_revision_id == TaskModel.current_team_revision_id),
            )
            .join(
                MemberConfigurationModel,
                (MemberConfigurationModel.task_id == TeamRevisionMemberModel.task_id)
                & (MemberConfigurationModel.member_id == TeamRevisionMemberModel.member_id)
                & (
                    MemberConfigurationModel.member_configuration_id
                    == TeamRevisionMemberModel.member_configuration_id
                ),
            )
            .where(TaskModel.status.in_(("running", "paused")))
        )
    ).all()
    return {
        task.task_id: task
        for task, requested_provider in task_rows
        if isinstance(requested_provider, dict)
        and requested_provider.get("kind") == _RETIRED_PROVIDER_KIND
        and task.pause_reason != "provider_retired"
    }


async def _pause_affected_task(
    session: AsyncSession,
    *,
    task: TaskModel,
    paused_at: datetime,
) -> None:
    next_revision = task.control_revision + 1
    changed_task_id = await session.scalar(
        update(TaskModel)
        .where(
            TaskModel.task_id == task.task_id,
            TaskModel.current_team_revision_id == task.current_team_revision_id,
            TaskModel.control_revision == task.control_revision,
            TaskModel.status.in_(("running", "paused")),
        )
        .values(
            status="paused",
            pause_reason="provider_retired",
            pause_details={
                "failure_code": "provider_retired",
                "provider": _RETIRED_PROVIDER_KIND,
            },
            paused_at=paused_at,
            paused_by_actor_ref="controller.runtime",
            control_revision=next_revision,
            updated_at=paused_at,
        )
        .returning(TaskModel.task_id)
    )
    if changed_task_id is None:
        await session.rollback()
        raise RuntimeError("Task changed during retired-provider startup reconciliation")
    await close_current_task_dispatches(
        session,
        task_id=task.task_id,
        closed_reason="paused",
        closed_at=paused_at,
    )
    await append_task_event(
        session,
        task_id=task.task_id,
        event_type=TaskEventType.TASK_PAUSED,
        event_source=TaskEventSource.CONTROLLER,
        occurred_at=paused_at,
        team_revision_id=task.current_team_revision_id,
        actor_ref="controller.runtime",
        payload={
            "pause_reason": "provider_retired",
            "control_revision": next_revision,
            "actor_ref": "controller.runtime",
            "summary": "Paused because the current Team selects retired provider OpenClaw.",
        },
    )


__all__ = ["pause_tasks_using_retired_providers"]
