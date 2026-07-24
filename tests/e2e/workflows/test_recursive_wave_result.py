from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import func, select

from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    AssignmentModel,
    AttemptModel,
    AttemptWaitModel,
    DelegationWaveMemberModel,
    DelegationWaveModel,
    DispatchRequestModel,
    DispatchTurnModel,
    ReplanTransitionModel,
    TaskModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.checkpoint.reads import read_task_result
from banksia.runtime.clock import utc_now
from banksia.runtime.contracts import ReplanSuccess
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.contracts.prompt import DelegationWaveSettledTrigger
from banksia.runtime.delegation import (
    open_delegation_wave_successor,
    settle_delegation_wave,
)
from banksia.runtime.delegation.continuation import (
    read_delegation_wave_continuation_basis,
)
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    DelegationWaveSettled,
)
from banksia.runtime.replan.continuation import continue_committed_replan
from tests.helpers.executor_harness import (
    AsyncSessionFactory,
    make_seed_child_terminal,
    seeded_async_executor,
)
from tests.helpers.lineage_seed import RuntimeIds


@dataclass(frozen=True, slots=True)
class _OpenedWave:
    wave_id: str
    dispatch_ids: dict[str, str]


@dataclass(frozen=True, slots=True)
class _RecursiveWaves:
    members: dict[str, str]
    root: _OpenedWave
    a: _OpenedWave
    b: _OpenedWave
    e: _OpenedWave


async def test_recursive_parallel_waves_fan_in_once_at_each_local_join(
    tmp_path: Path,
) -> None:
    dependencies = _opening_dependencies()
    async with seeded_async_executor(tmp_path, suffix="wave-recursive-fan-in") as (
        executor,
        session_factory,
        ids,
        _activity,
    ):
        async with session_factory() as session:
            await make_seed_child_terminal(session, ids)

        waves = await _open_recursive_waves(
            executor,
            session_factory,
            ids,
            dependencies=dependencies,
        )
        await _record_out_of_order_leaf_returns(
            executor,
            session_factory,
            ids,
            waves,
        )
        await _close_e_and_b_joins(
            executor,
            session_factory,
            ids,
            waves,
            dependencies=dependencies,
        )
        root_continuation = await _close_a_and_root_joins(
            executor,
            session_factory,
            ids,
            waves,
            dependencies=dependencies,
        )
        await _complete_root_and_assert_result(
            executor,
            session_factory,
            ids,
            root_continuation,
        )


async def _open_recursive_waves(
    executor: NodeOperationExecutor,
    session_factory: AsyncSessionFactory,
    ids: RuntimeIds,
    *,
    dependencies: DispatchOpeningDependencies,
) -> _RecursiveWaves:
    root_dispatch, members = await _add_recursive_team(
        executor,
        session_factory,
        ids,
        dependencies=dependencies,
    )
    root_wave = await _delegate(
        executor,
        session_factory,
        task_id=ids.task_id,
        parent_dispatch_id=root_dispatch,
        children=((members["A"], "A"), ("child", "existing root child")),
    )
    a_dispatch = root_wave.dispatch_ids[members["A"]]
    with pytest.raises(RuntimeOperationError) as indirect:
        await executor.execute(
            scope=NodeOperationScope(task_id=ids.task_id, dispatch_id=a_dispatch),
            operation_name="delegate",
            arguments={
                "assignments": [
                    {
                        "child_id": members["E"],
                        "prompt": "This indirect ownership must be rejected.",
                    }
                ]
            },
        )
    assert indirect.value.code == OperationFailureCode.ILLEGAL_TARGET_RELATION

    a_wave = await _delegate(
        executor,
        session_factory,
        task_id=ids.task_id,
        parent_dispatch_id=a_dispatch,
        children=tuple((members[title], title) for title in ("B", "C", "D")),
    )
    b_wave = await _delegate(
        executor,
        session_factory,
        task_id=ids.task_id,
        parent_dispatch_id=a_wave.dispatch_ids[members["B"]],
        children=tuple((members[title], title) for title in ("E", "F")),
    )
    e_wave = await _delegate(
        executor,
        session_factory,
        task_id=ids.task_id,
        parent_dispatch_id=b_wave.dispatch_ids[members["E"]],
        children=tuple((members[title], title) for title in ("G", "H")),
    )
    return _RecursiveWaves(members, root_wave, a_wave, b_wave, e_wave)


