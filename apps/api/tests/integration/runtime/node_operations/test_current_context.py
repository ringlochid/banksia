from __future__ import annotations

from pathlib import Path

from autoclaw.persistence.models import (
    AcceptedBoundaryModel,
    DispatchTurnModel,
    FlowModel,
)
from autoclaw.runtime.clock import utc_now
from autoclaw.runtime.node_operations import NodeOperationScope
from sqlalchemy import update
from tests.helpers.executor_harness import SessionFactory, seeded_executor


async def test_current_context_exposes_request_readbacks_and_live_children(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="current-context") as (
        executor,
        _session_factory,
        ids,
        _signals,
    ):
        context = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="get_current_context",
            arguments={},
        )

    payload = context.model_dump(mode="json")
    dispatch_root = f"_runtime/dispatch/{ids.current_dispatch_id}"
    assert payload["readback_refs"] == {
        "instructions": f"{dispatch_root}/instructions.md",
        "input": f"{dispatch_root}/input.md",
        "workflow_manifest": "_runtime/workflow-manifest.md",
    }
    assert payload["workflow_neighborhood"] == [
        {
            "node_key": "child",
            "node_kind": "worker",
            "relationship": "direct child",
            "assignment_id": ids.child_assignment_id,
        }
    ]


async def test_current_context_normalizes_root_start_trigger(tmp_path: Path) -> None:
    async with seeded_executor(tmp_path, suffix="current-context-root") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        await _make_dispatch_current(
            session_factory,
            current_dispatch_id=ids.current_dispatch_id,
            target_dispatch_id=ids.root_dispatch_id,
            flow_id=ids.flow_id,
        )

        context = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.root_dispatch_id,
            ),
            operation_name="get_current_context",
            arguments={},
        )

    payload = context.model_dump(mode="json")
    assert payload["trigger"] == {
        "kind": "root_start",
        "source_dispatch_id": None,
    }
    assert payload["checkpoint_to_resume_from"] is None


async def test_current_context_normalizes_accepted_boundary_trigger(tmp_path: Path) -> None:
    async with seeded_executor(tmp_path, suffix="current-context-boundary") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        await _make_dispatch_current(
            session_factory,
            current_dispatch_id=ids.current_dispatch_id,
            target_dispatch_id=ids.child_dispatch_id,
            flow_id=ids.flow_id,
        )

        context = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.child_dispatch_id,
            ),
            operation_name="get_current_context",
            arguments={},
        )

    payload = context.model_dump(mode="json")
    assert payload["trigger"] == {
        "kind": "accepted_boundary",
        "source_dispatch_id": ids.root_dispatch_id,
    }
    assert payload["checkpoint_to_resume_from"] is None


async def test_current_context_reads_exact_boundary_successor_checkpoint(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="current-context-checkpoint") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        async with session_factory() as session:
            session.add(
                AcceptedBoundaryModel(
                    accepted_boundary_id="accepted-boundary.current-context-checkpoint",
                    source_dispatch_id=ids.child_dispatch_id,
                    task_id=ids.task_id,
                    flow_id=ids.flow_id,
                    assignment_id=ids.child_assignment_id,
                    attempt_id=ids.child_attempt_id,
                    outcome="blocked",
                    checkpoint_id=ids.child_checkpoint_id,
                    assignment_decision_id=None,
                    successor_dispatch_id=ids.current_dispatch_id,
                )
            )
            await session.commit()

        context = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="get_current_context",
            arguments={},
        )

    payload = context.model_dump(mode="json")
    assert payload["trigger"] == {
        "kind": "child_return",
        "source_dispatch_id": ids.child_dispatch_id,
    }
    assert payload["checkpoint_to_resume_from"] == (
        f"_runtime/attempts/{ids.child_attempt_id}/latest-checkpoint.md"
    )


async def _make_dispatch_current(
    session_factory: SessionFactory,
    *,
    current_dispatch_id: str,
    target_dispatch_id: str,
    flow_id: str,
) -> None:
    now = utc_now()
    async with session_factory() as session:
        await session.execute(
            update(DispatchTurnModel)
            .where(DispatchTurnModel.dispatch_id == current_dispatch_id)
            .values(status="closed", closed_at=now, closed_reason="cancelled")
        )
        await session.execute(
            update(DispatchTurnModel)
            .where(DispatchTurnModel.dispatch_id == target_dispatch_id)
            .values(status="open", closed_at=None, closed_reason=None)
        )
        await session.execute(
            update(FlowModel)
            .where(FlowModel.flow_id == flow_id)
            .values(current_dispatch_id=target_dispatch_id)
        )
        await session.commit()
