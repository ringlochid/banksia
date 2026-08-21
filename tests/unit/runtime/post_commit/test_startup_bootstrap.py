from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import oh_my_subagents.runtime.post_commit.delegation_wave_startup as wave_startup_module
import oh_my_subagents.runtime.post_commit.dispatch_startup as dispatch_startup_module
import oh_my_subagents.runtime.post_commit.external_wait_startup as external_wait_startup_module
from oh_my_subagents.runtime.post_commit import CapturedRuntimeEffectPublisher
from oh_my_subagents.runtime.post_commit.bootstrap import audit_startup_runtime_effects
from oh_my_subagents.runtime.post_commit.router import (
    AsyncSessionContextFactory,
    RuntimeEffectRouter,
)
from oh_my_subagents.runtime.post_commit.signals import (
    CommandRunCancellationRequested,
    CommandRunPending,
    CommandRunTerminal,
    DelegationWaveSettled,
    DispatchStartDue,
    HumanRequestOpened,
    HumanRequestTerminal,
    ReplanCommitted,
    RuntimeEffectSignal,
    TaskStartCommitted,
    WatchdogDeadlineChanged,
    WaveMemberSettled,
)
from oh_my_subagents.runtime.startup_audit import StartupAuditPage

type PageReader = Callable[
    [AsyncSessionContextFactory, str | None, int],
    Awaitable[StartupAuditPage[RuntimeEffectSignal, str]],
]

_STARTUP_READER_LOCATIONS = (
    (dispatch_startup_module, "read_task_start_page"),
    (wave_startup_module, "read_wave_settlement_page"),
    (wave_startup_module, "read_wave_continuation_page"),
    (dispatch_startup_module, "read_replan_continuation_page"),
    (external_wait_startup_module, "read_human_deadline_page"),
    (external_wait_startup_module, "read_human_continuation_page"),
    (external_wait_startup_module, "read_command_continuation_page"),
    (external_wait_startup_module, "read_command_pending_page"),
    (external_wait_startup_module, "read_command_running_page"),
    (external_wait_startup_module, "read_command_cancellation_page"),
    (dispatch_startup_module, "read_dispatch_start_page"),
    (dispatch_startup_module, "read_watchdog_deadline_page"),
)


def build_page_reader(signal: RuntimeEffectSignal) -> PageReader:
    async def read_page(
        session_factory: AsyncSessionContextFactory,
        cursor: str | None,
        page_size: int,
        **kwargs: object,
    ) -> StartupAuditPage[RuntimeEffectSignal, str]:
        del session_factory, cursor, page_size, kwargs
        return StartupAuditPage((signal,), None)

    return read_page


def startup_source_signals(due_at: datetime) -> tuple[RuntimeEffectSignal, ...]:
    return (
        TaskStartCommitted("task.alpha"),
        WaveMemberSettled("wave.complete"),
        DelegationWaveSettled("wave.settled"),
        ReplanCommitted("replan.alpha"),
        HumanRequestOpened("human.open"),
        HumanRequestTerminal("human.alpha"),
        CommandRunTerminal("command.alpha"),
        CommandRunPending("command.pending"),
        CommandRunPending("command.running"),
        CommandRunCancellationRequested("command.cancelling", 4),
        DispatchStartDue("dispatch.starting", 3, due_at),
        WatchdogDeadlineChanged("dispatch.open", 5, due_at),
    )


def install_startup_readers(
    monkeypatch: pytest.MonkeyPatch,
    signals: tuple[RuntimeEffectSignal, ...],
) -> None:
    for (reader_module, reader_name), signal in zip(
        _STARTUP_READER_LOCATIONS,
        signals,
        strict=True,
    ):
        monkeypatch.setattr(reader_module, reader_name, build_page_reader(signal))