async def _record_out_of_order_leaf_returns(
    executor: NodeOperationExecutor,
    session_factory: AsyncSessionFactory,
    ids: RuntimeIds,
    waves: _RecursiveWaves,
) -> None:
    returns = (
        (waves.root.dispatch_ids["child"], "The existing root child completed."),
        (
            waves.b.dispatch_ids[waves.members["F"]],
            "F completed its leaf contribution.",
        ),
        (
            waves.a.dispatch_ids[waves.members["C"]],
            "C completed its leaf contribution.",
        ),
        (
            waves.e.dispatch_ids[waves.members["G"]],
            "G completed its leaf contribution.",
        ),
    )
    for dispatch_id, summary in returns:
        await _checkpoint(
            executor,
            task_id=ids.task_id,
            dispatch_id=dispatch_id,
            summary=summary,
        )

    for wave, statuses in (
        (waves.e, ("settled", "pending")),
        (waves.b, ("pending", "settled")),
        (waves.a, ("pending", "settled", "pending")),
        (waves.root, ("pending", "settled")),
    ):
        await _assert_incomplete_wave(
            session_factory,
            wave.wave_id,
            expected_member_statuses=statuses,
        )


async def _close_e_and_b_joins(
    executor: NodeOperationExecutor,
    session_factory: AsyncSessionFactory,
    ids: RuntimeIds,
    waves: _RecursiveWaves,
    *,
    dependencies: DispatchOpeningDependencies,
) -> None:
    await _checkpoint(
        executor,
        task_id=ids.task_id,
        dispatch_id=waves.e.dispatch_ids[waves.members["H"]],
        summary="H completed its leaf contribution.",
    )
    e_continuation = await _settle_and_open_wave(
        session_factory,
        waves.e.wave_id,
        dependencies=dependencies,
        expected_results=(
            (waves.members["G"], "G completed its leaf contribution."),
            (waves.members["H"], "H completed its leaf contribution."),
        ),
    )
    await _checkpoint(
        executor,
        task_id=ids.task_id,
        dispatch_id=e_continuation,
        summary="E integrated G and H.",
    )

    b_continuation = await _settle_and_open_wave(
        session_factory,
        waves.b.wave_id,
        dependencies=dependencies,
        expected_results=(
            (waves.members["E"], "E integrated G and H."),
            (waves.members["F"], "F completed its leaf contribution."),
        ),
    )
    await _checkpoint(
        executor,
        task_id=ids.task_id,
        dispatch_id=b_continuation,
        summary="B integrated E and F.",
    )
    await _assert_incomplete_wave(
        session_factory,
        waves.a.wave_id,
        expected_member_statuses=("settled", "settled", "pending"),
    )


async def _close_a_and_root_joins(
    executor: NodeOperationExecutor,
    session_factory: AsyncSessionFactory,
    ids: RuntimeIds,
    waves: _RecursiveWaves,
    *,
    dependencies: DispatchOpeningDependencies,
) -> str:
    await _checkpoint(
        executor,
        task_id=ids.task_id,
        dispatch_id=waves.a.dispatch_ids[waves.members["D"]],
        summary="D completed its leaf contribution.",
    )
    a_continuation = await _settle_and_open_wave(
        session_factory,
        waves.a.wave_id,
        dependencies=dependencies,
        expected_results=(
            (waves.members["B"], "B integrated E and F."),
            (waves.members["C"], "C completed its leaf contribution."),
            (waves.members["D"], "D completed its leaf contribution."),
        ),
    )
    await _checkpoint(
        executor,
        task_id=ids.task_id,
        dispatch_id=a_continuation,
        summary="A integrated B, C, and D.",
    )
    return await _settle_and_open_wave(
        session_factory,
        waves.root.wave_id,
        dependencies=dependencies,
        expected_results=(
            (waves.members["A"], "A integrated B, C, and D."),
            ("child", "The existing root child completed."),
        ),
    )


