from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

import banksia.runtime.node_operations.executor as executor_module
from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentModel,
    AttemptModel,
    AttemptWaitModel,
    DelegationWaveModel,
    DispatchTurnModel,
    TaskModel,
    TeamRevisionMemberModel,
)
from banksia.providers import ProviderKind
from banksia.runtime import RuntimeLaunchInput
from banksia.runtime.checkpoint.reads import read_task_result
from banksia.runtime.contracts import AssignmentBody
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.launch.continuation import open_root_dispatch
from banksia.runtime.launch.service import launch_task_runtime
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    TaskStartCommitted,
)
from banksia.workflows.catalog import read_current_published_workflow
from tests.helpers.delegation_wave_e2e import (
    DelegationAssignment,
    OpenedDelegationWave,
    delegate_direct_team_for_e2e,
    open_delegation_wave_successor_for_e2e,
    settle_delegation_wave_for_e2e,
)
from tests.helpers.workflow_runtime import (
    AsyncSessionFactory,
    initialized_workflow_database,
)


@dataclass(frozen=True, slots=True)
class _WorkNode:
    member_id: str
    summary: str
    children: tuple[_WorkNode, ...] = ()


@dataclass(frozen=True, slots=True)
class _CompletionCase:
    workflow_id: str
    task_prompt: str
    root: _WorkNode

    @property
    def task_id(self) -> str:
        return f"task.catalog-completion.{self.workflow_id}"


_COMPLETION_CASES = (
    _CompletionCase(
        workflow_id="reviewed-code-change",
        task_prompt=(
            "Implement the bounded cancellation repair, prove it with focused regression "
            "coverage, and independently review the integrated change."
        ),
        root=_WorkNode(
            member_id="change-lead",
            summary="The bounded cancellation repair is implemented, verified, and reviewed.",
            children=(
                _WorkNode(
                    member_id="implementation-manager",
                    summary="Production and regression contributions are integrated.",
                    children=(
                        _WorkNode(
                            member_id="code-owner",
                            summary="The bounded production repair is complete.",
                        ),
                        _WorkNode(
                            member_id="test-owner",
                            summary="Focused regression proof is complete.",
                        ),
                    ),
                ),
                _WorkNode(
                    member_id="independent-reviewer",
                    summary="Independent review found no remaining fix-now defect.",
                ),
            ),
        ),
    ),
    _CompletionCase(
        workflow_id="evidence-synthesis",
        task_prompt=(
            "Determine whether the proposed dependency upgrade is safe for this repository "
            "using local evidence, current authoritative sources, and independent criticism."
        ),
        root=_WorkNode(
            member_id="research-lead",
            summary="The upgrade is supported within the stated compatibility boundary.",
            children=(
                _WorkNode(
                    member_id="local-evidence-researcher",
                    summary="Relevant repository constraints and contradictions are recorded.",
                ),
                _WorkNode(
                    member_id="source-researcher",
                    summary="Current authoritative guidance and its scope are recorded.",
                ),
                _WorkNode(
                    member_id="evidence-critic",
                    summary="The supported conclusion and material evidence limits are checked.",
                ),
            ),
        ),
    ),
)


