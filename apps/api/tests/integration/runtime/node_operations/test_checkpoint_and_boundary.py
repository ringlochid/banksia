from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import cast

import banksia.runtime.node_operations.domain_handlers as domain_handlers
import banksia.runtime.node_operations.executor as executor_module
import pytest
from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentDecisionModel,
    AssignmentModel,
    AttemptCheckpointModel,
    AttemptModel,
    CheckpointFileReferenceModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
    TaskModel,
)
from banksia.runtime.checkpoint import read_task_result
from banksia.runtime.clock import utc_now
from banksia.runtime.contracts import (
    AssignmentBody,
    CheckpointRequest,
    CheckpointResponse,
    FileReference,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.node_operations import (
    NodeOperationScope,
    get_node_operation_descriptor,
)
from banksia.runtime.post_commit.publisher import CapturedRuntimeEffectPublisher
from banksia.runtime.post_commit.signals import BoundaryAccepted
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import seeded_executor


async def test_progress_checkpoint_persists_exact_message_and_ordered_files(
    tmp_path: Path,
) -> None:
    suffix = "checkpoint-progress"
    async with seeded_executor(tmp_path, suffix=suffix) as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        workspace = tmp_path / f"task-{suffix}" / "workspace"
        _write_checkpoint_reference_files(workspace)

        result = cast(
            CheckpointResponse,
            await executor.execute(
                scope=_scope(ids.task_id, ids.current_dispatch_id),
                operation_name="checkpoint",
                arguments={
                    "summary": "The bounded review is under way.",
                    "details": "The approach and current report are ready for a teammate.",
                    "files": [
                        {
                            "path": "notes/approach.md",
                            "description": "Working approach.",
                        },
                        {
                            "path": "artifacts/report.md",
                            "description": "Current reviewable report.",
                        },
                    ],
                },
            ),
        )

        async with session_factory() as session:
            checkpoint = await session.scalar(
                select(AttemptCheckpointModel).where(
                    AttemptCheckpointModel.authoring_dispatch_id == ids.current_dispatch_id,
                    AttemptCheckpointModel.summary == "The bounded review is under way.",
                )
            )
            assert checkpoint is not None
            files = tuple(
                await session.scalars(
                    select(CheckpointFileReferenceModel)
                    .where(CheckpointFileReferenceModel.checkpoint_id == checkpoint.checkpoint_id)
                    .order_by(CheckpointFileReferenceModel.order_index)
                )
            )
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            attempt = await session.get(AttemptModel, ids.root_attempt_id)

        assert checkpoint.task_id == ids.task_id
        assert checkpoint.assignment_id == ids.root_assignment_id
        assert checkpoint.attempt_id == ids.root_attempt_id
        assert checkpoint.outcome is None
        assert checkpoint.details == ("The approach and current report are ready for a teammate.")
        assert [(row.path, row.description) for row in files] == [
            ("notes/approach.md", "Working approach."),
            ("artifacts/report.md", "Current reviewable report."),
        ]
        assert dispatch is not None and dispatch.status == "open"
        assert attempt is not None and attempt.latest_checkpoint_id == checkpoint.checkpoint_id
        assert result.terminal is False
        assert result.must_stop is False
        assert result.checkpoint == CheckpointRequest(
            summary="The bounded review is under way.",
            details="The approach and current report are ready for a teammate.",
            files=(
                FileReference(
                    path="notes/approach.md",
                    description="Working approach.",
                ),
                FileReference(
                    path="artifacts/report.md",
                    description="Current reviewable report.",
                ),
            ),
        )
        assert [signal.activity_revision for signal in signals] == [1]


async def test_root_blocked_checkpoint_atomically_selects_exact_task_result(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(
        tmp_path,
        suffix="checkpoint-blocked",
        runtime_effect_publisher=publisher,
    ) as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        result = cast(
            CheckpointResponse,
            await executor.execute(
                scope=_scope(ids.task_id, ids.current_dispatch_id),
                operation_name="checkpoint",
                arguments={
                    "summary": "The task is blocked on an unavailable dependency.",
                    "details": "The exact missing dependency is recorded for the user.",
                    "outcome": "blocked",
                },
            ),
        )

        async with session_factory() as session:
            checkpoint = await session.scalar(
                select(AttemptCheckpointModel).where(
                    AttemptCheckpointModel.authoring_dispatch_id == ids.current_dispatch_id,
                    AttemptCheckpointModel.summary
                    == "The task is blocked on an unavailable dependency.",
                )
            )
            boundary = await session.scalar(
                select(AcceptedBoundaryModel).where(
                    AcceptedBoundaryModel.source_dispatch_id == ids.current_dispatch_id
                )
            )
            task = await session.get(TaskModel, ids.task_id)
            flow = await session.get(FlowModel, ids.flow_id)
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            attempt = await session.get(AttemptModel, ids.root_attempt_id)
            assignment = await session.get(AssignmentModel, ids.root_assignment_id)
            node = await session.get(FlowNodeModel, ids.root_node_id)
            task_result = await read_task_result(
                cast(AsyncSession, session),
                task_id=ids.task_id,
            )

        assert checkpoint is not None and checkpoint.outcome == "blocked"
        assert boundary is not None and boundary.checkpoint_id == checkpoint.checkpoint_id
        assert boundary.assignment_decision_id is None
        assert task is not None and task.result_boundary_id == boundary.accepted_boundary_id
        assert flow is not None and (flow.status, flow.terminal_outcome) == (
            "completed",
            "blocked",
        )
        assert dispatch is not None and dispatch.status == "closed"
        assert attempt is not None and (attempt.status, attempt.terminal_outcome) == (
            "completed",
            "blocked",
        )
        assert assignment is not None and assignment.terminal_outcome == "blocked"
        assert assignment.closed_at is not None
        assert node is not None and node.state == "failed"
        assert task_result is not None
        assert task_result.model_dump(mode="json", exclude={"completed_at"}) == {
            "outcome": "blocked",
            "summary": "The task is blocked on an unavailable dependency.",
            "details": "The exact missing dependency is recorded for the user.",
            "files": [],
        }
        assert task_result.completed_at == boundary.committed_at
        assert result.terminal is True
        assert result.must_stop is True
        assert publisher.signals == (BoundaryAccepted(ids.current_dispatch_id),)
        assert [signal.activity_revision for signal in signals] == [1]


async def test_retry_checkpoint_closes_only_execution_and_preserves_assignment(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(
        tmp_path,
        suffix="checkpoint-retry",
        runtime_effect_publisher=publisher,
    ) as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        result = cast(
            CheckpointResponse,
            await executor.execute(
                scope=_scope(ids.task_id, ids.current_dispatch_id),
                operation_name="checkpoint",
                arguments={
                    "summary": "Retry this exact assignment with the corrected approach.",
                    "outcome": "retry",
                },
            ),
        )

        async with session_factory() as session:
            boundary = await session.scalar(
                select(AcceptedBoundaryModel).where(
                    AcceptedBoundaryModel.source_dispatch_id == ids.current_dispatch_id
                )
            )
            source_attempt = await session.get(AttemptModel, ids.root_attempt_id)
            assignment = await session.get(AssignmentModel, ids.root_assignment_id)
            assert assignment is not None
            retry_attempt = await session.get(AttemptModel, assignment.current_attempt_id)
            task = await session.get(TaskModel, ids.task_id)
            flow = await session.get(FlowModel, ids.flow_id)
            task_result = await read_task_result(
                cast(AsyncSession, session),
                task_id=ids.task_id,
            )

        assert boundary is not None and boundary.outcome == "retry"
        assert boundary.checkpoint_id is not None
        assert source_attempt is not None
        assert (source_attempt.status, source_attempt.terminal_outcome) == (
            "completed",
            "retry",
        )
        assert assignment.closed_at is None
        assert assignment.terminal_outcome is None
        assert assignment.current_attempt_id != ids.root_attempt_id
        assert assignment.retries_remaining == 0
        assert retry_attempt is not None
        assert retry_attempt.retry_of_attempt_id == ids.root_attempt_id
        assert retry_attempt.status == "running"
        assert task is not None and task.result_boundary_id is None
        assert task_result is None
        assert flow is not None and flow.status == "running"
        assert result.terminal is True and result.must_stop is True
        assert publisher.signals == (BoundaryAccepted(ids.current_dispatch_id),)


async def test_green_checkpoint_requires_exact_current_direct_child_participation(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="checkpoint-participation") as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        with pytest.raises(RuntimeOperationError) as rejected:
            await executor.execute(
                scope=_scope(ids.task_id, ids.current_dispatch_id),
                operation_name="checkpoint",
                arguments={"summary": "All work is complete.", "outcome": "green"},
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

        assert rejected.value.code == OperationFailureCode.BOUNDARY_PRECONDITION_FAILED
        assert "child" in rejected.value.summary
        assert checkpoints == ()
        assert dispatch is not None and dispatch.status == "open"
        assert [signal.activity_revision for signal in signals] == [1]


async def test_green_checkpoint_accepts_exact_current_child_basis(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="checkpoint-green") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        now = utc_now()
        async with session_factory() as session:
            child_checkpoint = await session.get(
                AttemptCheckpointModel,
                ids.child_checkpoint_id,
            )
            child_attempt = await session.get(AttemptModel, ids.child_attempt_id)
            child_assignment = await session.get(
                AssignmentModel,
                ids.child_assignment_id,
            )
            child_node = await session.get(FlowNodeModel, ids.child_node_id)
            assert child_checkpoint is not None
            assert child_attempt is not None
            assert child_assignment is not None
            assert child_node is not None
            child_checkpoint.outcome = "green"
            child_attempt.latest_checkpoint_id = ids.child_checkpoint_id
            child_attempt.status = "completed"
            child_attempt.terminal_outcome = "green"
            child_attempt.closed_at = now
            child_assignment.terminal_outcome = "green"
            child_assignment.closed_at = now
            child_node.state = "done"
            session.add(
                AcceptedBoundaryModel(
                    accepted_boundary_id=f"accepted-boundary.{ids.child_dispatch_id}",
                    source_dispatch_id=ids.child_dispatch_id,
                    task_id=ids.task_id,
                    flow_id=ids.flow_id,
                    assignment_id=ids.child_assignment_id,
                    attempt_id=ids.child_attempt_id,
                    outcome="green",
                    checkpoint_id=ids.child_checkpoint_id,
                    assignment_decision_id=None,
                    successor_dispatch_id=ids.current_dispatch_id,
                    committed_at=now,
                )
            )
            await session.commit()

        response = cast(
            CheckpointResponse,
            await executor.execute(
                scope=_scope(ids.task_id, ids.current_dispatch_id),
                operation_name="checkpoint",
                arguments={"summary": "Integrated every current child.", "outcome": "green"},
            ),
        )

        async with session_factory() as session:
            task_result = await read_task_result(
                cast(AsyncSession, session),
                task_id=ids.task_id,
            )

        assert response.terminal is True and response.must_stop is True
        assert task_result is not None
        assert task_result.outcome == "green"
        assert task_result.summary == "Integrated every current child."


@pytest.mark.parametrize(
    ("files", "expected"),
    (
        (
            [
                {"path": "report.md"},
                {"path": "report.md", "description": "Duplicate."},
            ],
            "duplicate",
        ),
        ([{"path": "missing.md"}], "does not exist"),
        ([{"path": "escape.md"}], "symbolic link"),
    ),
)
async def test_checkpoint_file_references_fail_atomically(
    tmp_path: Path,
    files: list[dict[str, str]],
    expected: str,
) -> None:
    suffix = f"checkpoint-files-{expected.replace(' ', '-')}"
    async with seeded_executor(tmp_path, suffix=suffix) as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        workspace = tmp_path / f"task-{suffix}" / "workspace"
        (workspace / "report.md").write_text("report")
        if files[0]["path"] == "escape.md":
            outside = tmp_path / "outside.md"
            outside.write_text("outside")
            (workspace / "escape.md").symlink_to(outside)

        with pytest.raises(RuntimeOperationError, match=expected) as rejected:
            await executor.execute(
                scope=_scope(ids.task_id, ids.current_dispatch_id),
                operation_name="checkpoint",
                arguments={"summary": "Reference files.", "files": files},
            )

        async with session_factory() as session:
            checkpoints = tuple(
                await session.scalars(
                    select(AttemptCheckpointModel).where(
                        AttemptCheckpointModel.authoring_dispatch_id == ids.current_dispatch_id
                    )
                )
            )

        assert rejected.value.code == OperationFailureCode.INVALID_TASK_PATH
        assert checkpoints == ()


async def test_terminal_checkpoint_rejects_staged_child_without_partial_write(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="checkpoint-staged-child") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        async with session_factory() as session:
            child_assignment = await session.get(
                AssignmentModel,
                ids.child_assignment_id,
            )
            assert child_assignment is not None
            child_assignment.created_by_dispatch_id = ids.current_dispatch_id
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

        with pytest.raises(RuntimeOperationError) as rejected:
            await executor.execute(
                scope=_scope(ids.task_id, ids.current_dispatch_id),
                operation_name="checkpoint",
                arguments={
                    "summary": "This must not replace delegated work.",
                    "outcome": "blocked",
                },
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

        assert rejected.value.code == OperationFailureCode.BOUNDARY_PRECONDITION_FAILED
        assert checkpoints == ()
        assert dispatch is not None and dispatch.status == "open"


async def test_unexpected_checkpoint_integrity_failure_is_normalized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def reject_persistence(*_args: object, **_kwargs: object) -> None:
        raise IntegrityError(
            "INSERT INTO controller_truth",
            {},
            sqlite3.IntegrityError("FOREIGN KEY constraint failed"),
        )

    monkeypatch.setattr(
        domain_handlers,
        "execute_controller_node_operation",
        reject_persistence,
    )
    async with seeded_executor(tmp_path, suffix="checkpoint-integrity") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        with pytest.raises(RuntimeOperationError) as rejected:
            await executor.execute(
                scope=_scope(ids.task_id, ids.current_dispatch_id),
                operation_name="checkpoint",
                arguments={"summary": "Exercise persistence normalization."},
            )

        async with session_factory() as session:
            checkpoints = tuple(
                await session.scalars(
                    select(AttemptCheckpointModel).where(
                        AttemptCheckpointModel.authoring_dispatch_id == ids.current_dispatch_id
                    )
                )
            )

        assert rejected.value.code == OperationFailureCode.INTERNAL_ERROR
        assert "FOREIGN KEY" not in rejected.value.summary
        assert checkpoints == ()


async def test_admission_integrity_failure_is_normalized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def reject_activity(*_args: object, **_kwargs: object) -> None:
        raise IntegrityError(
            "UPDATE dispatch_turns",
            {},
            sqlite3.IntegrityError("FOREIGN KEY constraint failed"),
        )

    monkeypatch.setattr(executor_module, "refresh_node_activity", reject_activity)
    async with seeded_executor(tmp_path, suffix="checkpoint-admission-integrity") as (
        executor,
        _session_factory,
        ids,
        _signals,
    ):
        with pytest.raises(RuntimeOperationError) as rejected:
            await executor.execute(
                scope=_scope(ids.task_id, ids.current_dispatch_id),
                operation_name="get_current_context",
                arguments={},
            )

        assert rejected.value.code == OperationFailureCode.INTERNAL_ERROR
        assert "FOREIGN KEY" not in rejected.value.summary


def test_checkpoint_and_assignment_schemas_reject_unknown_fields() -> None:
    checkpoint_descriptor = get_node_operation_descriptor("checkpoint")
    assignment_descriptor = get_node_operation_descriptor("assign_child")

    for schema_model in (
        AssignmentBody,
        CheckpointRequest,
        checkpoint_descriptor.request_model,
        assignment_descriptor.request_model,
    ):
        assert schema_model.model_json_schema()["additionalProperties"] is False
    with pytest.raises(ValidationError, match="unexpected_field"):
        checkpoint_descriptor.request_model.model_validate(
            {
                "summary": "Checkpoint payload with an unknown field.",
                "unexpected_field": ["unexpected value"],
            }
        )
    with pytest.raises(ValidationError, match="unexpected_field"):
        assignment_descriptor.request_model.model_validate(
            {
                "expected_structural_revision_id": "revision.current",
                "payload": {
                    "child_node_key": "child",
                    "assignment": {"prompt": "Child assignment."},
                    "unexpected_field": ["unexpected value"],
                },
            }
        )


def _write_checkpoint_reference_files(workspace: Path) -> None:
    (workspace / "notes").mkdir()
    (workspace / "artifacts").mkdir()
    (workspace / "notes" / "approach.md").write_text("working notes")
    (workspace / "artifacts" / "report.md").write_text("reviewable report")


def _scope(task_id: str, dispatch_id: str) -> NodeOperationScope:
    return NodeOperationScope(task_id=task_id, dispatch_id=dispatch_id)
