from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from banksia.persistence.models import (
    AttemptModel,
    DispatchTurnModel,
    MemberConfigurationModel,
    TaskEventModel,
    TaskModel,
)
from banksia.runtime.providers.retirement import pause_tasks_using_retired_providers
from tests.helpers.executor_harness import seeded_async_executor


async def test_startup_pauses_a_task_that_selects_the_retired_provider(
    tmp_path: Path,
) -> None:
    paused_at = datetime(2026, 8, 9, 1, 2, 3, tzinfo=UTC)
    async with seeded_async_executor(tmp_path, suffix="retired-provider") as (
        _,
        session_factory,
        ids,
        _,
    ):
        async with session_factory() as session:
            configuration = await session.scalar(
                select(MemberConfigurationModel).where(
                    MemberConfigurationModel.task_id == ids.task_id,
                    MemberConfigurationModel.member_id == ids.root_member_id,
                )
            )
            assert configuration is not None
            configuration.requested_provider_json = {"kind": "openclaw"}
            await session.commit()

        async with session_factory() as session:
            affected = await pause_tasks_using_retired_providers(
                session,
                paused_at=paused_at,
            )

        async with session_factory() as session:
            task = await session.get(TaskModel, ids.task_id)
            attempt = await session.get(AttemptModel, ids.root_attempt_id)
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            event = await session.scalar(
                select(TaskEventModel).where(
                    TaskEventModel.task_id == ids.task_id,
                    TaskEventModel.event_type == "task_paused",
                )
            )
            assert task is not None
            task_state = (
                task.status,
                task.pause_reason,
                task.pause_details,
                task.paused_at,
            )
            attempt_dispatch_id = attempt.current_dispatch_id if attempt is not None else None
            dispatch_closed_reason = dispatch.closed_reason if dispatch is not None else None
            event_pause_reason = event.payload["pause_reason"] if event is not None else None

        async with session_factory() as session:
            repeated = await pause_tasks_using_retired_providers(session)

    assert affected == 1
    assert repeated == 0
    assert task_state == (
        "paused",
        "provider_retired",
        {"failure_code": "provider_retired", "provider": "openclaw"},
        paused_at,
    )
    assert attempt_dispatch_id is None
    assert dispatch_closed_reason == "paused"
    assert event_pause_reason == "provider_retired"