@pytest.mark.parametrize(
    "case",
    _COMPLETION_CASES,
    ids=lambda case: case.workflow_id,
)
async def test_packaged_starter_completes_through_shipped_controller(
    tmp_path: Path,
    case: _CompletionCase,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    dependencies = _opening_dependencies(publisher)
    executor = NodeOperationExecutor(
        runtime_effect_publisher=publisher,
        dispatch_opening_dependencies=dependencies,
    )

    async with initialized_workflow_database(tmp_path) as session_factory:
        root_dispatch_id = await _launch_packaged_workflow(
            session_factory,
            case,
            workspace=tmp_path,
            dependencies=dependencies,
        )
        await _assert_materialized_tree(session_factory, case)
        with patch.object(
            executor_module,
            "get_session_factory",
            return_value=session_factory,
        ):
            await _complete_member(
                executor,
                session_factory,
                task_id=case.task_id,
                node=case.root,
                dispatch_id=root_dispatch_id,
                dependencies=dependencies,
            )
        await _assert_exact_completed_result(session_factory, case)


async def _launch_packaged_workflow(
    session_factory: AsyncSessionFactory,
    case: _CompletionCase,
    *,
    workspace: Path,
    dependencies: DispatchOpeningDependencies,
) -> str:
    async with session_factory() as session:
        revision = await read_current_published_workflow(
            session,
            workflow_id=case.workflow_id,
        )
        await launch_task_runtime(
            session,
            RuntimeLaunchInput(
                task_id=case.task_id,
                task_root=workspace / ".banksia" / case.task_id,
                workspace=workspace,
                workflow_revision=revision,
                assignment=AssignmentBody(prompt=case.task_prompt),
            ),
        )
        await session.commit()
        opened = await open_root_dispatch(
            session,
            signal=TaskStartCommitted(case.task_id),
            dependencies=dependencies,
        )
    assert opened.outcome == "opened"
    assert opened.dispatch_id is not None
    return opened.dispatch_id


async def _complete_member(
    executor: NodeOperationExecutor,
    session_factory: AsyncSessionFactory,
    *,
    task_id: str,
    node: _WorkNode,
    dispatch_id: str,
    dependencies: DispatchOpeningDependencies,
) -> None:
    current_dispatch_id = dispatch_id
    if node.children:
        wave = await _delegate_direct_team(
            executor,
            session_factory,
            task_id=task_id,
            parent_dispatch_id=current_dispatch_id,
            children=node.children,
        )
        for child in node.children:
            await _complete_member(
                executor,
                session_factory,
                task_id=task_id,
                node=child,
                dispatch_id=wave.dispatch_for(child.member_id),
                dependencies=dependencies,
            )
        current_dispatch_id = await _join_local_wave(
            session_factory,
            wave,
            children=node.children,
            dependencies=dependencies,
        )

    response = await executor.execute(
        scope=NodeOperationScope(
            task_id=task_id,
            dispatch_id=current_dispatch_id,
        ),
        operation_name="checkpoint",
        arguments={"summary": node.summary, "outcome": "green"},
    )
    values = response.model_dump()
    assert values["terminal"] is True
    assert values["must_stop"] is True


async def _delegate_direct_team(
    executor: NodeOperationExecutor,
    session_factory: AsyncSessionFactory,
    *,
    task_id: str,
    parent_dispatch_id: str,
    children: tuple[_WorkNode, ...],
) -> OpenedDelegationWave:
    wave = await delegate_direct_team_for_e2e(
        executor,
        session_factory,
        task_id=task_id,
        parent_dispatch_id=parent_dispatch_id,
        assignments=tuple(
            DelegationAssignment(
                child_id=child.member_id,
                prompt=(
                    f"Own the {child.member_id} contribution for this exact Task and "
                    "return a scoped, evidence-bearing Checkpoint."
                ),
            )
            for child in children
        ),
    )
    assert wave.response_must_stop
    assert tuple(member.child_id for member in wave.members) == tuple(
        child.member_id for child in children
    )
    assert wave.parent_wait_id is not None
    return wave


async def _join_local_wave(
    session_factory: AsyncSessionFactory,
    wave: OpenedDelegationWave,
    *,
    children: tuple[_WorkNode, ...],
    dependencies: DispatchOpeningDependencies,
) -> str:
    settlement = await settle_delegation_wave_for_e2e(
        session_factory,
        wave_id=wave.wave_id,
        dependencies=dependencies,
    )
    assert settlement.did_settle
    assert settlement.member_results == tuple(
        (child.member_id, child.summary) for child in children
    )
    opened = await open_delegation_wave_successor_for_e2e(
        session_factory,
        wave_id=wave.wave_id,
        dependencies=dependencies,
    )
    assert opened.outcome == "opened"
    assert opened.dispatch_id is not None
    return opened.dispatch_id


async def _assert_materialized_tree(
    session_factory: AsyncSessionFactory,
    case: _CompletionCase,
) -> None:
    expected = tuple(_preorder(case.root))
    async with session_factory() as session:
        task = await session.get(TaskModel, case.task_id)
        assert task is not None and task.current_team_revision_id is not None
        members = tuple(
            await session.scalars(
                select(TeamRevisionMemberModel)
                .where(
                    TeamRevisionMemberModel.task_id == case.task_id,
                    TeamRevisionMemberModel.team_revision_id == task.current_team_revision_id,
                )
                .order_by(TeamRevisionMemberModel.preorder_index)
            )
        )
    assert task.workflow_key == case.workflow_id
    assert tuple((member.member_id, member.parent_member_id) for member in members) == expected


async def _assert_exact_completed_result(
    session_factory: AsyncSessionFactory,
    case: _CompletionCase,
) -> None:
    expected_assignment_count = sum(1 for _entry in _preorder(case.root))
    async with session_factory() as session:
        task = await session.get(TaskModel, case.task_id)
        assert task is not None and task.root_assignment_id is not None
        result = await read_task_result(session, task_id=case.task_id)
        root_boundaries = tuple(
            await session.scalars(
                select(AcceptedBoundaryModel).where(
                    AcceptedBoundaryModel.task_id == case.task_id,
                    AcceptedBoundaryModel.assignment_id == task.root_assignment_id,
                )
            )
        )
        assignment_count = await session.scalar(
            select(func.count())
            .select_from(AssignmentModel)
            .where(AssignmentModel.task_id == case.task_id)
        )
        live_attempts = await session.scalar(
            select(func.count())
            .select_from(AttemptModel)
            .where(
                AttemptModel.task_id == case.task_id,
                AttemptModel.status.in_(("pending", "running")),
            )
        )
        live_dispatches = await session.scalar(
            select(func.count())
            .select_from(DispatchTurnModel)
            .where(
                DispatchTurnModel.task_id == case.task_id,
                DispatchTurnModel.status == "open",
            )
        )
        live_waves = await session.scalar(
            select(func.count())
            .select_from(DelegationWaveModel)
            .where(
                DelegationWaveModel.task_id == case.task_id,
                DelegationWaveModel.status == "open",
            )
        )
        live_waits = await session.scalar(
            select(func.count())
            .select_from(AttemptWaitModel)
            .where(AttemptWaitModel.task_id == case.task_id)
        )

    assert task.status == "completed"
    assert result is not None
    assert result.outcome == "green"
    assert result.summary == case.root.summary
    assert result.files == ()
    assert len(root_boundaries) == 1
    assert task.result_boundary_id == root_boundaries[0].accepted_boundary_id
    assert assignment_count == expected_assignment_count
    assert live_attempts == live_dispatches == live_waves == live_waits == 0


def _preorder(
    node: _WorkNode,
    parent_id: str | None = None,
) -> tuple[tuple[str, str | None], ...]:
    entries = [(node.member_id, parent_id)]
    for child in node.children:
        entries.extend(_preorder(child, node.member_id))
    return tuple(entries)


def _opening_dependencies(
    publisher: CapturedRuntimeEffectPublisher,
) -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds=(ProviderKind.CODEX,),
        post_commit_publisher=publisher,
    )
