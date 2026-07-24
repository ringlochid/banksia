from __future__ import annotations

from pathlib import Path

import pytest
from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentFileReferenceModel,
    AssignmentModel,
    AttemptModel,
    AttemptWaitModel,
    DelegationWaveMemberModel,
    DelegationWaveModel,
    DispatchRequestModel,
    DispatchTurnModel,
    FlowNodeModel,
    TaskModel,
)
from banksia.runtime.contracts import DelegateRequest
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.node_operations import NodeOperationScope
from banksia.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    DispatchStartDue,
)
from pydantic import ValidationError
from sqlalchemy import func, select
from tests.helpers.executor_harness import seeded_executor
from tests.helpers.lineage_seed import FIXTURE_TIMESTAMP, RuntimeIds
from tests.helpers.sqlite_runtime import SyncSessionAdapter


async def test_delegate_atomically_starts_child_and_selects_parent_wave_wait(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    workspace_file = tmp_path / "task-delegate-atomic" / "workspace" / "brief.md"
    async with seeded_executor(
        tmp_path,
        suffix="delegate-atomic",
        runtime_effect_publisher=publisher,
    ) as (executor, session_factory, ids, _activity):
        workspace_file.write_text("bounded input", encoding="utf-8")
        async with session_factory() as session:
            await _make_child_terminal(session, ids)
            task = await session.get(TaskModel, ids.task_id)
            parent = await session.get(AssignmentModel, ids.root_assignment_id)
            assert task is not None and parent is not None
            task.max_child_assignments_per_assignment = 7
            task.max_retries_per_assignment = 4
            parent.child_assignment_limit = 7
            parent.child_assignments_remaining = 7
            parent.retry_limit = 4
            parent.retries_remaining = 4
            await session.commit()

        result = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="delegate",
            arguments={
                "assignments": [
                    {
                        "child_id": "child",
                        "prompt": "Do  bounded child work.\r\nPreserve spacing.\r",
                        "files": [
                            {
                                "path": "./brief.md",
                                "description": "Read this bounded input.",
                            }
                        ],
                    }
                ]
            },
        )

        assert result.model_dump(mode="json") == {
            "accepted": True,
            "members": [{"child_id": "child"}],
            "must_stop": True,
        }
        async with session_factory() as session:
            wave = await session.scalar(
                select(DelegationWaveModel).where(
                    DelegationWaveModel.source_dispatch_id == ids.current_dispatch_id
                )
            )
            assert wave is not None
            member = await session.scalar(
                select(DelegationWaveMemberModel).where(
                    DelegationWaveMemberModel.delegation_wave_id == wave.delegation_wave_id
                )
            )
            assert member is not None
            assignment = await session.get(AssignmentModel, member.child_assignment_id)
            assert assignment is not None and assignment.current_attempt_id is not None
            attempt = await session.get(AttemptModel, assignment.current_attempt_id)
            parent = await session.get(AssignmentModel, ids.root_assignment_id)
            parent_attempt = await session.get(AttemptModel, ids.root_attempt_id)
            parent_dispatch = await session.get(
                DispatchTurnModel,
                ids.current_dispatch_id,
            )
            parent_node = await session.get(FlowNodeModel, ids.root_node_id)
            child_node = await session.get(FlowNodeModel, ids.child_node_id)
            old_child = await session.get(AssignmentModel, ids.child_assignment_id)
            wait = await session.scalar(
                select(AttemptWaitModel).where(
                    AttemptWaitModel.delegation_wave_id == wave.delegation_wave_id
                )
            )
            child_dispatch = (
                await session.get(DispatchTurnModel, attempt.current_dispatch_id)
                if attempt is not None and attempt.current_dispatch_id is not None
                else None
            )
            dispatch_request = (
                await session.get(DispatchRequestModel, child_dispatch.dispatch_id)
                if child_dispatch is not None
                else None
            )
            file_rows = tuple(
                await session.scalars(
                    select(AssignmentFileReferenceModel)
                    .where(AssignmentFileReferenceModel.assignment_id == assignment.assignment_id)
                    .order_by(AssignmentFileReferenceModel.order_index)
                )
            )

        assert wave.status == "open"
        assert wave.successor_dispatch_id is None
        assert member.order_index == 0
        assert member.status == "pending"
        assert member.terminal_boundary_id is None
        assert assignment.parent_assignment_id == ids.root_assignment_id
        assert assignment.created_by_dispatch_id == ids.current_dispatch_id
        assert assignment.prompt == "Do  bounded child work.\nPreserve spacing.\n"
        assert assignment.child_assignment_limit == 7
        assert assignment.child_assignments_remaining == 7
        assert assignment.retry_limit == 4
        assert assignment.retries_remaining == 4
        assert [(row.path, row.description) for row in file_rows] == [
            ("brief.md", "Read this bounded input.")
        ]
        assert parent is not None and parent.child_assignments_remaining == 6
        assert parent_attempt is not None
        assert wait is not None
        assert parent_attempt.current_dispatch_id is None
        assert parent_attempt.current_wait_id == wait.wait_id
        assert wait.source_dispatch_id == ids.current_dispatch_id
        assert wait.human_request_id is None
        assert wait.command_run_id is None
        assert parent_dispatch is not None
        assert parent_dispatch.status == "closed"
        assert parent_dispatch.closed_reason == "delegation"
        assert parent_node is not None and parent_node.state == "waiting"
        assert child_node is not None and child_node.state == "running"
        assert child_node.current_assignment_id == assignment.assignment_id
        assert old_child is not None and old_child.superseded_at is not None
        assert attempt is not None and attempt.status == "running"
        assert child_dispatch is not None
        assert child_dispatch.status == "starting"
        assert child_dispatch.opened_reason == "delegation"
        assert child_dispatch.predecessor_dispatch_id is None
        assert child_dispatch.flow_start_source_flow_id is None
        assert dispatch_request is not None
        assert "Do  bounded child work." in dispatch_request.input
        assert "<continuation>" not in dispatch_request.input
        assert publisher.signals == (
            DispatchStartDue(
                dispatch_id=child_dispatch.dispatch_id,
                provider_start_revision=0,
                due_at=child_dispatch.created_at,
            ),
        )


