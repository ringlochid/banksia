from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from banksia.config import RuntimeSettings
from banksia.persistence.models import (
    AssignmentModel,
    AttemptModel,
    AttemptWaitModel,
    DelegationWaveMemberModel,
    DelegationWaveModel,
    DispatchRequestModel,
    DispatchTurnModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.node_mcp import DispatchMcpBindingRegistry
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    DeadlineScheduler,
    DispatchStartDue,
)
from banksia.runtime.providers import (
    DispatchStartRequest,
    ProviderAdapterRegistry,
    ProviderCheckResult,
    ProviderCheckStatus,
    ProviderStartAccepted,
    ProviderStartError,
    ProviderStartErrorCode,
    ProviderStartFailureKind,
    ProviderStopOutcome,
)
from banksia.runtime.providers.starter import DispatchStarter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import (
    SessionFactory,
    make_seed_child_terminal,
    seeded_executor,
)


@dataclass(frozen=True)
class _WaveLaneSnapshot:
    wave_id: str
    wave_status: str
    wave_successor_dispatch_id: str | None
    member_status: str
    member_terminal_boundary_id: str | None
    assignment_id: str
    assignment_terminal_outcome: str | None
    attempt_id: str
    attempt_status: str
    current_dispatch_id: str | None
    dispatch_id: str
    dispatch_status: str
    provider_start_revision: int
    parent_wait_id: str
    parent_wait_source_dispatch_id: str
    request_text: tuple[str, str]

    @property
    def authority(self) -> tuple[str, ...]:
        return (
            self.wave_id,
            self.assignment_id,
            self.attempt_id,
            self.dispatch_id,
            self.parent_wait_id,
            self.parent_wait_source_dispatch_id,
        )


class _FailOnceAdapter:
    kind = ProviderKind.CODEX

    def __init__(self) -> None:
        self.should_fail = True
        self.requests: list[DispatchStartRequest] = []

    async def start(self, request: DispatchStartRequest) -> ProviderStartAccepted:
        self.requests.append(request)
        if self.should_fail:
            raise ProviderStartError(
                kind=ProviderStartFailureKind.DEFINITE_FAILURE,
                code=ProviderStartErrorCode.CONNECTION,
            )
        return ProviderStartAccepted()

    async def stop(self, dispatch_id: str) -> ProviderStopOutcome:
        del dispatch_id
        return ProviderStopOutcome.STOPPED

    async def read_availability(self) -> ProviderCheckResult:
        return ProviderCheckResult(
            kind=self.kind,
            status=ProviderCheckStatus.AVAILABLE,
            code="test_available",
        )

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        yield


class _RecordingScheduler:
    def __init__(self) -> None:
        self.registered: list[DispatchStartDue] = []

    def register(self, signal: DispatchStartDue) -> bool:
        self.registered.append(signal)
        return True


async def test_child_provider_start_retry_preserves_wave_and_dispatch_authority(
    tmp_path: Path,
) -> None:
    delegate_publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(
        tmp_path,
        suffix="wave-provider-start-retry",
        runtime_effect_publisher=delegate_publisher,
    ) as (executor, session_factory, ids, _activity):
        async with session_factory() as session:
            await make_seed_child_terminal(session, ids)

        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="delegate",
            arguments={
                "assignments": [
                    {
                        "child_id": "child",
                        "prompt": "Complete the provider-start-sensitive contribution.",
                    }
                ]
            },
        )
        start_signal = _only_dispatch_start_signal(delegate_publisher)
        initial = await _read_wave_lane(session_factory, ids.current_dispatch_id)
        adapter = _FailOnceAdapter()
        scheduler = _RecordingScheduler()
        now = [start_signal.due_at]
        starter = _build_starter(
            executor=executor,
            session_factory=session_factory,
            adapter=adapter,
            scheduler=scheduler,
            clock=lambda: now[0],
        )

        await _start_dispatch(session_factory, starter, start_signal)

        failed = await _read_wave_lane(session_factory, ids.current_dispatch_id)
        assert failed.authority == initial.authority
        assert failed.wave_status == "open"
        assert failed.wave_successor_dispatch_id is None
        assert failed.member_status == "pending"
        assert failed.member_terminal_boundary_id is None
        assert failed.assignment_terminal_outcome is None
        assert failed.attempt_status == "running"
        assert failed.current_dispatch_id == initial.dispatch_id
        assert failed.dispatch_status == "starting"
        assert failed.provider_start_revision == start_signal.provider_start_revision + 1
        assert failed.request_text == initial.request_text
        assert len(scheduler.registered) == 1
        retry_signal = scheduler.registered[0]
        assert retry_signal.dispatch_id == initial.dispatch_id

        adapter.should_fail = False
        now[0] = retry_signal.due_at
        await _start_dispatch(session_factory, starter, retry_signal)

        accepted = await _read_wave_lane(session_factory, ids.current_dispatch_id)
        assert accepted.authority == initial.authority
        assert accepted.wave_status == "open"
        assert accepted.wave_successor_dispatch_id is None
        assert accepted.member_status == "pending"
        assert accepted.member_terminal_boundary_id is None
        assert accepted.assignment_terminal_outcome is None
        assert accepted.attempt_status == "running"
        assert accepted.current_dispatch_id == initial.dispatch_id
        assert accepted.dispatch_status == "open"
        assert accepted.provider_start_revision == retry_signal.provider_start_revision
        assert accepted.request_text == initial.request_text
        assert [request.dispatch_id for request in adapter.requests] == [
            initial.dispatch_id,
            initial.dispatch_id,
        ]
        assert {(request.instructions, request.input) for request in adapter.requests} == {
            initial.request_text
        }


