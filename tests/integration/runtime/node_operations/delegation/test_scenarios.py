from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.config import CodexSettings, RuntimeSettings, Settings
from oh_my_subagents.persistence.models import (
    AssignmentModel,
    AttemptModel,
    AttemptWaitModel,
    DelegationWaveMemberModel,
    DelegationWaveModel,
    MemberConfigurationModel,
    ReplanTransitionModel,
    TaskModel,
    TeamRevisionMemberModel,
)
from oh_my_subagents.providers import ProviderKind
from oh_my_subagents.runtime.delegation import (
    open_delegation_wave_successor,
    settle_delegation_wave,
)
from oh_my_subagents.runtime.dispatch.preparation import DispatchOpeningDependencies
from oh_my_subagents.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from oh_my_subagents.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    DelegationWaveSettled,
    DispatchStartDue,
)
from oh_my_subagents.runtime.replan.continuation import continue_committed_replan
from tests.helpers.executor_harness import (
    SessionFactory,
    make_seed_child_terminal,
    seeded_executor,
)
from tests.helpers.lineage_seed import FIXTURE_TIMESTAMP, RuntimeIds


@dataclass(frozen=True, slots=True)
class _OpenedWave:
    wave_id: str
    assignment_ids: dict[str, str]
    dispatch_ids: dict[str, str]


async def test_three_member_wave_joins_retry_blocked_green_in_member_order(
    tmp_path: Path,
) -> None:
    dependencies = _opening_dependencies()
    async with seeded_executor(tmp_path, suffix="wave-three-outcomes") as (
        executor,
        session_factory,
        ids,
        _activity,
    ):
        branch_wave, members, retry_dispatch_id = await _prepare_mixed_outcome_wave(
            executor,
            session_factory,
            ids,
            dependencies=dependencies,
        )

        async with session_factory() as session:
            wave = await session.get(DelegationWaveModel, branch_wave.wave_id)
            parent_wait = await session.scalar(
                select(AttemptWaitModel).where(
                    AttemptWaitModel.delegation_wave_id == branch_wave.wave_id
                )
            )
            outcomes_before_final = tuple(
                (
                    member.child_member_id,
                    member.status,
                    member.terminal_outcome,
                )
                for member in await session.scalars(
                    select(DelegationWaveMemberModel)
                    .where(DelegationWaveMemberModel.delegation_wave_id == branch_wave.wave_id)
                    .order_by(DelegationWaveMemberModel.order_index)
                )
            )
        assert wave is not None and wave.status == "open"
        assert parent_wait is not None
        assert outcomes_before_final == (
            (members["B"], "pending", None),
            (members["C"], "settled", "blocked"),
            (members["D"], "settled", "green"),
        )

        await _checkpoint(
            executor,
            task_id=ids.task_id,
            dispatch_id=retry_dispatch_id,
            outcome="green",
        )
        async with session_factory() as session:
            assert await settle_delegation_wave(
                cast(AsyncSession, session),
                delegation_wave_id=branch_wave.wave_id,
                settled_at=FIXTURE_TIMESTAMP,
            )
        async with session_factory() as session:
            opened = await open_delegation_wave_successor(
                cast(AsyncSession, session),
                signal=DelegationWaveSettled(branch_wave.wave_id),
                dependencies=dependencies,
            )
        assert opened.outcome == "opened"
        assert opened.dispatch_id is not None

        async with session_factory() as session:
            wave = await session.get(DelegationWaveModel, branch_wave.wave_id)
            outcomes = tuple(
                member.terminal_outcome
                for member in await session.scalars(
                    select(DelegationWaveMemberModel)
                    .where(DelegationWaveMemberModel.delegation_wave_id == branch_wave.wave_id)
                    .order_by(DelegationWaveMemberModel.order_index)
                )
            )
        assert wave is not None
        assert wave.successor_dispatch_id == opened.dispatch_id
        assert outcomes == ("green", "blocked", "green")


async def _prepare_mixed_outcome_wave(
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    ids: RuntimeIds,
    *,
    dependencies: DispatchOpeningDependencies,
) -> tuple[_OpenedWave, dict[str, str], str]:
    async with session_factory() as session:
        await make_seed_child_terminal(session, ids)
    root_dispatch, members = await _add_tree(
        executor,
        session_factory,
        ids,
        dependencies=dependencies,
        child={
            "title": "A",
            "children": [{"title": title} for title in ("B", "C", "D")],
        },
    )
    root_wave = await _delegate(
        executor,
        session_factory,
        task_id=ids.task_id,
        parent_dispatch_id=root_dispatch,
        child_ids=(members["A"],),
    )
    branch_wave = await _delegate(
        executor,
        session_factory,
        task_id=ids.task_id,
        parent_dispatch_id=root_wave.dispatch_ids[members["A"]],
        child_ids=tuple(members[title] for title in ("B", "C", "D")),
    )

    await _checkpoint(
        executor,
        task_id=ids.task_id,
        dispatch_id=branch_wave.dispatch_ids[members["B"]],
        outcome="retry",
    )
    retry_dispatch_id = await _current_assignment_dispatch(
        session_factory,
        branch_wave.assignment_ids[members["B"]],
    )
    for title, outcome in (("C", "blocked"), ("D", "green")):
        await _checkpoint(
            executor,
            task_id=ids.task_id,
            dispatch_id=branch_wave.dispatch_ids[members[title]],
            outcome=outcome,
        )
    return branch_wave, members, retry_dispatch_id


