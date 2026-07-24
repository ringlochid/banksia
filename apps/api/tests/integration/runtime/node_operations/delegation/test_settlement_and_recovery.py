from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import cast

from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    AssignmentModel,
    AttemptModel,
    AttemptWaitModel,
    DelegationWaveMemberModel,
    DelegationWaveModel,
    DispatchRequestModel,
    DispatchTurnModel,
    FlowNodeModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.clock import utc_now
from banksia.runtime.delegation import (
    create_wave_member_settled_handler,
    open_delegation_wave_successor,
    settle_delegation_wave,
)
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.node_operations import NodeOperationScope
from banksia.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    DelegationWaveSettled,
    WaveMemberSettled,
)
from banksia.runtime.post_commit.delegation_wave_startup import (
    read_wave_continuation_page,
    read_wave_settlement_page,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import make_seed_child_terminal, seeded_executor


async def test_green_checkpoint_joins_wave_and_opens_exact_ordered_parent_continuation(
    tmp_path: Path,
) -> None:
    operation_publisher = CapturedRuntimeEffectPublisher()
    continuation_publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(
        tmp_path,
        suffix="wave-join",
        runtime_effect_publisher=operation_publisher,
    ) as (executor, session_factory, ids, _activity):
        async_session_factory = cast(
            Callable[[], AbstractAsyncContextManager[AsyncSession]],
            session_factory,
        )
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
                        "prompt": "Implement the bounded child contribution.",
                    }
                ]
            },
        )
        async with session_factory() as session:
            wave = await session.scalar(
                select(DelegationWaveModel).where(
                    DelegationWaveModel.source_dispatch_id == ids.current_dispatch_id
                )
            )
            assert wave is not None
            member = await session.scalar(
                select(DelegationWaveMemberModel).where(
                    DelegationWaveMemberModel.delegation_wave_id == wave.delegation_wave_id
                )
            )
            assert member is not None
            child_assignment = await session.get(
                AssignmentModel,
                member.child_assignment_id,
            )
            assert child_assignment is not None
            assert child_assignment.current_attempt_id is not None
            child_attempt = await session.get(
                AttemptModel,
                child_assignment.current_attempt_id,
            )
            assert child_attempt is not None
            assert child_attempt.current_dispatch_id is not None
            child_dispatch = await session.get(
                DispatchTurnModel,
                child_attempt.current_dispatch_id,
            )
            assert child_dispatch is not None
            child_dispatch.status = "open"
            child_dispatch.adapter_started_at = child_dispatch.created_at
            child_dispatch.last_node_activity_at = child_dispatch.created_at
            child_dispatch.next_provider_start_at = None
            child_dispatch.provider_start_retry_kind = None
            child_dispatch.provider_start_last_error_code = None
            await session.commit()

        response = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=child_dispatch.dispatch_id,
            ),
            operation_name="checkpoint",
            arguments={
                "summary": "The delegated contribution is complete.",
                "details": "Implemented and verified the bounded scope.",
                "outcome": "green",
            },
        )
        assert response.model_dump()["terminal"] is True
        assert operation_publisher.signals[-1] == WaveMemberSettled(
            delegation_wave_id=wave.delegation_wave_id
        )

        async with session_factory() as session:
            member = await session.scalar(
                select(DelegationWaveMemberModel).where(
                    DelegationWaveMemberModel.delegation_wave_id == wave.delegation_wave_id
                )
            )
            parent_wait = await session.scalar(
                select(AttemptWaitModel).where(
                    AttemptWaitModel.delegation_wave_id == wave.delegation_wave_id
                )
            )
            assert member is not None and member.status == "settled"
            assert member.terminal_outcome == "green"
            assert member.terminal_boundary_id is not None
            assert parent_wait is not None
            settlement_page = await read_wave_settlement_page(
                async_session_factory,
                None,
                10,
            )
            assert settlement_page.sources == (
                WaveMemberSettled(delegation_wave_id=wave.delegation_wave_id),
            )

            assert await settle_delegation_wave(
                cast(AsyncSession, session),
                delegation_wave_id=wave.delegation_wave_id,
                settled_at=utc_now(),
            )
            continuation_page = await read_wave_continuation_page(
                async_session_factory,
                None,
                10,
            )
            assert continuation_page.sources == (
                DelegationWaveSettled(delegation_wave_id=wave.delegation_wave_id),
            )
        async with session_factory() as session:
            assert not await settle_delegation_wave(
                cast(AsyncSession, session),
                delegation_wave_id=wave.delegation_wave_id,
                settled_at=utc_now(),
            )

        dependencies = DispatchOpeningDependencies.create(
            settings=Settings(
                runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
                codex=CodexSettings(enabled=True),
            ),
            available_adapter_kinds=(ProviderKind.CODEX,),
            post_commit_publisher=continuation_publisher,
        )
        signal = DelegationWaveSettled(delegation_wave_id=wave.delegation_wave_id)
        async with session_factory() as session:
            opened = await open_delegation_wave_successor(
                cast(AsyncSession, session),
                signal=signal,
                dependencies=dependencies,
            )
        assert opened.outcome == "opened"
        assert opened.dispatch_id is not None
        async with session_factory() as session:
            duplicate = await open_delegation_wave_successor(
                cast(AsyncSession, session),
                signal=signal,
                dependencies=dependencies,
            )
        assert duplicate.outcome == "skipped"

        async with session_factory() as session:
            wave = await session.get(DelegationWaveModel, wave.delegation_wave_id)
            parent_attempt = await session.get(AttemptModel, ids.root_attempt_id)
            parent_node = await session.get(FlowNodeModel, ids.root_node_id)
            successor = await session.get(DispatchTurnModel, opened.dispatch_id)
            request = await session.get(DispatchRequestModel, opened.dispatch_id)
            parent_wait = await session.scalar(
                select(AttemptWaitModel).where(
                    AttemptWaitModel.delegation_wave_id == wave.delegation_wave_id
                )
            )

        assert wave is not None and wave.status == "settled"
        assert wave.successor_dispatch_id == opened.dispatch_id
        assert parent_wait is None
        assert parent_attempt is not None
        assert parent_attempt.current_wait_id is None
        assert parent_attempt.current_dispatch_id == opened.dispatch_id
        assert parent_node is not None and parent_node.state == "running"
        assert successor is not None
        assert successor.opened_reason == "delegation_wave"
        assert successor.predecessor_dispatch_id == ids.current_dispatch_id
        assert request is not None
        assert "<kind>delegation_wave_settled</kind>" in request.input
        assert "Implement the bounded child contribution." in request.input
        assert "The delegated contribution is complete." in request.input


