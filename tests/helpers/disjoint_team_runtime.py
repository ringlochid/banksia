from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    AssignmentModel,
    AttemptModel,
    DelegationWaveMemberModel,
    DelegationWaveModel,
    DispatchTurnModel,
    ReplanTransitionModel,
    TaskModel,
    TeamRevisionMemberModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.contracts import ReplanSuccess
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import CapturedRuntimeEffectPublisher
from banksia.runtime.replan.continuation import continue_committed_replan
from tests.helpers.executor_harness import (
    SessionFactory,
    make_seed_child_terminal,
)
from tests.helpers.lineage_seed import RuntimeIds


@dataclass(frozen=True, slots=True)
class RuntimeLane:
    assignment_id: str
    attempt_id: str
    dispatch_id: str
    team_revision_id: str
    member_configuration_id: str
    member_branch_basis_id: str


@dataclass(frozen=True, slots=True)
class DelegationWaveLanes:
    wave_id: str
    lanes: dict[str, RuntimeLane]


async def add_sibling_and_continue_replan(
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    ids: RuntimeIds,
    *,
    dependencies: DispatchOpeningDependencies,
) -> tuple[str, str]:
    result = ReplanSuccess.model_validate(
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="add_child",
            arguments={"child": {"title": "Independent sibling"}},
        )
    )
    opened = await continue_replan_for_source(
        session_factory,
        source_dispatch_id=ids.current_dispatch_id,
        dependencies=dependencies,
    )
    return result.created_ids[0], opened


async def continue_replan_for_source(
    session_factory: SessionFactory,
    *,
    source_dispatch_id: str,
    dependencies: DispatchOpeningDependencies,
) -> str:
    async with session_factory() as session:
        transition = await session.scalar(
            select(ReplanTransitionModel).where(
                ReplanTransitionModel.source_dispatch_id == source_dispatch_id
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
    return opened.dispatch_id


async def delegate_pair(
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    *,
    task_id: str,
    parent_dispatch_id: str,
    child_ids: tuple[str, str],
) -> DelegationWaveLanes:
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
                    "prompt": f"Complete the bounded {child_id} contribution.",
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
                select(DelegationWaveMemberModel).where(
                    DelegationWaveMemberModel.delegation_wave_id == wave.delegation_wave_id
                )
            )
        )
    lanes = {
        member.child_member_id: await read_current_assignment_lane(
            session_factory,
            member.child_assignment_id,
        )
        for member in members
    }
    return DelegationWaveLanes(wave.delegation_wave_id, lanes)


async def read_current_assignment_lane(
    session_factory: SessionFactory,
    assignment_id: str,
) -> RuntimeLane:
    async with session_factory() as session:
        assignment = await session.get(AssignmentModel, assignment_id)
        assert assignment is not None and assignment.current_attempt_id is not None
        attempt = await session.get(AttemptModel, assignment.current_attempt_id)
        assert attempt is not None and attempt.current_dispatch_id is not None
        dispatch = await session.get(
            DispatchTurnModel,
            attempt.current_dispatch_id,
        )
        assert dispatch is not None
    return RuntimeLane(
        assignment_id=assignment.assignment_id,
        attempt_id=attempt.attempt_id,
        dispatch_id=dispatch.dispatch_id,
        team_revision_id=dispatch.team_revision_id,
        member_configuration_id=dispatch.member_configuration_id,
        member_branch_basis_id=dispatch.member_branch_basis_id,
    )


async def open_disjoint_child_lanes(
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    ids: RuntimeIds,
    *,
    dependencies: DispatchOpeningDependencies,
) -> tuple[RuntimeLane, RuntimeLane, str]:
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
    retained_lane = wave.lanes[sibling_id]
    await executor.execute(
        scope=NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=branch_lane.dispatch_id,
        ),
        operation_name="add_child",
        arguments={"child": {"title": "Branch-only responsibility"}},
    )
    await continue_replan_for_source(
        session_factory,
        source_dispatch_id=branch_lane.dispatch_id,
        dependencies=dependencies,
    )
    branch_lane = await read_current_assignment_lane(
        session_factory,
        branch_lane.assignment_id,
    )
    current_team_revision_id = await _assert_retained_lane_is_current(
        session_factory,
        ids=ids,
        retained_member_id=sibling_id,
        retained_lane=retained_lane,
    )
    return branch_lane, retained_lane, current_team_revision_id


async def _assert_retained_lane_is_current(
    session_factory: SessionFactory,
    *,
    ids: RuntimeIds,
    retained_member_id: str,
    retained_lane: RuntimeLane,
) -> str:
    async with session_factory() as session:
        task = await session.get(TaskModel, ids.task_id)
        assert task is not None and task.current_team_revision_id is not None
        retained_selection = await session.scalar(
            select(TeamRevisionMemberModel).where(
                TeamRevisionMemberModel.task_id == ids.task_id,
                TeamRevisionMemberModel.team_revision_id == task.current_team_revision_id,
                TeamRevisionMemberModel.member_id == retained_member_id,
            )
        )
    assert retained_selection is not None
    assert retained_selection.team_revision_id != retained_lane.team_revision_id
    assert retained_selection.member_configuration_id == retained_lane.member_configuration_id
    assert retained_selection.member_branch_basis_id == retained_lane.member_branch_basis_id
    return cast(str, task.current_team_revision_id)


def create_runtime_opening_dependencies(
    *,
    publisher: CapturedRuntimeEffectPublisher | None = None,
) -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds=(ProviderKind.CODEX,),
        post_commit_publisher=publisher or CapturedRuntimeEffectPublisher(),
    )


__all__ = [
    "DelegationWaveLanes",
    "RuntimeLane",
    "add_sibling_and_continue_replan",
    "continue_replan_for_source",
    "create_runtime_opening_dependencies",
    "delegate_pair",
    "open_disjoint_child_lanes",
    "read_current_assignment_lane",
]
