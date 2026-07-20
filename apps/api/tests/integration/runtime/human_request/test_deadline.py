from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from autoclaw.persistence.models import (
    FlowModel,
    FlowWaitModel,
    HumanRequestModel,
    TaskEventModel,
)
from autoclaw.runtime.contracts import HumanRequestResolveRequest
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.human_request.deadline import (
    create_human_request_opened_handler,
    expire_human_request,
)
from autoclaw.runtime.human_request.service import resolve_human_request
from autoclaw.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from autoclaw.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    DeadlineScheduler,
    HumanRequestDue,
    HumanRequestOpened,
    HumanRequestTerminal,
)
from autoclaw.runtime.post_commit.bootstrap import read_human_deadline_page
from autoclaw.runtime.post_commit.router import AsyncSessionContextFactory
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import seeded_executor
from tests.helpers.lineage_seed import RuntimeIds


@dataclass
class RecordedTimer:
    delay_seconds: float
    callback: Callable[[], None]
    is_cancelled: bool = False

    def cancel(self) -> None:
        self.is_cancelled = True


class RecordingTimerFactory:
    def __init__(self) -> None:
        self.timers: list[RecordedTimer] = []

    def __call__(
        self,
        delay_seconds: float,
        callback: Callable[[], None],
    ) -> RecordedTimer:
        timer = RecordedTimer(delay_seconds=delay_seconds, callback=callback)
        self.timers.append(timer)
        return timer


async def test_opened_handler_rereads_and_registers_stored_deadline(
    tmp_path: Path,
) -> None:
    now = datetime(2030, 1, 1, 12, tzinfo=UTC)
    due_at = now + timedelta(minutes=5)
    async with seeded_executor(tmp_path, suffix="human-deadline-register") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        request_id = await _open_human_request(executor, ids, due_at=due_at)
        timer_factory = RecordingTimerFactory()
        scheduler = DeadlineScheduler(
            publish=lambda signal: True,
            now=lambda: now,
            schedule_later=timer_factory,
        )

        async with scheduler, session_factory() as session:
            handler = create_human_request_opened_handler(scheduler)
            await handler(
                cast(AsyncSession, session),
                HumanRequestOpened(request_id),
            )

    assert len(timer_factory.timers) == 1
    assert timer_factory.timers[0].delay_seconds == 300
    assert timer_factory.timers[0].is_cancelled is True


async def test_opened_handler_cancels_timer_when_source_has_no_deadline(
    tmp_path: Path,
) -> None:
    now = datetime(2030, 1, 1, 12, tzinfo=UTC)
    async with seeded_executor(tmp_path, suffix="human-without-deadline") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        request_id = await _open_human_request(executor, ids, due_at=None)
        page = await read_human_deadline_page(
            cast(AsyncSessionContextFactory, session_factory),
            None,
            200,
        )
        timer_factory = RecordingTimerFactory()
        scheduler = DeadlineScheduler(
            publish=lambda signal: True,
            now=lambda: now,
            schedule_later=timer_factory,
        )

        async with scheduler:
            scheduler.register(HumanRequestDue(request_id, now + timedelta(minutes=5)))
            async with session_factory() as session:
                handler = create_human_request_opened_handler(scheduler)
                await handler(
                    cast(AsyncSession, session),
                    HumanRequestOpened(request_id),
                )

    assert page.sources == (HumanRequestOpened(request_id),)
    assert timer_factory.timers[0].is_cancelled is True


async def test_elapsed_human_deadline_terminalizes_exact_source_and_wait(
    tmp_path: Path,
) -> None:
    due_at = datetime(2030, 1, 1, 12, tzinfo=UTC)
    terminal_publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="human-deadline-terminal") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        request_id = await _open_human_request(
            executor,
            ids,
            due_at=due_at,
            default_behavior="Continue with the documented safe default.",
        )
        async with session_factory() as session:
            won = await expire_human_request(
                cast(AsyncSession, session),
                signal=HumanRequestDue(request_id, due_at),
                runtime_effect_publisher=terminal_publisher,
                now=due_at + timedelta(seconds=1),
            )

        async with session_factory() as session:
            source = await session.get(HumanRequestModel, request_id)
            flow = await session.get(FlowModel, ids.flow_id)
            wait = await session.get(FlowWaitModel, ids.flow_id)
            event = await session.scalar(
                select(TaskEventModel).where(
                    TaskEventModel.task_id == ids.task_id,
                    TaskEventModel.event_type == "human_request_timed_out",
                )
            )

    assert won is True
    assert source is not None and source.status == "timed_out"
    assert source.resolution_kind == "timed_out"
    assert source.resolution_policy_basis_json == {
        "timeout_policy": {"kind": "deadline"},
        "default_behavior": {
            "value": "Continue with the documented safe default.",
        },
    }
    assert flow is not None and flow.waiting_cause == "none"
    assert flow.waiting_source_id is None
    assert wait is None
    assert event is not None and event.dispatch_id == ids.current_dispatch_id
    assert terminal_publisher.signals == (HumanRequestTerminal(request_id),)