async def _complete_root_and_assert_result(
    executor: NodeOperationExecutor,
    session_factory: AsyncSessionFactory,
    ids: RuntimeIds,
    root_continuation: str,
) -> None:
    response = await _checkpoint(
        executor,
        task_id=ids.task_id,
        dispatch_id=root_continuation,
        summary="The root integrated the complete recursive team result.",
    )
    assert response["terminal"] is True
    assert response["must_stop"] is True

    async with session_factory() as session:
        task = await session.get(TaskModel, ids.task_id)
        root_assignment = await session.get(AssignmentModel, ids.root_assignment_id)
        result = await read_task_result(session, task_id=ids.task_id)
        open_waves = await session.scalar(
            select(func.count())
            .select_from(DelegationWaveModel)
            .where(DelegationWaveModel.status == "open")
        )
        live_waits = await session.scalar(select(func.count()).select_from(AttemptWaitModel))

    assert task is not None and task.result_boundary_id is not None
    assert root_assignment is not None and root_assignment.terminal_outcome == "green"
    assert result is not None
    assert result.outcome == "green"
    assert result.summary == "The root integrated the complete recursive team result."
    assert open_waves == 0
    assert live_waits == 0


async def _add_recursive_team(
    executor: NodeOperationExecutor,
    session_factory: AsyncSessionFactory,
    ids: RuntimeIds,
    *,
    dependencies: DispatchOpeningDependencies,
) -> tuple[str, dict[str, str]]:
    added = ReplanSuccess.model_validate(
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="add_child",
            arguments={
                "child": {
                    "title": "A",
                    "children": [
                        {
                            "title": "B",
                            "children": [
                                {
                                    "title": "E",
                                    "children": [{"title": "G"}, {"title": "H"}],
                                },
                                {"title": "F"},
                            ],
                        },
                        {"title": "C"},
                        {"title": "D"},
                    ],
                }
            },
        )
    )
    async with session_factory() as session:
        transition = await session.scalar(
            select(ReplanTransitionModel).where(
                ReplanTransitionModel.source_dispatch_id == ids.current_dispatch_id
            )
        )
        assert transition is not None
        opened = await continue_committed_replan(
            session,
            transition_id=transition.replan_transition_id,
            dependencies=dependencies,
        )
    assert opened.outcome == "opened"
    assert opened.dispatch_id is not None
    return opened.dispatch_id, dict(
        zip(
            ("A", "B", "E", "G", "H", "F", "C", "D"),
            added.created_ids,
            strict=True,
        )
    )


async def _delegate(
    executor: NodeOperationExecutor,
    session_factory: AsyncSessionFactory,
    *,
    task_id: str,
    parent_dispatch_id: str,
    children: tuple[tuple[str, str], ...],
) -> _OpenedWave:
    await executor.execute(
        scope=NodeOperationScope(
            task_id=task_id,
            dispatch_id=parent_dispatch_id,
        ),
        operation_name="delegate",
        arguments={
            "assignments": [
                {
                    "child_id": child_id,
                    "prompt": f"Complete the {label} contribution.",
                }
                for child_id, label in children
            ]
        },
    )
    async with session_factory() as session:
        wave = await session.scalar(
            select(DelegationWaveModel).where(
                DelegationWaveModel.source_dispatch_id == parent_dispatch_id
            )
        )
        assert wave is not None
        members = tuple(
            await session.scalars(
                select(DelegationWaveMemberModel)
                .where(DelegationWaveMemberModel.delegation_wave_id == wave.delegation_wave_id)
                .order_by(DelegationWaveMemberModel.order_index)
            )
        )
        dispatch_ids = {
            member.child_member_id: await _current_assignment_dispatch(
                session_factory,
                member.child_assignment_id,
            )
            for member in members
        }
    return _OpenedWave(wave.delegation_wave_id, dispatch_ids)


async def _checkpoint(
    executor: NodeOperationExecutor,
    *,
    task_id: str,
    dispatch_id: str,
    summary: str,
) -> dict[str, object]:
    response = await executor.execute(
        scope=NodeOperationScope(task_id=task_id, dispatch_id=dispatch_id),
        operation_name="checkpoint",
        arguments={"summary": summary, "outcome": "green"},
    )
    return response.model_dump()


