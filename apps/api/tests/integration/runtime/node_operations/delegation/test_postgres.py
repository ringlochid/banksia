from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from banksia.persistence.models import (
    AssignmentModel,
    AttemptModel,
    DelegationWaveMemberModel,
    DelegationWaveModel,
    DispatchTurnModel,
)
from banksia.runtime.delegation import (
    create_wave_member_settled_handler,
    open_delegation_wave_successor,
)
from banksia.runtime.node_operations import NodeOperationScope
from banksia.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    DelegationWaveSettled,
    WaveMemberSettled,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from tests.helpers.executor_harness import make_seed_child_terminal
from tests.helpers.postgres_runtime_race import postgres_runtime_harness


async def test_postgresql_wave_join_and_successor_have_one_concurrent_winner() -> None:
    async with postgres_runtime_harness(suffix="delegation-wave-final") as harness:
        async with harness.session_factory() as session:
            await make_seed_child_terminal(session, harness.ids)

        await harness.executor.execute(
            scope=NodeOperationScope(
                task_id=harness.ids.task_id,
                dispatch_id=harness.ids.current_dispatch_id,
            ),
            operation_name="delegate",
            arguments={
                "assignments": [
                    {
                        "child_id": "child",
                        "prompt": "Complete the final concurrent Wave contribution.",
                    }
                ]
            },
        )
        async with harness.session_factory() as session:
            wave = await session.scalar(
                select(DelegationWaveModel).where(
                    DelegationWaveModel.source_dispatch_id == harness.ids.current_dispatch_id
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
            assert assignment is not None
            assert assignment.current_attempt_id is not None
            attempt = await session.get(
                AttemptModel,
                assignment.current_attempt_id,
            )
            assert attempt is not None
            assert attempt.current_dispatch_id is not None
            child_dispatch_id = attempt.current_dispatch_id
            wave_identity = {
                "task_id": wave.task_id,
                "flow_id": wave.flow_id,
                "parent_assignment_id": wave.parent_assignment_id,
                "parent_attempt_id": wave.parent_attempt_id,
                "source_dispatch_id": wave.source_dispatch_id,
                "flow_revision_id": wave.flow_revision_id,
                "parent_node_key": wave.parent_node_key,
            }

        await harness.executor.execute(
            scope=NodeOperationScope(
                task_id=harness.ids.task_id,
                dispatch_id=child_dispatch_id,
            ),
            operation_name="checkpoint",
            arguments={
                "summary": "The concurrent Wave contribution is complete.",
                "outcome": "green",
            },
        )

        settlement_publisher = CapturedRuntimeEffectPublisher()
        settlement_dependencies = replace(
            harness.dependencies,
            post_commit_publisher=settlement_publisher,
        )
        settlement_handler = create_wave_member_settled_handler(settlement_dependencies)
        member_signal = WaveMemberSettled(wave.delegation_wave_id)

        async def settle_contender() -> None:
            async with harness.session_factory() as session:
                await settlement_handler(session, member_signal)

        await asyncio.gather(settle_contender(), settle_contender())
        continuation_signal = DelegationWaveSettled(wave.delegation_wave_id)
        assert settlement_publisher.signals == (continuation_signal,)

        async def successor_contender() -> tuple[str, str | None]:
            async with harness.session_factory() as session:
                result = await open_delegation_wave_successor(
                    session,
                    signal=continuation_signal,
                    dependencies=harness.dependencies,
                )
                return result.outcome, result.dispatch_id

        successor_results = await asyncio.gather(
            successor_contender(),
            successor_contender(),
        )
        assert sorted(outcome for outcome, _dispatch_id in successor_results) == [
            "opened",
            "skipped",
        ]
        successor_id = next(
            dispatch_id for outcome, dispatch_id in successor_results if outcome == "opened"
        )
        assert successor_id is not None

        async with harness.session_factory() as session:
            persisted_wave = await session.get(
                DelegationWaveModel,
                wave.delegation_wave_id,
            )
            successor_count = await session.scalar(
                select(func.count())
                .select_from(DispatchTurnModel)
                .where(
                    DispatchTurnModel.predecessor_dispatch_id == harness.ids.current_dispatch_id,
                    DispatchTurnModel.opened_reason == "delegation_wave",
                )
            )
        assert persisted_wave is not None
        assert persisted_wave.status == "settled"
        assert persisted_wave.successor_dispatch_id == successor_id
        assert successor_count == 1

        async with harness.session_factory() as session:
            session.add(
                DelegationWaveModel(
                    delegation_wave_id=f"{wave.delegation_wave_id}.duplicate",
                    **wave_identity,
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
            source_wave_count = await session.scalar(
                select(func.count())
                .select_from(DelegationWaveModel)
                .where(DelegationWaveModel.source_dispatch_id == harness.ids.current_dispatch_id)
            )
        assert source_wave_count == 1
