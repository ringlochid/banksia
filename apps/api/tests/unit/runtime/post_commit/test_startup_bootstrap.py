from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime

import banksia.runtime.post_commit.bootstrap as bootstrap_module
import banksia.runtime.post_commit.delegation_wave_startup as wave_startup_module
import pytest
from banksia.runtime.post_commit import CapturedRuntimeEffectPublisher
from banksia.runtime.post_commit.bootstrap import audit_startup_runtime_effects
from banksia.runtime.post_commit.router import (
    AsyncSessionContextFactory,
    RuntimeEffectRouter,
)
from banksia.runtime.post_commit.signals import (
    CommandRunCancellationRequested,
    CommandRunPending,
    CommandRunTerminal,
    DelegationWaveSettled,
    DispatchStartDue,
    FlowStartCommitted,
    HumanRequestOpened,
    HumanRequestTerminal,
    ReplanCommitted,
    RuntimeEffectSignal,
    WatchdogDeadlineChanged,
    WaveMemberSettled,
)
from banksia.runtime.startup_audit import StartupAuditPage
from sqlalchemy.ext.asyncio import AsyncSession

type PageReader = Callable[
    [AsyncSessionContextFactory, str | None, int],
    Awaitable[StartupAuditPage[RuntimeEffectSignal, str]],
]


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


async def test_runtime_startup_routes_only_registered_exact_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    due_at = datetime(2030, 1, 1, tzinfo=UTC)
    signals = (
        FlowStartCommitted("flow.alpha"),
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
    readers = (
        (bootstrap_module, "read_flow_start_page"),
        (wave_startup_module, "read_wave_settlement_page"),
        (wave_startup_module, "read_wave_continuation_page"),
        (bootstrap_module, "read_replan_continuation_page"),
        (bootstrap_module, "read_human_deadline_page"),
        (bootstrap_module, "read_human_continuation_page"),
        (bootstrap_module, "read_command_continuation_page"),
        (bootstrap_module, "read_command_pending_page"),
        (bootstrap_module, "read_command_running_page"),
        (bootstrap_module, "read_command_cancellation_page"),
        (bootstrap_module, "read_dispatch_start_page"),
        (bootstrap_module, "read_watchdog_deadline_page"),
    )
    for (reader_module, reader_name), signal in zip(readers, signals, strict=True):
        monkeypatch.setattr(reader_module, reader_name, build_page_reader(signal))

    publisher = CapturedRuntimeEffectPublisher()

    async def publish(signal: RuntimeEffectSignal) -> bool:
        return publisher.publish(signal)

    results = await audit_startup_runtime_effects(
        session_factory=unused_session_context,
        publish=publish,
        routed_signal_types=(
            FlowStartCommitted,
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
    assert results["runnable_flow_start"].routed_count == 1
    assert results["runnable_flow_start"].deferred_count == 0
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
            "runnable_flow_start",
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
    signals = tuple(FlowStartCommitted(f"flow.{index}") for index in range(5))

    async def read_flow_page(
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

    monkeypatch.setattr(bootstrap_module, "read_flow_start_page", read_flow_page)
    empty_readers = (
        (wave_startup_module, "read_wave_settlement_page"),
        (wave_startup_module, "read_wave_continuation_page"),
        (bootstrap_module, "read_replan_continuation_page"),
        (bootstrap_module, "read_human_deadline_page"),
        (bootstrap_module, "read_human_continuation_page"),
        (bootstrap_module, "read_command_continuation_page"),
        (bootstrap_module, "read_command_pending_page"),
        (bootstrap_module, "read_command_running_page"),
        (bootstrap_module, "read_command_cancellation_page"),
        (bootstrap_module, "read_dispatch_start_page"),
        (bootstrap_module, "read_watchdog_deadline_page"),
    )
    for reader_module, reader_name in empty_readers:
        monkeypatch.setattr(reader_module, reader_name, read_empty_page)

    handled: list[FlowStartCommitted] = []
    all_handled = asyncio.Event()

    async def handle(
        session: AsyncSession,
        signal: FlowStartCommitted,
    ) -> None:
        del session
        handled.append(signal)
        if len(handled) == len(signals):
            all_handled.set()

    router = RuntimeEffectRouter(session_factory=session_context, queue_capacity=1)
    router.register(FlowStartCommitted, handle)
    async with router:
        results = await asyncio.wait_for(
            audit_startup_runtime_effects(
                session_factory=session_context,
                publish=router.publish_startup,
                routed_signal_types=(FlowStartCommitted,),
                watchdog_inactivity_timeout_seconds=900,
            ),
            timeout=1,
        )
        await asyncio.wait_for(all_handled.wait(), timeout=1)

    assert handled == list(signals)
    assert results["runnable_flow_start"].routed_count == len(signals)


@asynccontextmanager
async def session_context() -> AsyncIterator[AsyncSession]:
    async with AsyncSession() as session:
        yield session


def unused_session_context() -> AbstractAsyncContextManager[AsyncSession]:
    raise AssertionError("startup pager unexpectedly opened a session")