async def test_rejected_settlement_hint_opens_successor_in_same_recovery_run(
    tmp_path: Path,
) -> None:
    rejecting_publisher = CapturedRuntimeEffectPublisher(should_accept=False)
    dependencies = DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds=(ProviderKind.CODEX,),
        post_commit_publisher=rejecting_publisher,
    )
    async with seeded_executor(tmp_path, suffix="wave-rejected-hint") as (
        executor,
        session_factory,
        ids,
        _activity,
    ):
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
                        "prompt": "Complete one recovery-sensitive contribution.",
                    }
                ]
            },
        )
        async with session_factory() as session:
            wave = await session.scalar(
                select(DelegationWaveModel).where(
                    DelegationWaveModel.source_dispatch_id == ids.current_dispatch_id
                )
            )
            assert wave is not None
            member = await session.scalar(
                select(DelegationWaveMemberModel).where(
                    DelegationWaveMemberModel.delegation_wave_id == wave.delegation_wave_id
                )
            )
            assert member is not None
            assignment = await session.get(
                AssignmentModel,
                member.child_assignment_id,
            )
            assert assignment is not None and assignment.current_attempt_id is not None
            attempt = await session.get(AttemptModel, assignment.current_attempt_id)
            assert attempt is not None and attempt.current_dispatch_id is not None
            child_dispatch_id = attempt.current_dispatch_id

        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=child_dispatch_id,
            ),
            operation_name="checkpoint",
            arguments={
                "summary": "The recovery-sensitive contribution is complete.",
                "outcome": "green",
            },
        )

        handler = create_wave_member_settled_handler(dependencies)
        signal = WaveMemberSettled(wave.delegation_wave_id)
        async with session_factory() as session:
            await handler(cast(AsyncSession, session), signal)
        async with session_factory() as session:
            await handler(cast(AsyncSession, session), signal)
            persisted_wave = await session.get(
                DelegationWaveModel,
                wave.delegation_wave_id,
            )
            parent_attempt = await session.get(AttemptModel, ids.root_attempt_id)
            assert persisted_wave is not None
            assert parent_attempt is not None
            successor = await session.get(
                DispatchTurnModel,
                persisted_wave.successor_dispatch_id,
            )

        assert rejecting_publisher.signals == ()
        assert persisted_wave.status == "settled"
        assert persisted_wave.successor_dispatch_id is not None
        assert parent_attempt.current_wait_id is None
        assert parent_attempt.current_dispatch_id == persisted_wave.successor_dispatch_id
        assert successor is not None
        assert successor.opened_reason == "delegation_wave"
