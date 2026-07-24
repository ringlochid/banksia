from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AttemptModel,
    AttemptWaitModel,
    DelegationWaveMemberModel,
    DelegationWaveModel,
    DispatchTurnModel,
    TaskModel,
    TeamRevisionMemberModel,
)
from banksia.runtime.delegation import create_wave_member_settled_handler
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    WaveMemberSettled,
)
from banksia.runtime.post_commit.delegation_wave_startup import (
    read_wave_settlement_page,
)
from tests.helpers.disjoint_team_runtime import (
    add_sibling_and_continue_replan,
    continue_replan_for_source,
    create_runtime_opening_dependencies,
    delegate_pair,
    read_current_assignment_lane,
)
from tests.helpers.executor_harness import (
    make_seed_child_terminal,
    seeded_executor,
)


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

        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=branch_lane.dispatch_id,
            ),
            operation_name="add_child",
            arguments={"child": {"title": "Nested responsibility"}},
        )
        branch_successor_id = await continue_replan_for_source(
            session_factory,
            source_dispatch_id=branch_lane.dispatch_id,
            dependencies=dependencies,
        )

        async with session_factory() as session:
            task = await session.get(TaskModel, ids.task_id)
            assert task is not None and task.current_team_revision_id is not None
            current_sibling = await session.scalar(
                select(TeamRevisionMemberModel).where(
                    TeamRevisionMemberModel.task_id == ids.task_id,
                    TeamRevisionMemberModel.team_revision_id == task.current_team_revision_id,
                    TeamRevisionMemberModel.member_id == sibling_id,
                )
            )
        assert current_sibling is not None
        assert current_sibling.team_revision_id != sibling_lane.team_revision_id
        assert current_sibling.member_configuration_id == sibling_lane.member_configuration_id
        assert current_sibling.member_branch_basis_id == sibling_lane.member_branch_basis_id

        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=sibling_lane.dispatch_id,
            ),
            operation_name="add_child",
            arguments={"child": {"title": "Sibling-owned responsibility"}},
        )
        sibling_successor_id = await continue_replan_for_source(
            session_factory,
            source_dispatch_id=sibling_lane.dispatch_id,
            dependencies=dependencies,
        )
        async with session_factory() as session:
            task = await session.get(TaskModel, ids.task_id)
            assert task is not None and task.current_team_revision_id is not None
            replanned_sibling = await session.scalar(
                select(TeamRevisionMemberModel).where(
                    TeamRevisionMemberModel.task_id == ids.task_id,
                    TeamRevisionMemberModel.team_revision_id == task.current_team_revision_id,
                    TeamRevisionMemberModel.member_id == sibling_id,
                )
            )
        assert replanned_sibling is not None
        assert replanned_sibling.team_revision_id != current_sibling.team_revision_id
        assert replanned_sibling.member_branch_basis_id != current_sibling.member_branch_basis_id

        await _checkpoint(
            executor,
            task_id=ids.task_id,
            dispatch_id=sibling_successor_id,
            outcome="retry",
        )
        retry_lane = await read_current_assignment_lane(
            session_factory,
            sibling_lane.assignment_id,
        )
        async with session_factory() as session:
            retry_attempt = await session.get(AttemptModel, retry_lane.attempt_id)
            retry_boundary = await session.scalar(
                select(AcceptedBoundaryModel).where(
                    AcceptedBoundaryModel.source_dispatch_id == sibling_successor_id
                )
            )
            sibling_wave_member = await _wave_member(
                session,
                wave.wave_id,
                sibling_id,
            )
        assert retry_attempt is not None
        assert retry_attempt.retry_of_attempt_id == sibling_lane.attempt_id
        assert retry_lane.assignment_id == sibling_lane.assignment_id
        assert retry_lane.team_revision_id == replanned_sibling.team_revision_id
        assert retry_lane.member_configuration_id == replanned_sibling.member_configuration_id
        assert retry_lane.member_branch_basis_id == replanned_sibling.member_branch_basis_id
        assert retry_boundary is not None and retry_boundary.outcome == "retry"
        assert sibling_wave_member.status == "pending"
        assert sibling_wave_member.terminal_boundary_id is None

        await _checkpoint(
            executor,
            task_id=ids.task_id,
            dispatch_id=retry_lane.dispatch_id,
            outcome="blocked",
        )
        async with session_factory() as session:
            open_wave = await session.get(DelegationWaveModel, wave.wave_id)
            branch_member = await _wave_member(
                session,
                wave.wave_id,
                ids.child_member_id,
            )
            sibling_member = await _wave_member(
                session,
                wave.wave_id,
                sibling_id,
            )
        assert open_wave is not None and open_wave.status == "open"
        assert branch_member.status == "pending"
        assert sibling_member.status == "settled"
        assert sibling_member.terminal_outcome == "blocked"

        await _checkpoint(
            executor,
            task_id=ids.task_id,
            dispatch_id=branch_successor_id,
            outcome="blocked",
        )
        async_factory = cast(
            Callable[[], AbstractAsyncContextManager[AsyncSession]],
            session_factory,
        )
        discovered = await read_wave_settlement_page(
            async_factory,
            cursor=None,
            page_size=10,
        )
        signal = WaveMemberSettled(wave.wave_id)
        assert discovered.sources == (signal,)

        rejecting_publisher = CapturedRuntimeEffectPublisher(should_accept=False)
        recovery_dependencies = create_runtime_opening_dependencies(
            publisher=rejecting_publisher,
        )
        recover = create_wave_member_settled_handler(recovery_dependencies)
        async with session_factory() as session:
            await recover(cast(AsyncSession, session), signal)
        async with session_factory() as session:
            await recover(cast(AsyncSession, session), signal)
            settled_wave = await session.get(DelegationWaveModel, wave.wave_id)
            parent_attempt = await session.get(AttemptModel, ids.root_attempt_id)
            parent_wait = await session.scalar(
                select(AttemptWaitModel).where(AttemptWaitModel.delegation_wave_id == wave.wave_id)
            )
            members = tuple(
                await session.scalars(
                    select(DelegationWaveMemberModel)
                    .where(DelegationWaveMemberModel.delegation_wave_id == wave.wave_id)
                    .order_by(DelegationWaveMemberModel.order_index)
                )
            )
            assert settled_wave is not None
            successor = await session.get(
                DispatchTurnModel,
                settled_wave.successor_dispatch_id,
            )
            successor_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(DispatchTurnModel)
                    .where(DispatchTurnModel.predecessor_dispatch_id == parent_dispatch_id)
                )
                or 0
            )

    assert rejecting_publisher.signals == ()
    assert settled_wave.status == "settled"
    assert settled_wave.successor_dispatch_id is not None
    assert tuple((member.status, member.terminal_outcome) for member in members) == (
        ("settled", "blocked"),
        ("settled", "blocked"),
    )
    assert parent_wait is None
    assert parent_attempt is not None
    assert parent_attempt.current_wait_id is None
    assert parent_attempt.current_dispatch_id == settled_wave.successor_dispatch_id
    assert successor is not None
    assert successor.opened_reason == "delegation_wave"
    assert successor.team_revision_id == replanned_sibling.team_revision_id
    assert successor_count == 1


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