async def test_runtime_startup_routes_only_registered_exact_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    due_at = datetime(2030, 1, 1, tzinfo=UTC)
    signals = startup_source_signals(due_at)
    install_startup_readers(monkeypatch, signals)

    publisher = CapturedRuntimeEffectPublisher()

    async def publish(signal: RuntimeEffectSignal) -> bool:
        return publisher.publish(signal)

    results = await audit_startup_runtime_effects(
        session_factory=unused_session_context,
        publish=publish,
        routed_signal_types=(
            TaskStartCommitted,
            WaveMemberSettled,
            DelegationWaveSettled,
            ReplanCommitted,
            HumanRequestOpened,
            CommandRunPending,
            CommandRunCancellationRequested,
            WatchdogDeadlineChanged,
        ),
        watchdog_inactivity_timeout_seconds=900,
    )

    assert publisher.signals == (
        signals[0],
        signals[1],
        signals[2],
        signals[3],
        signals[4],
        signals[7],
        signals[8],
        signals[9],
        signals[11],
    )
    assert results["runnable_task_start"].routed_count == 1
    assert results["runnable_task_start"].deferred_count == 0
    assert results["complete_delegation_wave"].routed_count == 1
    assert results["settled_delegation_wave"].routed_count == 1
    assert results["open_human_request"].routed_count == 1
    assert results["open_human_request"].deferred_count == 0
    assert results["committed_replan"].routed_count == 1
    assert results["committed_replan"].deferred_count == 0
    assert all(result.discovered_count == 1 for result in results.values())
    assert all(
        result.deferred_count == 1
        for family_name, result in results.items()
        if family_name
        not in {
            "runnable_task_start",
            "complete_delegation_wave",
            "settled_delegation_wave",
            "committed_replan",
            "open_human_request",
            "pending_command_run",
            "running_command_run",
            "cancellation_requested_command_run",
            "current_open_watchdog",
        }
    )


async def test_runtime_startup_waits_for_router_capacity_without_waiting_for_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signals = tuple(TaskStartCommitted(f"task.{index}") for index in range(5))

    async def read_task_page(
        session_factory: AsyncSessionContextFactory,
        cursor: str | None,
        page_size: int,
    ) -> StartupAuditPage[RuntimeEffectSignal, str]:
        del session_factory, cursor, page_size
        return StartupAuditPage(signals, None)

    async def read_empty_page(
        session_factory: AsyncSessionContextFactory,
        cursor: str | None,
        page_size: int,
        **kwargs: object,
    ) -> StartupAuditPage[RuntimeEffectSignal, str]:
        del session_factory, cursor, page_size, kwargs
        return StartupAuditPage((), None)

    monkeypatch.setattr(
        dispatch_startup_module,
        "read_task_start_page",
        read_task_page,
    )
    for reader_module, reader_name in _STARTUP_READER_LOCATIONS[1:]:
        monkeypatch.setattr(reader_module, reader_name, read_empty_page)

    handled: list[TaskStartCommitted] = []
    all_handled = asyncio.Event()

    async def handle(
        session: AsyncSession,
        signal: TaskStartCommitted,
    ) -> None:
        del session
        handled.append(signal)
        if len(handled) == len(signals):
            all_handled.set()

    router = RuntimeEffectRouter(session_factory=session_context, queue_capacity=1)
    router.register(TaskStartCommitted, handle)
    async with router:
        results = await asyncio.wait_for(
            audit_startup_runtime_effects(
                session_factory=session_context,
                publish=router.publish_startup,
                routed_signal_types=(TaskStartCommitted,),
                watchdog_inactivity_timeout_seconds=900,
            ),
            timeout=1,
        )
        await asyncio.wait_for(all_handled.wait(), timeout=1)

    assert handled == list(signals)
    assert results["runnable_task_start"].routed_count == len(signals)


@asynccontextmanager
async def session_context() -> AsyncIterator[AsyncSession]:
    async with AsyncSession() as session:
        yield session


def unused_session_context() -> AbstractAsyncContextManager[AsyncSession]:
    raise AssertionError("startup pager unexpectedly opened a session")
