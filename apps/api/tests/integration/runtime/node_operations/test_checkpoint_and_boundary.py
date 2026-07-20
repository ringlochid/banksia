from __future__ import annotations

from pathlib import Path

import pytest
from autoclaw.persistence.models import (
    AcceptedBoundaryModel,
    AttemptCheckpointModel,
    AttemptModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
)
from autoclaw.runtime.clock import utc_now
from autoclaw.runtime.contracts import (
    AssignmentBody,
    AssignmentProjection,
    CheckpointProjection,
)
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.node_operations import (
    NodeOperationScope,
    get_node_operation_descriptor,
)
from autoclaw.runtime.post_commit.publisher import CapturedRuntimeEffectPublisher
from autoclaw.runtime.post_commit.signals import BoundaryAccepted
from pydantic import ValidationError
from sqlalchemy import select
from tests.helpers.executor_harness import seeded_executor


async def test_record_checkpoint_persists_exact_source_and_keeps_dispatch_open(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="checkpoint") as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        result = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="record_checkpoint",
            arguments={
                "checkpoint": {
                    "checkpoint_kind": "progress",
                    "handoff": {
                        "summary": "The target runtime state is consistent.",
                        "next_step": "Continue the bounded operation.",
                        "blockers": ["None."],
                        "risks": ["A stale caller must still lose."],
                    },
                }
            },
        )

        async with session_factory() as session:
            checkpoint = await session.get(
                AttemptCheckpointModel,
                result.model_dump()["checkpoint_id"],
            )
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)

        assert checkpoint is not None
        assert checkpoint.task_id == ids.task_id
        assert checkpoint.assignment_id == ids.root_assignment_id
        assert checkpoint.attempt_id == ids.root_attempt_id
        assert checkpoint.authoring_dispatch_id == ids.current_dispatch_id
        assert checkpoint.checkpoint_kind == "progress"
        assert checkpoint.outcome is None
        assert checkpoint.evidence_json == {
            "next_step": "Continue the bounded operation.",
            "blockers": ["None."],
            "risks": ["A stale caller must still lose."],
        }
        assert dispatch is not None and dispatch.status == "open"
        assert dispatch.node_activity_revision == 1
        assert [signal.activity_revision for signal in signals] == [1]


def test_checkpoint_and_assignment_schemas_reject_unknown_fields() -> None:
    checkpoint_descriptor = get_node_operation_descriptor("record_checkpoint")
    assignment_descriptor = get_node_operation_descriptor("assign_child")

    schema_models = (
        AssignmentBody,
        AssignmentProjection,
        CheckpointProjection,
        checkpoint_descriptor.request_model,
        assignment_descriptor.request_model,
    )
    for schema_model in schema_models:
        assert schema_model.model_json_schema()["additionalProperties"] is False
    with pytest.raises(ValidationError, match="unexpected_field"):
        checkpoint_descriptor.request_model.model_validate(
            {
                "checkpoint": {
                    "checkpoint_kind": "progress",
                    "handoff": {
                        "summary": "Checkpoint payload with an unknown field.",
                        "next_step": "Reject the unknown field.",
                    },
                    "unexpected_field": ["unexpected value"],
                }
            }
        )
    with pytest.raises(ValidationError, match="unexpected_field"):
        assignment_descriptor.request_model.model_validate(
            {
                "expected_structural_revision_id": "revision.current",
                "payload": {
                    "child_node_key": "child",
                    "assignment_intent": {"summary": "Child assignment."},
                    "unexpected_field": ["unexpected value"],
                },
            }
        )


