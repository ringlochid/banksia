from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentDecisionModel,
    AssignmentModel,
    AttemptModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.boundary import BoundaryOpeningResult, open_boundary_successor
from banksia.runtime.checkpoint import read_task_result
from banksia.runtime.dispatch import accept_provider_start_if_current
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import BoundaryAccepted, CapturedRuntimeEffectPublisher
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import (
    SessionFactory,
    seeded_executor,
)
from tests.helpers.lineage_seed import RuntimeIds


async def test_parent_child_checkpoints_select_exact_green_task_result(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    dependencies = _opening_dependencies(publisher)
    async with seeded_executor(tmp_path, suffix="parent-child-checkpoint") as (
        executor,
        session_factory,
        ids,
        _activity_signals,
    ):
        await _make_child_assignable(session_factory, ids)
        child_attempt_id, child_dispatch_id = await _assign_child_and_yield(
            executor,
            session_factory,
            dependencies,
            ids,
        )
        child_checkpoint_id, parent_dispatch_id = await _complete_child_and_resume_parent(
            executor,
            session_factory,
            dependencies,
            ids,
            child_dispatch_id=child_dispatch_id,
        )
        await _complete_parent(
            executor,
            ids,
            parent_dispatch_id=parent_dispatch_id,
        )
        async with session_factory() as session:
            terminal = await open_boundary_successor(
                cast(AsyncSession, session),
                signal=BoundaryAccepted(parent_dispatch_id),
                dependencies=dependencies,
            )
        await _assert_terminal_result(
            session_factory,
            ids,
            child_attempt_id=child_attempt_id,
            child_checkpoint_id=child_checkpoint_id,
            parent_dispatch_id=parent_dispatch_id,
            terminal=terminal,
        )


async def _assert_terminal_result(
    session_factory: SessionFactory,
    ids: RuntimeIds,
    *,
    child_attempt_id: str,
    child_checkpoint_id: str,
    parent_dispatch_id: str,
    terminal: BoundaryOpeningResult,
) -> None:
    async with session_factory() as session:
        flow = await session.get(FlowModel, ids.flow_id)
        child_attempt = await session.get(AttemptModel, child_attempt_id)
        assert child_attempt is not None
        child_assignment = await session.get(AssignmentModel, child_attempt.assignment_id)
        child_decision = await session.scalar(
            select(AssignmentDecisionModel).where(
                AssignmentDecisionModel.source_dispatch_id == ids.current_dispatch_id
            )
        )
        root_boundary = await session.scalar(
            select(AcceptedBoundaryModel).where(
                AcceptedBoundaryModel.source_dispatch_id == parent_dispatch_id
            )
        )
        result = await read_task_result(
            cast(AsyncSession, session),
            task_id=ids.task_id,
        )
        decision_count = await session.scalar(
            select(func.count()).select_from(AssignmentDecisionModel)
        )
        dispatch_count = await session.scalar(select(func.count()).select_from(DispatchTurnModel))

    assert child_decision is not None and child_decision.decision_kind == "staged_child"
    assert child_attempt.status == "completed" and child_attempt.terminal_outcome == "green"
    assert child_assignment is not None
    assert child_assignment.prompt == "Complete the bounded child work."
    assert child_checkpoint_id
    assert root_boundary is not None
    assert root_boundary.outcome == "green"
    assert root_boundary.checkpoint_id is not None
    assert result is not None
    assert result.outcome == "green"
    assert result.summary == "The parent verified the completed child work."
    assert result.details == "Return the verified result to the user."
    assert result.files == ()
    assert decision_count == 1
    assert terminal.outcome == "terminal" and terminal.dispatch_id is None
    assert flow is not None and flow.status == "completed" and flow.terminal_outcome == "green"
    assert int(dispatch_count or 0) == 5


async def _assign_child_and_yield(
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    dependencies: DispatchOpeningDependencies,
    ids: RuntimeIds,
) -> tuple[str, str]:
    staged = await executor.execute(
        scope=_scope(ids.task_id, ids.current_dispatch_id),
        operation_name="assign_child",
        arguments={
            "expected_structural_revision_id": ids.flow_revision_id,
            "payload": {
                "child_node_key": "child",
                "assignment": {"prompt": "Complete the bounded child work."},
            },
        },
    )
    await executor.execute(
        scope=_scope(ids.task_id, ids.current_dispatch_id),
        operation_name="return_boundary",
        arguments={"boundary": "yield"},
    )
    child_dispatch_id = await _open_and_accept_successor(
        session_factory,
        dependencies,
        ids,
        source_dispatch_id=ids.current_dispatch_id,
    )
    return str(staged.model_dump()["target_attempt_id"]), child_dispatch_id


async def _complete_child_and_resume_parent(
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    dependencies: DispatchOpeningDependencies,
    ids: RuntimeIds,
    *,
    child_dispatch_id: str,
) -> tuple[str, str]:
    await executor.execute(
        scope=_scope(ids.task_id, child_dispatch_id),
        operation_name="checkpoint",
        arguments={
            "outcome": "green",
            "summary": "The child completed its bounded assignment.",
            "details": "The parent should verify the completed child work.",
        },
    )
    async with session_factory() as session:
        child_checkpoint_id = await session.scalar(
            select(AcceptedBoundaryModel.checkpoint_id).where(
                AcceptedBoundaryModel.source_dispatch_id == child_dispatch_id
            )
        )
    assert child_checkpoint_id is not None
    parent_dispatch_id = await _open_and_accept_successor(
        session_factory,
        dependencies,
        ids,
        source_dispatch_id=child_dispatch_id,
    )
    return child_checkpoint_id, parent_dispatch_id


async def _complete_parent(
    executor: NodeOperationExecutor,
    ids: RuntimeIds,
    *,
    parent_dispatch_id: str,
) -> None:
    await executor.execute(
        scope=_scope(ids.task_id, parent_dispatch_id),
        operation_name="checkpoint",
        arguments={
            "outcome": "green",
            "summary": "The parent verified the completed child work.",
            "details": "Return the verified result to the user.",
        },
    )


async def _make_child_assignable(
    session_factory: SessionFactory,
    ids: RuntimeIds,
) -> None:
    async with session_factory() as session:
        parent = await session.get(AssignmentModel, ids.root_assignment_id)
        previous_child = await session.get(AssignmentModel, ids.child_assignment_id)
        previous_child_attempt = await session.get(AttemptModel, ids.child_attempt_id)
        child_node = await session.get(FlowNodeModel, ids.child_node_id)
        assert parent is not None
        assert previous_child is not None
        assert previous_child_attempt is not None
        assert child_node is not None

        retired_at = datetime.now(UTC)
        parent.child_assignment_limit = 1
        parent.child_assignments_remaining = 1
        previous_child_attempt.status = "cancelled"
        previous_child_attempt.terminal_outcome = None
        previous_child_attempt.closed_at = retired_at
        previous_child_attempt.current_dispatch_id = None
        previous_child_attempt.current_wait_id = None
        previous_child.terminal_outcome = "blocked"
        previous_child.closed_at = retired_at
        child_node.current_assignment_id = None
        child_node.state = "ready"
        await session.commit()


async def _open_and_accept_successor(
    session_factory: SessionFactory,
    dependencies: DispatchOpeningDependencies,
    ids: RuntimeIds,
    *,
    source_dispatch_id: str,
) -> str:
    async with session_factory() as session:
        opened = await open_boundary_successor(
            cast(AsyncSession, session),
            signal=BoundaryAccepted(source_dispatch_id),
            dependencies=dependencies,
        )
        assert opened.outcome == "opened"
        assert opened.dispatch_id is not None
        dispatch = await session.get(DispatchTurnModel, opened.dispatch_id)
        assert dispatch is not None and dispatch.next_provider_start_at is not None
        accepted = await accept_provider_start_if_current(
            cast(AsyncSession, session),
            task_id=ids.task_id,
            dispatch_id=dispatch.dispatch_id,
            expected_provider_start_revision=dispatch.provider_start_revision,
            expected_provider_start_attempt_count=dispatch.provider_start_attempt_count,
            expected_due_at=dispatch.next_provider_start_at,
            accepted_at=datetime.now(UTC),
        )
        await session.commit()
    assert accepted.is_accepted
    return opened.dispatch_id


def _opening_dependencies(
    publisher: CapturedRuntimeEffectPublisher,
) -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=publisher,
    )


def _scope(task_id: str, dispatch_id: str) -> NodeOperationScope:
    return NodeOperationScope(task_id=task_id, dispatch_id=dispatch_id)
