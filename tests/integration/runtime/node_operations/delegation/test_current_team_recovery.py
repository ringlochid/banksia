from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.persistence.models import (
    AcceptedBoundaryModel,
    AttemptModel,
    AttemptWaitModel,
    DelegationWaveMemberModel,
    DelegationWaveModel,
    DispatchTurnModel,
    TaskModel,
    TeamRevisionMemberModel,
)
from oh_my_subagents.runtime.delegation import create_wave_member_settled_handler
from oh_my_subagents.runtime.dispatch.preparation import DispatchOpeningDependencies
from oh_my_subagents.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from oh_my_subagents.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    WaveMemberSettled,
)
from oh_my_subagents.runtime.post_commit.delegation_wave_startup import (
    read_wave_settlement_page,
)
from tests.helpers.disjoint_team_runtime import (
    RuntimeLane,
    add_sibling_and_continue_replan,
    continue_replan_for_source,
    create_runtime_opening_dependencies,
    delegate_pair,
    read_current_assignment_lane,
)
from tests.helpers.executor_harness import (
    SessionFactory,
    make_seed_child_terminal,
    seeded_executor,
)
from tests.helpers.lineage_seed import RuntimeIds


@dataclass(frozen=True, slots=True)
class _ReplanObservation:
    successor_dispatch_id: str
    team_revision_id: str
    configuration_id: str
    branch_basis_id: str


@dataclass(frozen=True, slots=True)
class _RetryObservation:
    lane: RuntimeLane
    retry_of_attempt_id: str | None
    boundary_outcome: str | None
    wave_member_status: str
    wave_member_boundary_id: str | None


@dataclass(frozen=True, slots=True)
class _OpenWaveObservation:
    wave_status: str
    branch_status: str
    sibling_status: str
    sibling_outcome: str | None


@dataclass(frozen=True, slots=True)
class _RecoveryObservation:
    rejected_hint_count: int
    wave_status: str
    successor_dispatch_id: str | None
    member_outcomes: tuple[tuple[str, str | None], ...]
    parent_wait_exists: bool
    parent_current_wait_id: str | None
    parent_current_dispatch_id: str | None
    successor_reason: str | None
    successor_team_revision_id: str | None
    successor_count: int


async def test_disjoint_replan_retry_and_rejected_hint_recover_one_wave_successor(
    tmp_path: Path,
) -> None:
    dependencies = create_runtime_opening_dependencies()
    async with seeded_executor(tmp_path, suffix="wave-current-team-recovery") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        async with session_factory() as session:
            await make_seed_child_terminal(session, ids)
        sibling_id, parent_dispatch_id = await add_sibling_and_continue_replan(
            executor,
            session_factory,
            ids,
            dependencies=dependencies,
        )
        wave = await delegate_pair(
            executor,
            session_factory,
            task_id=ids.task_id,
            parent_dispatch_id=parent_dispatch_id,
            child_ids=(ids.child_member_id, sibling_id),
        )
        branch_lane = wave.lanes[ids.child_member_id]
        sibling_lane = wave.lanes[sibling_id]
        branch = await _replan_branch_and_observe_retained_sibling(
            executor,
            session_factory,
            ids,
            sibling_id=sibling_id,
            branch_lane=branch_lane,
            sibling_lane=sibling_lane,
            dependencies=dependencies,
        )
        sibling = await _replan_sibling_and_observe_changed_basis(
            executor,
            session_factory,
            ids,
            sibling_id=sibling_id,
            sibling_lane=sibling_lane,
            previous=branch,
            dependencies=dependencies,
        )
        retry = await _retry_sibling_and_observe_lineage(
            executor,
            session_factory,
            ids,
            wave_id=wave.wave_id,
            sibling_id=sibling_id,
            sibling_lane=sibling_lane,
            source_dispatch_id=sibling.successor_dispatch_id,
        )
        _assert_retry_matches_replanned_sibling(retry, sibling_lane, sibling)
        open_wave = await _settle_sibling_and_observe_open_wave(
            executor,
            session_factory,
            ids,
            wave_id=wave.wave_id,
            branch_member_id=ids.child_member_id,
            sibling_id=sibling_id,
            retry_dispatch_id=retry.lane.dispatch_id,
        )
        _assert_wave_remains_open_for_branch(open_wave)
        await _checkpoint(
            executor,
            task_id=ids.task_id,
            dispatch_id=branch.successor_dispatch_id,
            outcome="blocked",
        )
        recovery = await _recover_rejected_hint_and_observe_successor(
            session_factory,
            ids,
            wave_id=wave.wave_id,
            parent_dispatch_id=parent_dispatch_id,
        )
    _assert_recovery_opened_one_current_team_successor(recovery, sibling)