async def test_eight_member_wave_is_atomic_at_the_public_limit(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    dependencies = _opening_dependencies()
    async with seeded_executor(
        tmp_path,
        suffix="wave-eight",
        runtime_effect_publisher=publisher,
    ) as (executor, session_factory, ids, _activity):
        async with session_factory() as session:
            await make_seed_child_terminal(session, ids)
        leaf_titles = tuple(f"Leaf {index}" for index in range(8))
        root_dispatch, members = await _add_tree(
            executor,
            session_factory,
            ids,
            dependencies=dependencies,
            child={
                "title": "A",
                "children": [{"title": title} for title in leaf_titles],
            },
        )
        root_wave = await _delegate(
            executor,
            session_factory,
            task_id=ids.task_id,
            parent_dispatch_id=root_dispatch,
            child_ids=(members["A"],),
        )
        leaf_ids = tuple(members[title] for title in leaf_titles)
        leaf_wave = await _delegate(
            executor,
            session_factory,
            task_id=ids.task_id,
            parent_dispatch_id=root_wave.dispatch_ids[members["A"]],
            child_ids=leaf_ids,
        )

        async with session_factory() as session:
            wave = await session.get(DelegationWaveModel, leaf_wave.wave_id)
            wave_members = tuple(
                await session.scalars(
                    select(DelegationWaveMemberModel)
                    .where(DelegationWaveMemberModel.delegation_wave_id == leaf_wave.wave_id)
                    .order_by(DelegationWaveMemberModel.order_index)
                )
            )
            parent_assignment = await session.get(
                AssignmentModel,
                root_wave.assignment_ids[members["A"]],
            )
            parent_attempt = await session.get(
                AttemptModel,
                parent_assignment.current_attempt_id,
            )

        assert wave is not None and wave.status == "open"
        assert tuple(member.child_member_id for member in wave_members) == leaf_ids
        assert len(leaf_wave.dispatch_ids) == 8
        assert parent_assignment is not None
        assert parent_assignment.child_assignments_remaining == 12
        assert parent_attempt is not None
        assert parent_attempt.current_dispatch_id is None
        assert parent_attempt.current_wait_id is not None
        assert sum(isinstance(signal, DispatchStartDue) for signal in publisher.signals) == 9


async def _add_tree(
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    ids: RuntimeIds,
    *,
    dependencies: DispatchOpeningDependencies,
    child: dict[str, object],
) -> tuple[str, dict[str, str]]:
    await executor.execute(
        scope=NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        ),
        operation_name="add_child",
        arguments={"child": child},
    )
    async with session_factory() as session:
        transition = await session.scalar(
            select(ReplanTransitionModel).where(
                ReplanTransitionModel.source_dispatch_id == ids.current_dispatch_id
            )
        )
        assert transition is not None
        opened = await continue_committed_replan(
            cast(AsyncSession, session),
            transition_id=transition.replan_transition_id,
            dependencies=dependencies,
        )
    assert opened.outcome == "opened"
    assert opened.dispatch_id is not None
    return opened.dispatch_id, await _current_member_ids_by_title(
        session_factory,
        ids.task_id,
    )


async def _delegate(
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    *,
    task_id: str,
    parent_dispatch_id: str,
    child_ids: tuple[str, ...],
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
                    "prompt": f"Complete the {child_id} contribution.",
                }
                for child_id in child_ids
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
        assignment_ids = {member.child_member_id: member.child_assignment_id for member in members}
        dispatch_ids = {
            child_id: await _current_assignment_dispatch(
                session_factory,
                assignment_id,
            )
            for child_id, assignment_id in assignment_ids.items()
        }
    return _OpenedWave(wave.delegation_wave_id, assignment_ids, dispatch_ids)


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


async def _current_member_ids_by_title(
    session_factory: SessionFactory,
    task_id: str,
) -> dict[str, str]:
    async with session_factory() as session:
        task = await session.get(TaskModel, task_id)
        assert task is not None and task.current_team_revision_id is not None
        rows = tuple(
            await session.execute(
                select(
                    MemberConfigurationModel.title,
                    TeamRevisionMemberModel.member_id,
                )
                .join(
                    MemberConfigurationModel,
                    (
                        MemberConfigurationModel.member_configuration_id
                        == TeamRevisionMemberModel.member_configuration_id
                    )
                    & (MemberConfigurationModel.member_id == TeamRevisionMemberModel.member_id),
                )
                .where(
                    TeamRevisionMemberModel.task_id == task_id,
                    TeamRevisionMemberModel.team_revision_id == task.current_team_revision_id,
                    MemberConfigurationModel.title.is_not(None),
                )
            )
        )
    return {title: member_id for title, member_id in rows if title is not None}


async def _current_assignment_dispatch(
    session_factory: SessionFactory,
    assignment_id: str,
) -> str:
    async with session_factory() as session:
        assignment = await session.get(AssignmentModel, assignment_id)
        assert assignment is not None and assignment.current_attempt_id is not None
        attempt = await session.get(AttemptModel, assignment.current_attempt_id)
        assert attempt is not None and attempt.current_dispatch_id is not None
        return cast(str, attempt.current_dispatch_id)


def _opening_dependencies() -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds=(ProviderKind.CODEX,),
        post_commit_publisher=CapturedRuntimeEffectPublisher(),
    )
