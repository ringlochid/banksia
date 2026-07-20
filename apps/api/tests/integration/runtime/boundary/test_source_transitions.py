from __future__ import annotations

from pathlib import Path

import pytest
from autoclaw.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentDecisionModel,
    AssignmentModel,
    AttemptModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
)
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
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
        async with session_factory() as session:
            root_node = await session.get(FlowNodeModel, ids.root_node_id)
            child_node = await session.get(FlowNodeModel, ids.child_node_id)
            child_assignment = await session.get(AssignmentModel, ids.child_assignment_id)
            child_attempt = await session.get(AttemptModel, ids.child_attempt_id)
            assert root_node is not None
            assert child_node is not None
            assert child_assignment is not None
            assert child_attempt is not None
            child_node.state = "waiting"
            child_assignment.created_by_dispatch_id = ids.current_dispatch_id
            child_attempt.status = "pending"
            session.add(
                AssignmentDecisionModel(
                    assignment_decision_id=f"assignment-decision.{ids.current_dispatch_id}",
                    source_dispatch_id=ids.current_dispatch_id,
                    task_id=ids.task_id,
                    flow_id=ids.flow_id,
                    assignment_id=ids.root_assignment_id,
                    attempt_id=ids.root_attempt_id,
                    source_flow_revision_id=ids.flow_revision_id,
                    decision_kind="staged_child",
                    staged_child_assignment_id=ids.child_assignment_id,
                    staged_child_attempt_id=ids.child_attempt_id,
                )
            )
            await session.commit()

        await executor.execute(
            scope=_current_scope(ids),
            operation_name="return_boundary",
            arguments={"boundary": "yield"},
        )

        async with session_factory() as session:
            root_node = await session.get(FlowNodeModel, ids.root_node_id)
            child_node = await session.get(FlowNodeModel, ids.child_node_id)
            root_attempt = await session.get(AttemptModel, ids.root_attempt_id)
            child_attempt = await session.get(AttemptModel, ids.child_attempt_id)
            flow = await session.get(FlowModel, ids.flow_id)
            accepted = await session.scalar(select(AcceptedBoundaryModel))

        assert root_node is not None and root_node.state == "waiting"
        assert child_node is not None and child_node.state == "running"
        assert root_attempt is not None and root_attempt.status == "running"
        assert child_attempt is not None and child_attempt.status == "running"
        assert flow is not None and flow.current_dispatch_id is None
        assert accepted is not None
        assert accepted.assignment_decision_id == (f"assignment-decision.{ids.current_dispatch_id}")


async def test_worker_retry_creates_one_attempt_and_consumes_budget_atomically(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="boundary-retry") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        await _make_child_current(session_factory, ids, retries_remaining=2)
        await _record_terminal_checkpoint(executor, ids, outcome="retry")

        await executor.execute(
            scope=_current_scope(ids),
            operation_name="return_boundary",
            arguments={"boundary": "retry"},
        )

        async with session_factory() as session:
            assignment = await session.get(AssignmentModel, ids.child_assignment_id)
            source_attempt = await session.get(AttemptModel, ids.child_attempt_id)
            retry_attempt = await session.scalar(
                select(AttemptModel).where(AttemptModel.retry_of_attempt_id == ids.child_attempt_id)
            )
            child_node = await session.get(FlowNodeModel, ids.child_node_id)

        assert assignment is not None and assignment.retries_remaining == 1
        assert retry_attempt is not None
        assert assignment.current_attempt_id == retry_attempt.attempt_id
        assert retry_attempt.status == "running"
        assert source_attempt is not None and source_attempt.status == "completed"
        assert source_attempt.terminal_outcome == "retry"
        assert child_node is not None and child_node.state == "running"


async def test_child_terminal_boundary_routes_exact_parent_before_success(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="boundary-child") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        await _make_child_current(session_factory, ids)
        await _record_terminal_checkpoint(executor, ids, outcome="green")

        await executor.execute(
            scope=_current_scope(ids),
            operation_name="return_boundary",
            arguments={"boundary": "green"},
        )

        async with session_factory() as session:
            root_node = await session.get(FlowNodeModel, ids.root_node_id)
            child_node = await session.get(FlowNodeModel, ids.child_node_id)
            child_attempt = await session.get(AttemptModel, ids.child_attempt_id)
            flow = await session.get(FlowModel, ids.flow_id)

        assert root_node is not None and root_node.state == "running"
        assert child_node is not None and child_node.state == "done"
        assert child_attempt is not None and child_attempt.status == "completed"
        assert child_attempt.terminal_outcome == "green"
        assert flow is not None and flow.status == "running"
        assert flow.current_dispatch_id is None


async def test_exhausted_retry_rolls_back_dispatch_and_semantic_state(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="boundary-retry-exhausted") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        await _make_child_current(session_factory, ids, retries_remaining=0)
        await _record_terminal_checkpoint(executor, ids, outcome="retry")

        with pytest.raises(RuntimeOperationError) as error:
            await executor.execute(
                scope=_current_scope(ids),
                operation_name="return_boundary",
                arguments={"boundary": "retry"},
            )

        async with session_factory() as session:
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            attempt = await session.get(AttemptModel, ids.child_attempt_id)
            accepted = await session.scalar(select(AcceptedBoundaryModel))

        assert error.value.code == OperationFailureCode.BUDGET_EXHAUSTED
        assert dispatch is not None and dispatch.status == "open"
        assert attempt is not None and attempt.status == "running"
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
        operation_name="record_checkpoint",
        arguments={
            "checkpoint": {
                "checkpoint_kind": "terminal",
                "outcome": outcome,
                "handoff": {
                    "summary": f"The child returned {outcome}.",
                    "next_step": "Apply the exact boundary transition.",
                },
            }
        },
    )


async def _make_child_current(
    session_factory: SessionFactory,
    ids: RuntimeIds,
    *,
    retries_remaining: int | None = None,
) -> None:
    async with session_factory() as session:
        dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
        root_node = await session.get(FlowNodeModel, ids.root_node_id)
        child_node = await session.get(FlowNodeModel, ids.child_node_id)
        child_assignment = await session.get(AssignmentModel, ids.child_assignment_id)
        assert dispatch is not None
        assert root_node is not None
        assert child_node is not None
        assert child_assignment is not None
        dispatch.assignment_id = ids.child_assignment_id
        dispatch.attempt_id = ids.child_attempt_id
        dispatch.node_key = "child"
        root_node.state = "waiting"
        child_node.state = "running"
        if retries_remaining is not None:
            child_assignment.retry_limit = 2
            child_assignment.retries_remaining = retries_remaining
        await session.commit()


__all__ = []