def _assert_retry_matches_replanned_sibling(
    retry: _RetryObservation,
    previous_lane: RuntimeLane,
    replanned: _ReplanObservation,
) -> None:
    assert retry.retry_of_attempt_id == previous_lane.attempt_id
    assert retry.lane.assignment_id == previous_lane.assignment_id
    assert retry.lane.team_revision_id == replanned.team_revision_id
    assert retry.lane.member_configuration_id == replanned.configuration_id
    assert retry.lane.member_branch_basis_id == replanned.branch_basis_id
    assert retry.boundary_outcome == "retry"
    assert retry.wave_member_status == "pending"
    assert retry.wave_member_boundary_id is None


def _assert_wave_remains_open_for_branch(observed: _OpenWaveObservation) -> None:
    assert observed.wave_status == "open"
    assert observed.branch_status == "pending"
    assert observed.sibling_status == "settled"
    assert observed.sibling_outcome == "blocked"


def _assert_recovery_opened_one_current_team_successor(
    observed: _RecoveryObservation,
    replanned: _ReplanObservation,
) -> None:
    assert observed.rejected_hint_count == 0
    assert observed.wave_status == "settled"
    assert observed.successor_dispatch_id is not None
    assert observed.member_outcomes == (
        ("settled", "blocked"),
        ("settled", "blocked"),
    )
    assert not observed.parent_wait_exists
    assert observed.parent_current_wait_id is None
    assert observed.parent_current_dispatch_id == observed.successor_dispatch_id
    assert observed.successor_reason == "delegation_wave"
    assert observed.successor_team_revision_id == replanned.team_revision_id
    assert observed.successor_count == 1


async def _replan_branch_and_observe_retained_sibling(
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    ids: RuntimeIds,
    *,
    sibling_id: str,
    branch_lane: RuntimeLane,
    sibling_lane: RuntimeLane,
    dependencies: DispatchOpeningDependencies,
) -> _ReplanObservation:
    await executor.execute(
        scope=NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=branch_lane.dispatch_id,
        ),
        operation_name="add_child",
        arguments={"child": {"title": "Nested responsibility"}},
    )
    successor_dispatch_id = await continue_replan_for_source(
        session_factory,
        source_dispatch_id=branch_lane.dispatch_id,
        dependencies=dependencies,
    )
    current_sibling = await _current_member_selection(
        session_factory,
        ids,
        sibling_id,
    )
    assert current_sibling.team_revision_id != sibling_lane.team_revision_id
    assert current_sibling.member_configuration_id == sibling_lane.member_configuration_id
    assert current_sibling.member_branch_basis_id == sibling_lane.member_branch_basis_id
    return _ReplanObservation(
        successor_dispatch_id=successor_dispatch_id,
        team_revision_id=current_sibling.team_revision_id,
        configuration_id=current_sibling.member_configuration_id,
        branch_basis_id=current_sibling.member_branch_basis_id,
    )


async def _replan_sibling_and_observe_changed_basis(
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    ids: RuntimeIds,
    *,
    sibling_id: str,
    sibling_lane: RuntimeLane,
    previous: _ReplanObservation,
    dependencies: DispatchOpeningDependencies,
) -> _ReplanObservation:
    await executor.execute(
        scope=NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=sibling_lane.dispatch_id,
        ),
        operation_name="add_child",
        arguments={"child": {"title": "Sibling-owned responsibility"}},
    )
    successor_dispatch_id = await continue_replan_for_source(
        session_factory,
        source_dispatch_id=sibling_lane.dispatch_id,
        dependencies=dependencies,
    )
    replanned = await _current_member_selection(session_factory, ids, sibling_id)
    assert replanned.team_revision_id != previous.team_revision_id
    assert replanned.member_branch_basis_id != previous.branch_basis_id
    return _ReplanObservation(
        successor_dispatch_id=successor_dispatch_id,
        team_revision_id=replanned.team_revision_id,
        configuration_id=replanned.member_configuration_id,
        branch_basis_id=replanned.member_branch_basis_id,
    )


async def _current_member_selection(
    session_factory: SessionFactory,
    ids: RuntimeIds,
    member_id: str,
) -> TeamRevisionMemberModel:
    async with session_factory() as session:
        task = await session.get(TaskModel, ids.task_id)
        assert task is not None and task.current_team_revision_id is not None
        member = await session.scalar(
            select(TeamRevisionMemberModel).where(
                TeamRevisionMemberModel.task_id == ids.task_id,
                TeamRevisionMemberModel.team_revision_id == task.current_team_revision_id,
                TeamRevisionMemberModel.member_id == member_id,
            )
        )
    assert member is not None
    return cast(TeamRevisionMemberModel, member)


