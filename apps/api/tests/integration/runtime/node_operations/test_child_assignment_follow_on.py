from __future__ import annotations

from pathlib import Path

import banksia.runtime.node_operations.structural_handlers as structural_handlers
import pytest
from banksia.persistence.models import (
    AssignmentDecisionModel,
    AssignmentModel,
    AttemptCheckpointModel,
    AttemptModel,
    FlowNodeModel,
)
from banksia.runtime.clock import utc_now
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.node_operations import NodeOperationScope
from banksia.runtime.projection.signals import SupportProjectionSignal
from sqlalchemy import func, select
from tests.helpers.executor_harness import (
    SessionFactory,
    seeded_executor,
)
from tests.helpers.lineage_seed import RuntimeIds


class _CapturedProjectionPublisher:
    def __init__(self) -> None:
        self.signals: list[SupportProjectionSignal] = []

    def publish(self, signal: SupportProjectionSignal) -> bool:
        self.signals.append(signal)
        return True


async def test_assign_child_consumes_budget_once_without_assignment_projection(
    tmp_path: Path,
) -> None:
    publisher = _CapturedProjectionPublisher()
    async with seeded_executor(
        tmp_path,
        suffix="child-budget-success",
        support_projection_publisher=publisher,
    ) as (executor, session_factory, ids, _activity_signals):
        await _prepare_assignable_child(session_factory, ids, remaining=1)

        response = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="assign_child",
            arguments=_assign_child_arguments(ids.flow_revision_id),
        )
        assignment_key = response.model_dump()["target_assignment_key"]
        async with session_factory() as session:
            parent = await session.get(AssignmentModel, ids.root_assignment_id)
            assignment = await session.scalar(
                select(AssignmentModel).where(AssignmentModel.assignment_key == assignment_key)
            )
        assert parent is not None and parent.child_assignments_remaining == 0
        assert assignment is not None
        assert publisher.signals == []

        with pytest.raises(RuntimeOperationError) as duplicate:
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="assign_child",
                arguments=_assign_child_arguments(ids.flow_revision_id),
            )
        async with session_factory() as session:
            parent = await session.get(AssignmentModel, ids.root_assignment_id)
        assert duplicate.value.code == OperationFailureCode.ILLEGAL_STATE
        assert parent is not None and parent.child_assignments_remaining == 0
        assert publisher.signals == []


async def test_assign_child_zero_budget_commits_nothing(tmp_path: Path) -> None:
    publisher = _CapturedProjectionPublisher()
    async with seeded_executor(
        tmp_path,
        suffix="child-budget-zero",
        support_projection_publisher=publisher,
    ) as (executor, session_factory, ids, _activity_signals):
        assignment_count = await _prepare_assignable_child(
            session_factory,
            ids,
            remaining=0,
        )

        with pytest.raises(RuntimeOperationError) as exhausted:
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="assign_child",
                arguments=_assign_child_arguments(ids.flow_revision_id),
            )
        async with session_factory() as session:
            parent = await session.get(AssignmentModel, ids.root_assignment_id)
            child = await session.get(FlowNodeModel, ids.child_node_id)
            final_assignment_count = await session.scalar(
                select(func.count()).select_from(AssignmentModel)
            )
            decision = await session.scalar(select(AssignmentDecisionModel))
        assert exhausted.value.code == OperationFailureCode.BUDGET_EXHAUSTED
        assert parent is not None and parent.child_assignments_remaining == 0
        assert child is not None and child.current_assignment_id is None
        assert final_assignment_count == assignment_count
        assert decision is None
        assert publisher.signals == []


async def test_assign_child_loser_rolls_back_budget_decrement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher = _CapturedProjectionPublisher()

    async def lose_child_claim(*_args: object, **_kwargs: object) -> None:
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="another child assignment won the target node",
            is_retryable=False,
        )

    monkeypatch.setattr(structural_handlers, "_claim_child_node", lose_child_claim)
    async with seeded_executor(
        tmp_path,
        suffix="child-budget-rollback",
        support_projection_publisher=publisher,
    ) as (executor, session_factory, ids, _activity_signals):
        assignment_count = await _prepare_assignable_child(
            session_factory,
            ids,
            remaining=1,
        )

        with pytest.raises(RuntimeOperationError):
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="assign_child",
                arguments=_assign_child_arguments(ids.flow_revision_id),
            )
        async with session_factory() as session:
            parent = await session.get(AssignmentModel, ids.root_assignment_id)
            child = await session.get(FlowNodeModel, ids.child_node_id)
            final_assignment_count = await session.scalar(
                select(func.count()).select_from(AssignmentModel)
            )
            decision = await session.scalar(select(AssignmentDecisionModel))
        assert parent is not None and parent.child_assignments_remaining == 1
        assert child is not None and child.current_assignment_id is None
        assert final_assignment_count == assignment_count
        assert decision is None
        assert publisher.signals == []


