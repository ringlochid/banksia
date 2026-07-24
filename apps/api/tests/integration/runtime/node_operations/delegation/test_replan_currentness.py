from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    AssignmentModel,
    AttemptModel,
    DelegationWaveMemberModel,
    DelegationWaveModel,
    DispatchRequestModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
    ReplanTransitionModel,
    TaskModel,
    TeamRevisionMemberModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.clock import utc_now
from banksia.runtime.contracts import ReplanSuccess
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.dispatch.provider_start import (
    accept_provider_start_if_current,
    read_provider_start_candidate,
)
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    DispatchStartDue,
)
from banksia.runtime.post_commit.bootstrap import read_dispatch_start_page
from banksia.runtime.replan.continuation import continue_committed_replan
from sqlalchemy import select
from tests.helpers.executor_harness import (
    AsyncSessionFactory,
    make_seed_child_terminal,
    seeded_async_executor,
)
from tests.helpers.lineage_seed import RuntimeIds


@dataclass(frozen=True, slots=True)
class _WaveLanes:
    wave_id: str
    branch_b_id: str
    branch_c_id: str
    branch_b_request: str
    branch_c_request: str


async def test_unaffected_wave_lane_settles_after_sibling_replan(
    tmp_path: Path,
) -> None:
    dependencies = _opening_dependencies()
    async with seeded_async_executor(tmp_path, suffix="wave-sibling-replan") as (
        executor,
        session_factory,
        ids,
        _activity,
    ):
        async with session_factory() as session:
            await make_seed_child_terminal(session, ids)

        sibling_id, parent_dispatch_id = await _add_sibling_and_continue(
            executor,
            session_factory,
            ids,
            dependencies=dependencies,
        )
        lanes = await _delegate_sibling_wave(
            executor,
            session_factory,
            task_id=ids.task_id,
            parent_dispatch_id=parent_dispatch_id,
            sibling_id=sibling_id,
        )
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=lanes.branch_b_id,
            ),
            operation_name="add_child",
            arguments={"child": {"title": "Nested branch E"}},
        )
        await _accept_unaffected_branch_start(
            session_factory,
            branch_b_id=lanes.branch_b_id,
            branch_c_id=lanes.branch_c_id,
        )

        response = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=lanes.branch_c_id,
            ),
            operation_name="checkpoint",
            arguments={
                "summary": "Unaffected branch C is complete.",
                "outcome": "green",
            },
        )
        assert response.model_dump()["terminal"] is True

        await _assert_unaffected_lane_settled(
            session_factory,
            ids,
            sibling_id=sibling_id,
            lanes=lanes,
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


async def _add_sibling_and_continue(
    executor: NodeOperationExecutor,
    session_factory: AsyncSessionFactory,
    ids: RuntimeIds,
    *,
    dependencies: DispatchOpeningDependencies,
) -> tuple[str, str]:
    added = ReplanSuccess.model_validate(
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="add_child",
            arguments={"child": {"title": "Concurrent sibling"}},
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
    return sibling_id, opened.dispatch_id


async def _delegate_sibling_wave(
    executor: NodeOperationExecutor,
    session_factory: AsyncSessionFactory,
    *,
    task_id: str,
    parent_dispatch_id: str,
    sibling_id: str,
) -> _WaveLanes:
    await executor.execute(
        scope=NodeOperationScope(
            task_id=task_id,
            dispatch_id=parent_dispatch_id,
        ),
        operation_name="delegate",
        arguments={
            "assignments": [
                {"child_id": "child", "prompt": "Own branch B."},
                {"child_id": sibling_id, "prompt": "Own unaffected branch C."},
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
        members = {
            member.child_member_id: member
            for member in await session.scalars(
                select(DelegationWaveMemberModel).where(
                    DelegationWaveMemberModel.delegation_wave_id == wave.delegation_wave_id
                )
            )
        }
        child_dispatches: dict[str, DispatchTurnModel] = {}
        original_requests: dict[str, str] = {}
        for member_id, member in members.items():
            assignment = await session.get(
                AssignmentModel,
                member.child_assignment_id,
            )
            assert assignment is not None
            assert assignment.current_attempt_id is not None
            attempt = await session.get(AttemptModel, assignment.current_attempt_id)
            assert attempt is not None and attempt.current_dispatch_id is not None
            dispatch = await session.get(
                DispatchTurnModel,
                attempt.current_dispatch_id,
            )
            request = await session.get(
                DispatchRequestModel,
                attempt.current_dispatch_id,
            )
            assert dispatch is not None and request is not None
            if member_id == "child":
                _mark_dispatch_started(dispatch)
            child_dispatches[member_id] = dispatch
            original_requests[member_id] = request.input
        await session.commit()

    return _WaveLanes(
        wave_id=wave.delegation_wave_id,
        branch_b_id=child_dispatches["child"].dispatch_id,
        branch_c_id=child_dispatches[sibling_id].dispatch_id,
        branch_b_request=original_requests["child"],
        branch_c_request=original_requests[sibling_id],
    )


def _mark_dispatch_started(dispatch: DispatchTurnModel) -> None:
    dispatch.status = "open"
    dispatch.adapter_started_at = dispatch.created_at
    dispatch.last_node_activity_at = dispatch.created_at
    dispatch.next_provider_start_at = None
    dispatch.provider_start_retry_kind = None
    dispatch.provider_start_last_error_code = None


async def _accept_unaffected_branch_start(
    session_factory: AsyncSessionFactory,
    *,
    branch_b_id: str,
    branch_c_id: str,
) -> None:
    start_page = await read_dispatch_start_page(session_factory, None, 10)
    start_signals = tuple(
        signal for signal in start_page.sources if isinstance(signal, DispatchStartDue)
    )
    assert len(start_signals) == len(start_page.sources)
    branch_c_signal = next(signal for signal in start_signals if signal.dispatch_id == branch_c_id)
    assert all(signal.dispatch_id != branch_b_id for signal in start_signals)
    async with session_factory() as session:
        candidate = await read_provider_start_candidate(
            session,
            branch_c_signal,
        )
        assert candidate is not None
        accepted = await accept_provider_start_if_current(
            session,
            task_id=candidate.task_id,
            dispatch_id=branch_c_signal.dispatch_id,
            expected_provider_start_revision=branch_c_signal.provider_start_revision,
            expected_provider_start_attempt_count=candidate.provider_start_attempt_count,
            expected_due_at=candidate.persisted_due_at,
            accepted_at=utc_now(),
        )
        await session.commit()
    assert accepted.is_accepted


async def _assert_unaffected_lane_settled(
    session_factory: AsyncSessionFactory,
    ids: RuntimeIds,
    *,
    sibling_id: str,
    lanes: _WaveLanes,
) -> None:
    async with session_factory() as session:
        task = await session.get(TaskModel, ids.task_id)
        flow = await session.get(FlowModel, ids.flow_id)
        persisted_wave = await session.get(DelegationWaveModel, lanes.wave_id)
        branch_b = await session.get(DispatchTurnModel, lanes.branch_b_id)
        branch_c = await session.get(DispatchTurnModel, lanes.branch_c_id)
        request_b = await session.get(DispatchRequestModel, lanes.branch_b_id)
        request_c = await session.get(DispatchRequestModel, lanes.branch_c_id)
        assert task is not None and task.current_team_revision_id is not None
        assert flow is not None and flow.active_flow_revision_id is not None
        assert persisted_wave is not None
        assert branch_b is not None and branch_c is not None
        current_c_selection = await session.scalar(
            select(TeamRevisionMemberModel).where(
                TeamRevisionMemberModel.task_id == ids.task_id,
                TeamRevisionMemberModel.team_revision_id == task.current_team_revision_id,
                TeamRevisionMemberModel.member_id == sibling_id,
            )
        )
        current_c_node = await session.scalar(
            select(FlowNodeModel).where(
                FlowNodeModel.flow_revision_id == flow.active_flow_revision_id,
                FlowNodeModel.member_id == sibling_id,
            )
        )
        settled_members = {
            member.child_member_id: member
            for member in await session.scalars(
                select(DelegationWaveMemberModel).where(
                    DelegationWaveMemberModel.delegation_wave_id
                    == persisted_wave.delegation_wave_id
                )
            )
        }

    assert persisted_wave.status == "open"
    assert branch_b.closed_reason == "structural_replan"
    assert branch_c.closed_reason == "boundary"
    assert branch_c.team_revision_id != task.current_team_revision_id
    assert current_c_selection is not None
    assert current_c_selection.member_configuration_id == branch_c.member_configuration_id
    assert current_c_selection.member_branch_basis_id == branch_c.member_branch_basis_id
    assert current_c_node is not None and current_c_node.state == "done"
    assert settled_members["child"].status == "pending"
    assert settled_members[sibling_id].status == "settled"
    assert settled_members[sibling_id].terminal_outcome == "green"
    assert request_b is not None
    assert request_b.input == lanes.branch_b_request
    assert request_c is not None
    assert request_c.input == lanes.branch_c_request