async def _retry_sibling_and_observe_lineage(
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    ids: RuntimeIds,
    *,
    wave_id: str,
    sibling_id: str,
    sibling_lane: RuntimeLane,
    source_dispatch_id: str,
) -> _RetryObservation:
    await _checkpoint(
        executor,
        task_id=ids.task_id,
        dispatch_id=source_dispatch_id,
        outcome="retry",
    )
    retry_lane = await read_current_assignment_lane(
        session_factory,
        sibling_lane.assignment_id,
    )
    async with session_factory() as session:
        attempt = await session.get(AttemptModel, retry_lane.attempt_id)
        boundary = await session.scalar(
            select(AcceptedBoundaryModel).where(
                AcceptedBoundaryModel.source_dispatch_id == source_dispatch_id
            )
        )
        member = await _wave_member(session, wave_id, sibling_id)
    assert attempt is not None
    return _RetryObservation(
        lane=retry_lane,
        retry_of_attempt_id=attempt.retry_of_attempt_id,
        boundary_outcome=boundary.outcome if boundary is not None else None,
        wave_member_status=member.status,
        wave_member_boundary_id=member.terminal_boundary_id,
    )


async def _settle_sibling_and_observe_open_wave(
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    ids: RuntimeIds,
    *,
    wave_id: str,
    branch_member_id: str,
    sibling_id: str,
    retry_dispatch_id: str,
) -> _OpenWaveObservation:
    await _checkpoint(
        executor,
        task_id=ids.task_id,
        dispatch_id=retry_dispatch_id,
        outcome="blocked",
    )
    async with session_factory() as session:
        wave = await session.get(DelegationWaveModel, wave_id)
        branch = await _wave_member(session, wave_id, branch_member_id)
        sibling = await _wave_member(session, wave_id, sibling_id)
    assert wave is not None
    return _OpenWaveObservation(
        wave_status=wave.status,
        branch_status=branch.status,
        sibling_status=sibling.status,
        sibling_outcome=sibling.terminal_outcome,
    )


async def _recover_rejected_hint_and_observe_successor(
    session_factory: SessionFactory,
    ids: RuntimeIds,
    *,
    wave_id: str,
    parent_dispatch_id: str,
) -> _RecoveryObservation:
    async_factory = cast(
        Callable[[], AbstractAsyncContextManager[AsyncSession]],
        session_factory,
    )
    page = await read_wave_settlement_page(async_factory, cursor=None, page_size=10)
    signal = WaveMemberSettled(wave_id)
    assert page.sources == (signal,)
    publisher = CapturedRuntimeEffectPublisher(should_accept=False)
    recover = create_wave_member_settled_handler(
        create_runtime_opening_dependencies(publisher=publisher)
    )
    async with session_factory() as session:
        await recover(cast(AsyncSession, session), signal)
    async with session_factory() as session:
        await recover(cast(AsyncSession, session), signal)
        wave = await session.get(DelegationWaveModel, wave_id)
        parent_attempt = await session.get(AttemptModel, ids.root_attempt_id)
        parent_wait = await session.scalar(
            select(AttemptWaitModel).where(AttemptWaitModel.delegation_wave_id == wave_id)
        )
        members = tuple(
            await session.scalars(
                select(DelegationWaveMemberModel)
                .where(DelegationWaveMemberModel.delegation_wave_id == wave_id)
                .order_by(DelegationWaveMemberModel.order_index)
            )
        )
        assert wave is not None
        successor = await session.get(DispatchTurnModel, wave.successor_dispatch_id)
        successor_count = int(
            await session.scalar(
                select(func.count())
                .select_from(DispatchTurnModel)
                .where(DispatchTurnModel.predecessor_dispatch_id == parent_dispatch_id)
            )
            or 0
        )
    assert parent_attempt is not None
    return _RecoveryObservation(
        rejected_hint_count=len(publisher.signals),
        wave_status=wave.status,
        successor_dispatch_id=wave.successor_dispatch_id,
        member_outcomes=tuple((member.status, member.terminal_outcome) for member in members),
        parent_wait_exists=parent_wait is not None,
        parent_current_wait_id=parent_attempt.current_wait_id,
        parent_current_dispatch_id=parent_attempt.current_dispatch_id,
        successor_reason=successor.opened_reason if successor is not None else None,
        successor_team_revision_id=(successor.team_revision_id if successor is not None else None),
        successor_count=successor_count,
    )


async def _wave_member(
    session: Any,
    wave_id: str,
    member_id: str,
) -> DelegationWaveMemberModel:
    member = await session.scalar(
        select(DelegationWaveMemberModel).where(
            DelegationWaveMemberModel.delegation_wave_id == wave_id,
            DelegationWaveMemberModel.child_member_id == member_id,
        )
    )
    assert member is not None
    return cast(DelegationWaveMemberModel, member)


async def _checkpoint(
    executor: NodeOperationExecutor,
    *,
    task_id: str,
    dispatch_id: str,
    outcome: str,
) -> None:
    await executor.execute(
        scope=NodeOperationScope(
            task_id=task_id,
            dispatch_id=dispatch_id,
        ),
        operation_name="checkpoint",
        arguments={
            "summary": f"The contribution returned {outcome}.",
            "outcome": outcome,
        },
    )