async def test_assign_child_supersedes_terminal_child_with_fresh_assignment(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="child-fresh-assignment") as (
        executor,
        session_factory,
        ids,
        _activity_signals,
    ):
        async with session_factory() as session:
            parent = await session.get(AssignmentModel, ids.root_assignment_id)
            child = await session.get(FlowNodeModel, ids.child_node_id)
            previous = await session.get(AssignmentModel, ids.child_assignment_id)
            previous_attempt = await session.get(AttemptModel, ids.child_attempt_id)
            previous_checkpoint = await session.get(
                AttemptCheckpointModel,
                ids.child_checkpoint_id,
            )
            assert parent is not None
            assert child is not None
            assert previous is not None
            assert previous_attempt is not None
            assert previous_checkpoint is not None
            historical_parent_id = f"assignment.{ids.suffix}.root.previous"
            session.add(
                AssignmentModel(
                    assignment_id=historical_parent_id,
                    task_id=ids.task_id,
                    member_id=parent.member_id,
                    flow_id=ids.flow_id,
                    assignment_key=f"assignment-key.{ids.suffix}.root.previous",
                    node_key="root",
                    parent_assignment_id=None,
                    prompt="Previous root assignment.",
                    current_attempt_id=None,
                    work_plan_revision=0,
                    superseded_at=utc_now(),
                )
            )
            parent.child_assignment_limit = 2
            parent.child_assignments_remaining = 2
            child.state = "done"
            previous.parent_assignment_id = historical_parent_id
            previous_attempt.status = "completed"
            previous_attempt.terminal_outcome = "green"
            previous_attempt.closed_at = utc_now()
            previous_attempt.latest_checkpoint_id = previous_checkpoint.checkpoint_id
            previous_checkpoint.outcome = "green"
            previous.terminal_outcome = "green"
            previous.closed_at = utc_now()
            await session.commit()

        response = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="assign_child",
            arguments=_assign_child_arguments(ids.flow_revision_id),
        )

        async with session_factory() as session:
            parent = await session.get(AssignmentModel, ids.root_assignment_id)
            child = await session.get(FlowNodeModel, ids.child_node_id)
            previous = await session.get(AssignmentModel, ids.child_assignment_id)
            current = await session.scalar(
                select(AssignmentModel).where(
                    AssignmentModel.assignment_key == response.model_dump()["target_assignment_key"]
                )
            )
            current_attempt = (
                await session.get(AttemptModel, current.current_attempt_id)
                if current is not None and current.current_attempt_id is not None
                else None
            )

        assert parent is not None and parent.child_assignments_remaining == 1
        assert previous is not None and previous.superseded_at is not None
        assert current is not None and current.superseded_at is None
        assert child is not None and child.current_assignment_id == current.assignment_id
        assert child.state == "waiting"
        assert current_attempt is not None and current_attempt.status == "pending"


async def test_staged_child_allows_progress_but_rejects_terminal_checkpoint(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="child-staged-checkpoint") as (
        executor,
        session_factory,
        ids,
        _activity_signals,
    ):
        await _prepare_assignable_child(session_factory, ids, remaining=1)
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="assign_child",
            arguments=_assign_child_arguments(ids.flow_revision_id),
        )
        progress = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="checkpoint",
            arguments={
                "summary": "The child assignment is staged.",
                "details": "Return the temporary yield bridge next.",
            },
        )

        with pytest.raises(RuntimeOperationError) as terminal:
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="checkpoint",
                arguments={
                    "summary": "This dispatch has staged a child.",
                    "details": "Return yield instead of terminal closure.",
                    "outcome": "green",
                },
            )

        async with session_factory() as session:
            attempt = await session.get(AttemptModel, ids.root_attempt_id)
        assert terminal.value.code == OperationFailureCode.BOUNDARY_PRECONDITION_FAILED
        assert attempt is not None
        assert attempt.latest_checkpoint_id is not None
        assert progress.model_dump()["terminal"] is False


async def _prepare_assignable_child(
    session_factory: SessionFactory,
    ids: RuntimeIds,
    *,
    remaining: int,
) -> int:
    async with session_factory() as session:
        parent = await session.get(AssignmentModel, ids.root_assignment_id)
        child = await session.get(FlowNodeModel, ids.child_node_id)
        assert parent is not None and child is not None
        parent.child_assignment_limit = remaining
        parent.child_assignments_remaining = remaining
        child.current_assignment_id = None
        child.state = "ready"
        assignment_count = await session.scalar(select(func.count()).select_from(AssignmentModel))
        await session.commit()
    return int(assignment_count or 0)


def _assign_child_arguments(flow_revision_id: str) -> dict[str, object]:
    return {
        "expected_structural_revision_id": flow_revision_id,
        "payload": {
            "child_node_key": "child",
            "assignment": {"prompt": "Do bounded child work."},
        },
    }
