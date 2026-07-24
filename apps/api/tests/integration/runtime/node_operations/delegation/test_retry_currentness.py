from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentModel,
    AttemptModel,
    DelegationWaveMemberModel,
    DelegationWaveModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
    ReplanTransitionModel,
    TaskModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.contracts import ReplanSuccess
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import CapturedRuntimeEffectPublisher
from banksia.runtime.replan.continuation import continue_committed_replan
from sqlalchemy import select
from tests.helpers.executor_harness import (
    AsyncSessionFactory,
    make_seed_child_terminal,
    seeded_async_executor,
)
from tests.helpers.lineage_seed import RuntimeIds


@dataclass(frozen=True, slots=True)
class _DelegatedLane:
    assignment_id: str
    attempt_id: str
    dispatch_id: str
    team_revision_id: str
    flow_revision_id: str
    flow_node_id: str
    member_configuration_id: str
    member_branch_basis_id: str


@dataclass(frozen=True, slots=True)
class _CurrentRuntimeSelection:
    team_revision_id: str
    flow_revision_id: str
    node: FlowNodeModel


async def test_retry_after_disjoint_sibling_replan_uses_current_runtime_selection(
    tmp_path: Path,
) -> None:
    dependencies = _opening_dependencies()
    async with seeded_async_executor(tmp_path, suffix="wave-retry-currentness") as (
        executor,
        session_factory,
        ids,
        _activity,
    ):
        root_dispatch_id, sibling_id = await _add_sibling_and_continue(
            executor,
            session_factory,
            ids,
            dependencies=dependencies,
        )
        wave_id, lanes = await _delegate_siblings(
            executor,
            session_factory,
            task_id=ids.task_id,
            parent_dispatch_id=root_dispatch_id,
            child_ids=("child", sibling_id),
        )

        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=lanes["child"].dispatch_id,
            ),
            operation_name="add_child",
            arguments={"child": {"title": "Nested responsibility"}},
        )
        current_selection = await _read_current_selection(
            session_factory,
            task_id=ids.task_id,
            flow_id=ids.flow_id,
            member_id=sibling_id,
        )
        retained_lane = lanes[sibling_id]
        assert retained_lane.team_revision_id != current_selection.team_revision_id
        assert retained_lane.flow_revision_id != current_selection.flow_revision_id
        assert retained_lane.flow_node_id != current_selection.node.flow_node_id
        assert (
            retained_lane.member_configuration_id == current_selection.node.member_configuration_id
        )
        assert retained_lane.member_branch_basis_id == current_selection.node.member_branch_basis_id
        assert current_selection.node.current_assignment_id == retained_lane.assignment_id

        await _checkpoint(
            executor,
            task_id=ids.task_id,
            dispatch_id=retained_lane.dispatch_id,
            outcome="retry",
        )
        retry_lane = await _assert_retry_uses_current_selection(
            session_factory,
            wave_id=wave_id,
            original_lane=retained_lane,
            current_selection=current_selection,
        )

        await _checkpoint(
            executor,
            task_id=ids.task_id,
            dispatch_id=retry_lane.dispatch_id,
            outcome="green",
        )
        await _assert_retry_lane_settled_exact_wave_member(
            session_factory,
            wave_id=wave_id,
            assignment_id=retry_lane.assignment_id,
        )


async def _add_sibling_and_continue(
    executor: NodeOperationExecutor,
    session_factory: AsyncSessionFactory,
    ids: RuntimeIds,
    *,
    dependencies: DispatchOpeningDependencies,
) -> tuple[str, str]:
    async with session_factory() as session:
        await make_seed_child_terminal(session, ids)
    added = ReplanSuccess.model_validate(
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="add_child",
            arguments={"child": {"title": "Independent sibling"}},
        )
    )
    sibling_id = added.created_ids[0]
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
    return opened.dispatch_id, sibling_id


async def _delegate_siblings(
    executor: NodeOperationExecutor,
    session_factory: AsyncSessionFactory,
    *,
    task_id: str,
    parent_dispatch_id: str,
    child_ids: tuple[str, str],
) -> tuple[str, dict[str, _DelegatedLane]]:
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
        lanes: dict[str, _DelegatedLane] = {}
        for member in members:
            assignment = await session.get(
                AssignmentModel,
                member.child_assignment_id,
            )
            assert assignment is not None and assignment.current_attempt_id is not None
            attempt = await session.get(AttemptModel, assignment.current_attempt_id)
            assert attempt is not None and attempt.current_dispatch_id is not None
            dispatch = await session.get(DispatchTurnModel, attempt.current_dispatch_id)
            assert dispatch is not None
            lanes[member.child_member_id] = _DelegatedLane(
                assignment_id=assignment.assignment_id,
                attempt_id=attempt.attempt_id,
                dispatch_id=attempt.current_dispatch_id,
                team_revision_id=dispatch.team_revision_id,
                flow_revision_id=dispatch.flow_revision_id,
                flow_node_id=dispatch.flow_node_id,
                member_configuration_id=dispatch.member_configuration_id,
                member_branch_basis_id=dispatch.member_branch_basis_id,
            )
    return wave.delegation_wave_id, lanes


