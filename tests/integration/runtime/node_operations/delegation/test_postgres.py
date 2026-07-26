from __future__ import annotations

from dataclasses import dataclass, replace

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

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
from tests.helpers.executor_harness import make_seed_child_terminal
from tests.helpers.postgres_runtime_race import (
    PostgresRuntimeHarness,
    postgres_runtime_harness,
    run_two_contenders_at_task_update_barrier,
)


@dataclass(frozen=True, slots=True)
class _WaveOwnerIdentity:
    task_id: str
    parent_assignment_id: str
    parent_attempt_id: str
    source_dispatch_id: str
    team_revision_id: str
    parent_member_id: str
    parent_member_configuration_id: str
    parent_member_branch_basis_id: str


@dataclass(frozen=True, slots=True)
class _OpenedPostgresWave:
    wave_id: str
    child_dispatch_id: str
    owner: _WaveOwnerIdentity


async def test_postgresql_wave_join_and_successor_have_one_concurrent_winner() -> None:
    async with postgres_runtime_harness(suffix="delegation-wave-final") as harness:
        opened = await _open_single_member_wave(harness)
        await harness.executor.execute(
            scope=NodeOperationScope(
                task_id=harness.ids.task_id,
                dispatch_id=opened.child_dispatch_id,
            ),
            operation_name="checkpoint",
            arguments={
                "summary": "The concurrent Wave contribution is complete.",
                "outcome": "green",
            },
        )
        continuation_signal = await _run_settlement_contenders(harness, opened.wave_id)
        successor_results = await _run_successor_contenders(
            harness,
            continuation_signal,
        )

        assert sorted(outcome for outcome, _ in successor_results) == [
            "opened",
            "skipped",
        ]
        successor_id = next(
            dispatch_id for outcome, dispatch_id in successor_results if outcome == "opened"
        )
        assert successor_id is not None
        async with harness.session_factory() as session:
            persisted_wave = await session.get(DelegationWaveModel, opened.wave_id)
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


async def test_postgresql_delegation_wave_source_dispatch_is_unique() -> None:
    async with postgres_runtime_harness(suffix="delegation-wave-source-unique") as harness:
        opened = await _open_single_member_wave(harness)
        async with harness.session_factory() as session:
            session.add(
                DelegationWaveModel(
                    delegation_wave_id=f"{opened.wave_id}.duplicate",
                    task_id=opened.owner.task_id,
                    parent_assignment_id=opened.owner.parent_assignment_id,
                    parent_attempt_id=opened.owner.parent_attempt_id,
                    source_dispatch_id=opened.owner.source_dispatch_id,
                    team_revision_id=opened.owner.team_revision_id,
                    parent_member_id=opened.owner.parent_member_id,
                    parent_member_configuration_id=(opened.owner.parent_member_configuration_id),
                    parent_member_branch_basis_id=(opened.owner.parent_member_branch_basis_id),
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


async def _open_single_member_wave(
    harness: PostgresRuntimeHarness,
) -> _OpenedPostgresWave:
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
        assignment = await session.get(AssignmentModel, member.child_assignment_id)
        assert assignment is not None and assignment.current_attempt_id is not None
        attempt = await session.get(AttemptModel, assignment.current_attempt_id)
    assert attempt is not None and attempt.current_dispatch_id is not None
    return _OpenedPostgresWave(
        wave_id=wave.delegation_wave_id,
        child_dispatch_id=attempt.current_dispatch_id,
        owner=_WaveOwnerIdentity(
            task_id=wave.task_id,
            parent_assignment_id=wave.parent_assignment_id,
            parent_attempt_id=wave.parent_attempt_id,
            source_dispatch_id=wave.source_dispatch_id,
            team_revision_id=wave.team_revision_id,
            parent_member_id=wave.parent_member_id,
            parent_member_configuration_id=wave.parent_member_configuration_id,
            parent_member_branch_basis_id=wave.parent_member_branch_basis_id,
        ),
    )


async def _run_settlement_contenders(
    harness: PostgresRuntimeHarness,
    wave_id: str,
) -> DelegationWaveSettled:
    publisher = CapturedRuntimeEffectPublisher()
    dependencies = replace(
        harness.dependencies,
        post_commit_publisher=publisher,
    )
    handler = create_wave_member_settled_handler(dependencies)
    signal = WaveMemberSettled(wave_id)

    async def contend() -> None:
        async with harness.session_factory() as session:
            await handler(session, signal)

    results = await run_two_contenders_at_task_update_barrier(
        harness,
        task_id=harness.ids.task_id,
        contender=contend,
    )
    continuation = DelegationWaveSettled(wave_id)
    assert results == (None, None)
    assert publisher.signals == (continuation,)
    return continuation


async def _run_successor_contenders(
    harness: PostgresRuntimeHarness,
    signal: DelegationWaveSettled,
) -> tuple[tuple[str, str | None], tuple[str, str | None]]:
    async def contend() -> tuple[str, str | None]:
        async with harness.session_factory() as session:
            result = await open_delegation_wave_successor(
                session,
                signal=signal,
                dependencies=harness.dependencies,
            )
            return result.outcome, result.dispatch_id

    return await run_two_contenders_at_task_update_barrier(
        harness,
        task_id=harness.ids.task_id,
        contender=contend,
    )