async def test_return_blocked_boundary_closes_exact_source_after_prerequisites(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(
        tmp_path,
        suffix="boundary",
        runtime_effect_publisher=publisher,
    ) as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        async with session_factory() as session:
            child_attempt = await session.get(AttemptModel, ids.child_attempt_id)
            assert child_attempt is not None
            child_attempt.status = "completed"
            child_attempt.terminal_outcome = "blocked"
            child_attempt.closed_at = utc_now()
            await session.commit()

        checkpoint = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="record_checkpoint",
            arguments={
                "checkpoint": {
                    "checkpoint_kind": "terminal",
                    "outcome": "blocked",
                    "handoff": {
                        "summary": "The root and its descendant are blocked.",
                        "next_step": "Escalate the recorded blocker.",
                    },
                }
            },
        )
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="release_blocked",
            arguments={"expected_structural_revision_id": ids.flow_revision_id},
        )
        result = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="return_boundary",
            arguments={"boundary": "blocked"},
        )

        async with session_factory() as session:
            accepted = await session.scalar(
                select(AcceptedBoundaryModel).where(
                    AcceptedBoundaryModel.source_dispatch_id == ids.current_dispatch_id
                )
            )
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            root_attempt = await session.get(AttemptModel, ids.root_attempt_id)
            flow = await session.get(FlowModel, ids.flow_id)
            root_node = await session.get(FlowNodeModel, ids.root_node_id)

        assert result.model_dump()["accepted_boundary"] == "blocked"
        assert accepted is not None
        assert accepted.checkpoint_id == checkpoint.model_dump()["checkpoint_id"]
        assert accepted.assignment_decision_id is not None
        assert accepted.successor_dispatch_id is None
        assert dispatch is not None and dispatch.status == "closed"
        assert dispatch.closed_reason == "boundary"
        assert root_attempt is not None and root_attempt.status == "completed"
        assert root_attempt.terminal_outcome == "blocked"
        assert flow is not None and flow.current_dispatch_id is None
        assert flow.status == "completed"
        assert flow.terminal_outcome == "blocked"
        assert root_node is not None and root_node.state == "failed"
        assert [signal.activity_revision for signal in signals] == [1, 2, 3]
        assert publisher.signals == (BoundaryAccepted(ids.current_dispatch_id),)


async def test_return_boundary_rejects_missing_current_checkpoint_without_closure(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="boundary-reject") as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        with pytest.raises(RuntimeOperationError) as error:
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="return_boundary",
                arguments={"boundary": "blocked"},
            )

        async with session_factory() as session:
            accepted = await session.scalar(
                select(AcceptedBoundaryModel).where(
                    AcceptedBoundaryModel.source_dispatch_id == ids.current_dispatch_id
                )
            )
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            attempt = await session.get(AttemptModel, ids.root_attempt_id)

        assert error.value.code == OperationFailureCode.ILLEGAL_STATE
        assert error.value.is_retryable is False
        assert accepted is None
        assert dispatch is not None and dispatch.status == "open"
        assert attempt is not None and attempt.status == "running"
        assert dispatch.node_activity_revision == 1
        assert [signal.activity_revision for signal in signals] == [1]


async def test_return_boundary_rejects_stale_source_before_activity_admission(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="boundary-stale") as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        with pytest.raises(RuntimeOperationError) as error:
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.root_dispatch_id,
                ),
                operation_name="return_boundary",
                arguments={"boundary": "green"},
            )

        async with session_factory() as session:
            accepted = await session.scalar(
                select(AcceptedBoundaryModel).where(
                    AcceptedBoundaryModel.source_dispatch_id == ids.root_dispatch_id
                )
            )
            stale_dispatch = await session.get(DispatchTurnModel, ids.root_dispatch_id)

        assert error.value.code == OperationFailureCode.STALE_DISPATCH
        assert error.value.is_retryable is False
        assert accepted is None
        assert stale_dispatch is not None
        assert stale_dispatch.node_activity_revision == 0
        assert signals == []


async def test_terminal_checkpoint_rejects_another_checkpoint_after_admission(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="checkpoint-terminal") as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        scope = NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        )
        terminal_arguments = {
            "checkpoint": {
                "checkpoint_kind": "terminal",
                "outcome": "blocked",
                "handoff": {
                    "summary": "The current assignment is blocked.",
                    "next_step": "Return the matching boundary.",
                },
            }
        }
        await executor.execute(
            scope=scope,
            operation_name="record_checkpoint",
            arguments=terminal_arguments,
        )
        context = await executor.execute(
            scope=scope,
            operation_name="get_current_context",
            arguments={},
        )
        allowed_actions = context.model_dump(mode="json")["allowed_actions"]

        with pytest.raises(RuntimeOperationError) as error:
            await executor.execute(
                scope=scope,
                operation_name="record_checkpoint",
                arguments=terminal_arguments,
            )

        async with session_factory() as session:
            checkpoints = tuple(
                await session.scalars(
                    select(AttemptCheckpointModel).where(
                        AttemptCheckpointModel.authoring_dispatch_id == ids.current_dispatch_id
                    )
                )
            )
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)

        assert error.value.code == OperationFailureCode.ILLEGAL_STATE
        assert error.value.is_retryable is False
        assert "record_checkpoint" not in allowed_actions
        assert "open_human_request" not in allowed_actions
        assert "start_command_run" not in allowed_actions
        assert len(checkpoints) == 1
        assert dispatch is not None and dispatch.node_activity_revision == 3
        assert [signal.activity_revision for signal in signals] == [1, 2, 3]