async def _read_current_selection(
    session_factory: AsyncSessionFactory,
    *,
    task_id: str,
    flow_id: str,
    member_id: str,
) -> _CurrentRuntimeSelection:
    async with session_factory() as session:
        task = await session.get(TaskModel, task_id)
        flow = await session.get(FlowModel, flow_id)
        assert task is not None and task.current_team_revision_id is not None
        assert flow is not None and flow.active_flow_revision_id is not None
        node = await session.scalar(
            select(FlowNodeModel).where(
                FlowNodeModel.task_id == task_id,
                FlowNodeModel.flow_id == flow_id,
                FlowNodeModel.flow_revision_id == flow.active_flow_revision_id,
                FlowNodeModel.team_revision_id == task.current_team_revision_id,
                FlowNodeModel.member_id == member_id,
            )
        )
        assert node is not None
        return _CurrentRuntimeSelection(
            team_revision_id=task.current_team_revision_id,
            flow_revision_id=flow.active_flow_revision_id,
            node=node,
        )


async def _assert_retry_uses_current_selection(
    session_factory: AsyncSessionFactory,
    *,
    wave_id: str,
    original_lane: _DelegatedLane,
    current_selection: _CurrentRuntimeSelection,
) -> _DelegatedLane:
    async with session_factory() as session:
        assignment = await session.get(AssignmentModel, original_lane.assignment_id)
        assert assignment is not None and assignment.current_attempt_id is not None
        retry_attempt = await session.get(AttemptModel, assignment.current_attempt_id)
        assert retry_attempt is not None and retry_attempt.current_dispatch_id is not None
        retry_dispatch = await session.get(
            DispatchTurnModel,
            retry_attempt.current_dispatch_id,
        )
        wave_member = await session.scalar(
            select(DelegationWaveMemberModel).where(
                DelegationWaveMemberModel.delegation_wave_id == wave_id,
                DelegationWaveMemberModel.child_assignment_id == original_lane.assignment_id,
            )
        )
        retry_boundary = await session.scalar(
            select(AcceptedBoundaryModel).where(
                AcceptedBoundaryModel.source_dispatch_id == original_lane.dispatch_id
            )
        )

    assert retry_attempt.retry_of_attempt_id == original_lane.attempt_id
    assert retry_dispatch is not None
    assert retry_dispatch.assignment_id == original_lane.assignment_id
    assert retry_dispatch.team_revision_id == current_selection.team_revision_id
    assert retry_dispatch.flow_revision_id == current_selection.flow_revision_id
    assert retry_dispatch.flow_node_id == current_selection.node.flow_node_id
    assert retry_dispatch.member_configuration_id == current_selection.node.member_configuration_id
    assert retry_dispatch.member_branch_basis_id == current_selection.node.member_branch_basis_id
    assert wave_member is not None and wave_member.status == "pending"
    assert wave_member.terminal_boundary_id is None
    assert retry_boundary is not None and retry_boundary.outcome == "retry"
    return _DelegatedLane(
        assignment_id=original_lane.assignment_id,
        attempt_id=retry_attempt.attempt_id,
        dispatch_id=retry_dispatch.dispatch_id,
        team_revision_id=retry_dispatch.team_revision_id,
        flow_revision_id=retry_dispatch.flow_revision_id,
        flow_node_id=retry_dispatch.flow_node_id,
        member_configuration_id=retry_dispatch.member_configuration_id,
        member_branch_basis_id=retry_dispatch.member_branch_basis_id,
    )


async def _assert_retry_lane_settled_exact_wave_member(
    session_factory: AsyncSessionFactory,
    *,
    wave_id: str,
    assignment_id: str,
) -> None:
    async with session_factory() as session:
        wave = await session.get(DelegationWaveModel, wave_id)
        wave_member = await session.scalar(
            select(DelegationWaveMemberModel).where(
                DelegationWaveMemberModel.delegation_wave_id == wave_id,
                DelegationWaveMemberModel.child_assignment_id == assignment_id,
            )
        )
        assert wave is not None and wave.status == "open"
        assert wave_member is not None
        assert wave_member.status == "settled"
        assert wave_member.terminal_outcome == "green"
        assert wave_member.terminal_boundary_id is not None


async def _checkpoint(
    executor: NodeOperationExecutor,
    *,
    task_id: str,
    dispatch_id: str,
    outcome: str,
) -> None:
    await executor.execute(
        scope=NodeOperationScope(task_id=task_id, dispatch_id=dispatch_id),
        operation_name="checkpoint",
        arguments={
            "summary": f"The contribution returned {outcome}.",
            "outcome": outcome,
        },
    )


def _opening_dependencies() -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds=(ProviderKind.CODEX,),
        post_commit_publisher=CapturedRuntimeEffectPublisher(),
    )
