from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentDecisionModel,
    AssignmentModel,
    AttemptModel,
    AttemptWaitModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from sqlalchemy import select
from tests.helpers.executor_harness import (
    SessionFactory,
    seeded_executor,
)
from tests.helpers.lineage_seed import RuntimeIds


async def test_yield_activates_the_exact_staged_child_in_source_transaction(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="boundary-yield") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        child_assignment_id, child_attempt_id = await _stage_fresh_child_assignment(
            executor,
            session_factory,
            ids,
        )

        await executor.execute(
            scope=_current_scope(ids),
            operation_name="return_boundary",
            arguments={"boundary": "yield"},
        )

        async with session_factory() as session:
            root_node = await session.get(FlowNodeModel, ids.root_node_id)
            child_node = await session.get(FlowNodeModel, ids.child_node_id)
            root_attempt = await session.get(AttemptModel, ids.root_attempt_id)
            child_attempt = await session.get(AttemptModel, child_attempt_id)
            flow = await session.get(FlowModel, ids.flow_id)
            accepted = await session.scalar(select(AcceptedBoundaryModel))
            wait = await session.scalar(
                select(AttemptWaitModel).where(AttemptWaitModel.attempt_id == ids.root_attempt_id)
            )

        assert root_node is not None and root_node.state == "waiting"
        assert child_node is not None and child_node.state == "running"
        assert root_attempt is not None and root_attempt.status == "running"
        assert root_attempt.current_dispatch_id is None
        assert root_attempt.current_wait_id == wait.wait_id
        assert child_attempt is not None and child_attempt.status == "running"
        assert flow is not None
        assert wait is not None
        assert wait.source_dispatch_id == ids.current_dispatch_id
        assert wait.assignment_id == ids.root_assignment_id
        assert wait.sequential_child_assignment_id == child_assignment_id
        assert accepted is not None
        assert accepted.assignment_decision_id == (f"assignment-decision.{ids.current_dispatch_id}")


async def test_exhausted_retry_rolls_back_dispatch_and_semantic_state(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="boundary-retry-exhausted") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        async with session_factory() as session:
            assignment = await session.get(AssignmentModel, ids.root_assignment_id)
            assert assignment is not None
            assignment.retry_limit = 0
            assignment.retries_remaining = 0
            await session.commit()
        with pytest.raises(RuntimeOperationError) as error:
            await _record_terminal_checkpoint(executor, ids, outcome="retry")

        async with session_factory() as session:
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            attempt = await session.get(AttemptModel, ids.root_attempt_id)
            accepted = await session.scalar(select(AcceptedBoundaryModel))

        assert error.value.code == OperationFailureCode.BUDGET_EXHAUSTED
        assert dispatch is not None and dispatch.status == "open"
        assert attempt is not None and attempt.status == "running"
        assert accepted is None


async def test_root_terminal_rejects_a_live_descendant_without_partial_boundary(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="boundary-live-descendant") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        with pytest.raises(RuntimeOperationError) as error:
            await _record_terminal_checkpoint(executor, ids, outcome="blocked")

        async with session_factory() as session:
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            root_attempt = await session.get(AttemptModel, ids.root_attempt_id)
            accepted = await session.scalar(select(AcceptedBoundaryModel))

    assert error.value.code == OperationFailureCode.CONFLICT
    assert dispatch is not None and dispatch.status == "open"
    assert root_attempt is not None and root_attempt.status == "running"
    assert root_attempt.current_dispatch_id == ids.current_dispatch_id
    assert accepted is None


def _current_scope(ids: RuntimeIds) -> NodeOperationScope:
    return NodeOperationScope(
        task_id=ids.task_id,
        dispatch_id=ids.current_dispatch_id,
    )


async def _record_terminal_checkpoint(
    executor: NodeOperationExecutor,
    ids: RuntimeIds,
    *,
    outcome: str,
) -> None:
    await executor.execute(
        scope=_current_scope(ids),
        operation_name="checkpoint",
        arguments={
            "outcome": outcome,
            "summary": f"The child returned {outcome}.",
            "details": "Apply the exact boundary transition.",
        },
    )


async def _stage_fresh_child_assignment(
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    ids: RuntimeIds,
) -> tuple[str, str]:
    async with session_factory() as session:
        parent = await session.get(AssignmentModel, ids.root_assignment_id)
        child_node = await session.get(FlowNodeModel, ids.child_node_id)
        old_assignment = await session.get(AssignmentModel, ids.child_assignment_id)
        old_attempt = await session.get(AttemptModel, ids.child_attempt_id)
        assert parent is not None and child_node is not None
        assert old_assignment is not None and old_attempt is not None
        retired_at = datetime.now(UTC)
        parent.child_assignments_remaining = 1
        old_attempt.status = "cancelled"
        old_attempt.terminal_outcome = None
        old_attempt.closed_at = retired_at
        old_attempt.current_dispatch_id = None
        old_attempt.current_wait_id = None
        old_assignment.terminal_outcome = "blocked"
        old_assignment.closed_at = retired_at
        child_node.current_assignment_id = None
        child_node.state = "ready"
        await session.commit()
    await executor.execute(
        scope=_current_scope(ids),
        operation_name="assign_child",
        arguments={
            "expected_structural_revision_id": ids.flow_revision_id,
            "payload": {
                "child_node_key": "child",
                "assignment": {"prompt": "Complete the exact delegated work."},
            },
        },
    )
    async with session_factory() as session:
        decision = await session.scalar(
            select(AssignmentDecisionModel).where(
                AssignmentDecisionModel.source_dispatch_id == ids.current_dispatch_id
            )
        )
    assert decision is not None
    return decision.staged_child_assignment_id, decision.staged_child_attempt_id


__all__ = []