async def test_delegate_budget_rejection_rolls_back_every_staged_row(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(
        tmp_path,
        suffix="delegate-budget",
        runtime_effect_publisher=publisher,
    ) as (executor, session_factory, ids, _activity):
        async with session_factory() as session:
            await _make_child_terminal(session, ids)
            parent = await session.get(AssignmentModel, ids.root_assignment_id)
            assert parent is not None
            parent.child_assignments_remaining = 0
            await session.commit()

        with pytest.raises(RuntimeOperationError) as error:
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="delegate",
                arguments={
                    "assignments": [
                        {
                            "child_id": "child",
                            "prompt": "This entire delegation must roll back.",
                        }
                    ]
                },
            )

        assert error.value.code == OperationFailureCode.BUDGET_EXHAUSTED
        async with session_factory() as session:
            wave_count = await session.scalar(select(func.count()).select_from(DelegationWaveModel))
            new_assignment_count = await session.scalar(
                select(func.count())
                .select_from(AssignmentModel)
                .where(AssignmentModel.created_by_dispatch_id == ids.current_dispatch_id)
            )
            wait_count = await session.scalar(select(func.count()).select_from(AttemptWaitModel))
            parent = await session.get(AssignmentModel, ids.root_assignment_id)
            parent_attempt = await session.get(AttemptModel, ids.root_attempt_id)
            parent_dispatch = await session.get(
                DispatchTurnModel,
                ids.current_dispatch_id,
            )
            child_node = await session.get(FlowNodeModel, ids.child_node_id)
            old_child = await session.get(AssignmentModel, ids.child_assignment_id)

        assert wave_count == 0
        assert new_assignment_count == 0
        assert wait_count == 0
        assert parent is not None and parent.child_assignments_remaining == 0
        assert parent_attempt is not None
        assert parent_attempt.current_dispatch_id == ids.current_dispatch_id
        assert parent_attempt.current_wait_id is None
        assert parent_dispatch is not None and parent_dispatch.status == "open"
        assert child_node is not None
        assert child_node.current_assignment_id == ids.child_assignment_id
        assert child_node.state == "failed"
        assert old_child is not None and old_child.superseded_at is None
        assert publisher.signals == ()


@pytest.mark.parametrize(
    "assignments",
    [
        [
            {"child_id": "same", "prompt": "First."},
            {"child_id": "same", "prompt": "Second."},
        ],
        [{"child_id": f"child-{index}", "prompt": "Work."} for index in range(9)],
    ],
)
def test_delegate_schema_rejects_duplicate_or_oversized_wave(
    assignments: list[dict[str, str]],
) -> None:
    with pytest.raises(ValidationError):
        DelegateRequest.model_validate({"assignments": assignments})


async def _make_child_terminal(
    session: SyncSessionAdapter,
    ids: RuntimeIds,
) -> None:
    child_assignment = await session.get(AssignmentModel, ids.child_assignment_id)
    child_attempt = await session.get(AttemptModel, ids.child_attempt_id)
    child_node = await session.get(FlowNodeModel, ids.child_node_id)
    assert child_assignment is not None
    assert child_attempt is not None
    assert child_node is not None
    child_assignment.terminal_outcome = "blocked"
    child_assignment.closed_at = FIXTURE_TIMESTAMP
    child_attempt.status = "completed"
    child_attempt.terminal_outcome = "blocked"
    child_attempt.latest_checkpoint_id = ids.child_checkpoint_id
    child_attempt.closed_at = FIXTURE_TIMESTAMP
    child_node.state = "failed"
    session.add(
        AcceptedBoundaryModel(
            accepted_boundary_id=f"accepted-boundary.{ids.child_dispatch_id}",
            source_dispatch_id=ids.child_dispatch_id,
            task_id=ids.task_id,
            flow_id=ids.flow_id,
            assignment_id=ids.child_assignment_id,
            attempt_id=ids.child_attempt_id,
            outcome="blocked",
            checkpoint_id=ids.child_checkpoint_id,
            successor_dispatch_id=None,
            committed_at=FIXTURE_TIMESTAMP,
        )
    )