async def _assert_incomplete_wave(
    session_factory: AsyncSessionFactory,
    wave_id: str,
    *,
    expected_member_statuses: tuple[str, ...],
) -> None:
    async with session_factory() as session:
        assert not await settle_delegation_wave(
            session,
            delegation_wave_id=wave_id,
            settled_at=utc_now(),
        )
    async with session_factory() as session:
        wave = await session.get(DelegationWaveModel, wave_id)
        members = tuple(
            await session.scalars(
                select(DelegationWaveMemberModel)
                .where(DelegationWaveMemberModel.delegation_wave_id == wave_id)
                .order_by(DelegationWaveMemberModel.order_index)
            )
        )
        wait = await session.scalar(
            select(AttemptWaitModel).where(AttemptWaitModel.delegation_wave_id == wave_id)
        )

    assert wave is not None and wave.status == "open"
    assert wave.successor_dispatch_id is None
    assert tuple(member.status for member in members) == expected_member_statuses
    assert wait is not None


async def _settle_and_open_wave(
    session_factory: AsyncSessionFactory,
    wave_id: str,
    *,
    dependencies: DispatchOpeningDependencies,
    expected_results: tuple[tuple[str, str], ...],
) -> str:
    expected_child_ids = tuple(child_id for child_id, _summary in expected_results)
    expected_summaries = tuple(summary for _child_id, summary in expected_results)
    async with session_factory() as session:
        assert await settle_delegation_wave(
            session,
            delegation_wave_id=wave_id,
            settled_at=dependencies.clock(),
        )
    async with session_factory() as session:
        assert not await settle_delegation_wave(
            session,
            delegation_wave_id=wave_id,
            settled_at=dependencies.clock(),
        )
    async with session_factory() as session:
        basis = await read_delegation_wave_continuation_basis(session, wave_id)
    assert basis is not None
    assert isinstance(basis.trigger, DelegationWaveSettledTrigger)
    assert tuple(member.child_id for member in basis.trigger.result.members) == expected_child_ids
    assert (
        tuple(member.checkpoint.summary for member in basis.trigger.result.members)
        == expected_summaries
    )

    signal = DelegationWaveSettled(wave_id)
    async with session_factory() as session:
        opened = await open_delegation_wave_successor(
            session,
            signal=signal,
            dependencies=dependencies,
        )
    assert opened.outcome == "opened"
    assert opened.dispatch_id is not None
    async with session_factory() as session:
        duplicate = await open_delegation_wave_successor(
            session,
            signal=signal,
            dependencies=dependencies,
        )
    assert duplicate.outcome == "skipped"

    async with session_factory() as session:
        wave = await session.get(DelegationWaveModel, wave_id)
        assert wave is not None
        parent_attempt = await session.get(AttemptModel, wave.parent_attempt_id)
        request = await session.get(DispatchRequestModel, opened.dispatch_id)
        successor_count = await session.scalar(
            select(func.count())
            .select_from(DispatchTurnModel)
            .where(
                DispatchTurnModel.assignment_id == wave.parent_assignment_id,
                DispatchTurnModel.attempt_id == wave.parent_attempt_id,
                DispatchTurnModel.predecessor_dispatch_id == wave.source_dispatch_id,
                DispatchTurnModel.opened_reason == "delegation_wave",
            )
        )
        wait = await session.scalar(
            select(AttemptWaitModel).where(AttemptWaitModel.delegation_wave_id == wave_id)
        )

    assert wave.successor_dispatch_id == opened.dispatch_id
    assert parent_attempt is not None
    assert parent_attempt.current_dispatch_id == opened.dispatch_id
    assert parent_attempt.current_wait_id is None
    assert request is not None
    assert tuple(request.input.index(summary) for summary in expected_summaries) == tuple(
        sorted(request.input.index(summary) for summary in expected_summaries)
    )
    assert successor_count == 1
    assert wait is None
    return opened.dispatch_id


async def _current_assignment_dispatch(
    session_factory: AsyncSessionFactory,
    assignment_id: str,
) -> str:
    async with session_factory() as session:
        assignment = await session.get(AssignmentModel, assignment_id)
        assert assignment is not None and assignment.current_attempt_id is not None
        attempt = await session.get(AttemptModel, assignment.current_attempt_id)
        assert attempt is not None and attempt.current_dispatch_id is not None
        return attempt.current_dispatch_id


def _opening_dependencies() -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds=(ProviderKind.CODEX,),
        post_commit_publisher=CapturedRuntimeEffectPublisher(),
    )