@pytest.mark.parametrize("answer_wins", (True, False))
async def test_answer_and_timeout_have_one_exact_terminal_winner(
    tmp_path: Path,
    *,
    answer_wins: bool,
) -> None:
    due_at = datetime(2030, 1, 1, 12, tzinfo=UTC)
    suffix = f"human-answer-timeout-{answer_wins}"
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix=suffix) as (
        executor,
        session_factory,
        ids,
        _,
    ):
        request_id = await _open_human_request(executor, ids, due_at=due_at)
        if answer_wins:
            async with session_factory() as session:
                await resolve_human_request(
                    cast(AsyncSession, session),
                    task_id=ids.task_id,
                    request_id=request_id,
                    request=HumanRequestResolveRequest(item_responses={"direction": "a"}),
                    runtime_effect_publisher=publisher,
                )
            async with session_factory() as session:
                timeout_won = await expire_human_request(
                    cast(AsyncSession, session),
                    signal=HumanRequestDue(request_id, due_at),
                    runtime_effect_publisher=publisher,
                    now=due_at + timedelta(seconds=1),
                )
            assert timeout_won is False
        else:
            async with session_factory() as session:
                timeout_won = await expire_human_request(
                    cast(AsyncSession, session),
                    signal=HumanRequestDue(request_id, due_at),
                    runtime_effect_publisher=publisher,
                    now=due_at + timedelta(seconds=1),
                )
            assert timeout_won is True
            async with session_factory() as session:
                with pytest.raises(RuntimeOperationError):
                    await resolve_human_request(
                        cast(AsyncSession, session),
                        task_id=ids.task_id,
                        request_id=request_id,
                        request=HumanRequestResolveRequest(item_responses={"direction": "a"}),
                        runtime_effect_publisher=publisher,
                    )

        async with session_factory() as session:
            source = await session.get(HumanRequestModel, request_id)
            events = list(
                await session.scalars(
                    select(TaskEventModel).where(
                        TaskEventModel.task_id == ids.task_id,
                        TaskEventModel.event_type.in_(
                            ("human_request_resolved", "human_request_timed_out")
                        ),
                    )
                )
            )

    assert source is not None
    assert source.status == ("resolved" if answer_wins else "timed_out")
    assert len(events) == 1
    assert publisher.signals == (HumanRequestTerminal(request_id),)


async def test_stale_or_early_human_due_signal_is_harmless(tmp_path: Path) -> None:
    due_at = datetime(2030, 1, 1, 12, tzinfo=UTC)
    async with seeded_executor(tmp_path, suffix="human-deadline-stale") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        request_id = await _open_human_request(executor, ids, due_at=due_at)
        async with session_factory() as session:
            mismatched = await expire_human_request(
                cast(AsyncSession, session),
                signal=HumanRequestDue(request_id, due_at + timedelta(seconds=1)),
                now=due_at + timedelta(seconds=2),
            )
        async with session_factory() as session:
            early = await expire_human_request(
                cast(AsyncSession, session),
                signal=HumanRequestDue(request_id, due_at),
                now=due_at - timedelta(seconds=1),
            )
        async with session_factory() as session:
            source = await session.get(HumanRequestModel, request_id)
            wait = await session.get(FlowWaitModel, ids.flow_id)

    assert mismatched is False
    assert early is False
    assert source is not None and source.status == "open"
    assert wait is not None and wait.human_request_id == request_id


async def _open_human_request(
    executor: NodeOperationExecutor,
    ids: RuntimeIds,
    *,
    due_at: datetime | None,
    default_behavior: str | None = None,
) -> str:
    timeout: dict[str, object] = {}
    if due_at is not None:
        timeout["due_at"] = due_at
    if default_behavior is not None:
        timeout["default_behavior"] = default_behavior
    opened = await executor.execute(
        scope=NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        ),
        operation_name="open_human_request",
        arguments={
            "request": {
                "kind": "direction",
                "summary": "Choose one bounded direction.",
                "items": [
                    {
                        "id": "direction",
                        "prompt": "Which direction?",
                        "options": [
                            {"id": "a", "title": "A"},
                            {"id": "b", "title": "B"},
                        ],
                    }
                ],
                "timeout": timeout,
            }
        },
    )
    return cast(str, opened.model_dump()["request_id"])