def _only_dispatch_start_signal(
    publisher: CapturedRuntimeEffectPublisher,
) -> DispatchStartDue:
    signals = tuple(signal for signal in publisher.signals if isinstance(signal, DispatchStartDue))
    assert len(signals) == 1
    return signals[0]


def _build_starter(
    *,
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    adapter: _FailOnceAdapter,
    scheduler: _RecordingScheduler,
    clock: Callable[[], datetime],
) -> DispatchStarter:
    return DispatchStarter(
        adapters=ProviderAdapterRegistry((adapter,)),
        binding_registry=DispatchMcpBindingRegistry(),
        operation_executor=executor,
        scheduler=cast(DeadlineScheduler, scheduler),
        runtime_effect_publisher=CapturedRuntimeEffectPublisher(),
        runtime_settings=RuntimeSettings(),
        session_factory=lambda: cast(
            AbstractAsyncContextManager[AsyncSession],
            session_factory(),
        ),
        managed_node_mcp_url="http://127.0.0.1:18125/_internal/node/mcp",
        compatibility_node_mcp_url="http://127.0.0.1:18125/node/mcp",
        clock=clock,
    )


async def _start_dispatch(
    session_factory: SessionFactory,
    starter: DispatchStarter,
    signal: DispatchStartDue,
) -> None:
    async with session_factory() as session:
        await starter.schedule_or_start_dispatch(
            cast(AsyncSession, session),
            signal,
        )


async def _read_wave_lane(
    session_factory: SessionFactory,
    source_dispatch_id: str,
) -> _WaveLaneSnapshot:
    async with session_factory() as session:
        wave = await session.scalar(
            select(DelegationWaveModel).where(
                DelegationWaveModel.source_dispatch_id == source_dispatch_id
            )
        )
        assert wave is not None
        member = await session.scalar(
            select(DelegationWaveMemberModel).where(
                DelegationWaveMemberModel.delegation_wave_id == wave.delegation_wave_id
            )
        )
        assert member is not None
        assignment = await session.get(AssignmentModel, member.child_assignment_id)
        assert assignment is not None and assignment.current_attempt_id is not None
        attempt = await session.get(AttemptModel, assignment.current_attempt_id)
        assert attempt is not None and attempt.current_dispatch_id is not None
        dispatch = await session.get(DispatchTurnModel, attempt.current_dispatch_id)
        request = await session.get(DispatchRequestModel, attempt.current_dispatch_id)
        wait = await session.scalar(
            select(AttemptWaitModel).where(
                AttemptWaitModel.delegation_wave_id == wave.delegation_wave_id
            )
        )
        assert dispatch is not None
        assert request is not None
        assert wait is not None
        return _WaveLaneSnapshot(
            wave_id=wave.delegation_wave_id,
            wave_status=wave.status,
            wave_successor_dispatch_id=wave.successor_dispatch_id,
            member_status=member.status,
            member_terminal_boundary_id=member.terminal_boundary_id,
            assignment_id=assignment.assignment_id,
            assignment_terminal_outcome=assignment.terminal_outcome,
            attempt_id=attempt.attempt_id,
            attempt_status=attempt.status,
            current_dispatch_id=attempt.current_dispatch_id,
            dispatch_id=dispatch.dispatch_id,
            dispatch_status=dispatch.status,
            provider_start_revision=dispatch.provider_start_revision,
            parent_wait_id=wait.wait_id,
            parent_wait_source_dispatch_id=wait.source_dispatch_id,
            request_text=(request.instructions, request.input),
        )
