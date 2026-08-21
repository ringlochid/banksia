from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select

from oh_my_subagents.persistence.models import (
    AssignmentFileReferenceModel,
    AssignmentModel,
    AttemptModel,
    AttemptWaitModel,
    DelegationWaveMemberModel,
    DelegationWaveModel,
    DispatchRequestModel,
    DispatchTurnModel,
    TaskModel,
)
from oh_my_subagents.runtime.contracts import DelegateRequest
from oh_my_subagents.runtime.contracts.operation_failure import OperationFailureCode
from oh_my_subagents.runtime.errors import RuntimeOperationError
from oh_my_subagents.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from oh_my_subagents.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    DispatchStartDue,
)
from tests.helpers.executor_harness import (
    SessionFactory,
    make_seed_child_terminal,
    seeded_executor,
)
from tests.helpers.lineage_seed import RuntimeIds


@dataclass(frozen=True, slots=True)
class _AtomicDelegationSnapshot:
    wave: DelegationWaveModel
    member: DelegationWaveMemberModel
    child_assignment: AssignmentModel
    child_attempt: AttemptModel
    parent_assignment: AssignmentModel
    parent_attempt: AttemptModel
    parent_dispatch: DispatchTurnModel
    parent_wait: AttemptWaitModel
    child_dispatch: DispatchTurnModel
    child_request: DispatchRequestModel
    file_references: tuple[AssignmentFileReferenceModel, ...]


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
        await _prepare_atomic_delegation_budget(session_factory, ids)
        result = await _delegate_bounded_child(executor, ids)
        assert result.model_dump(mode="json") == {
            "accepted": True,
            "members": [{"child_id": "child"}],
            "must_stop": True,
        }
        snapshot = await _read_atomic_delegation_snapshot(session_factory, ids)

    _assert_atomic_wave_graph(snapshot, ids)
    _assert_atomic_child_snapshot(snapshot, ids)
    assert publisher.signals == (
        DispatchStartDue(
            dispatch_id=snapshot.child_dispatch.dispatch_id,
            provider_start_revision=0,
            due_at=snapshot.child_dispatch.created_at,
        ),
    )


async def _prepare_atomic_delegation_budget(
    session_factory: SessionFactory,
    ids: RuntimeIds,
) -> None:
    async with session_factory() as session:
        await make_seed_child_terminal(session, ids)
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


async def _delegate_bounded_child(
    executor: NodeOperationExecutor,
    ids: RuntimeIds,
) -> BaseModel:
    return await executor.execute(
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


async def _read_atomic_delegation_snapshot(
    session_factory: SessionFactory,
    ids: RuntimeIds,
) -> _AtomicDelegationSnapshot:
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
        child = await session.get(AssignmentModel, member.child_assignment_id)
        assert child is not None and child.current_attempt_id is not None
        attempt = await session.get(AttemptModel, child.current_attempt_id)
        parent = await session.get(AssignmentModel, ids.root_assignment_id)
        parent_attempt = await session.get(AttemptModel, ids.root_attempt_id)
        parent_dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
        wait = await session.scalar(
            select(AttemptWaitModel).where(
                AttemptWaitModel.delegation_wave_id == wave.delegation_wave_id
            )
        )
        assert attempt is not None and attempt.current_dispatch_id is not None
        child_dispatch = await session.get(DispatchTurnModel, attempt.current_dispatch_id)
        assert child_dispatch is not None
        request = await session.get(DispatchRequestModel, child_dispatch.dispatch_id)
        files = tuple(
            await session.scalars(
                select(AssignmentFileReferenceModel)
                .where(AssignmentFileReferenceModel.assignment_id == child.assignment_id)
                .order_by(AssignmentFileReferenceModel.order_index)
            )
        )
    assert parent is not None
    assert parent_attempt is not None
    assert parent_dispatch is not None
    assert wait is not None
    assert request is not None
    return _AtomicDelegationSnapshot(
        wave=wave,
        member=member,
        child_assignment=child,
        child_attempt=attempt,
        parent_assignment=parent,
        parent_attempt=parent_attempt,
        parent_dispatch=parent_dispatch,
        parent_wait=wait,
        child_dispatch=child_dispatch,
        child_request=request,
        file_references=files,
    )


def _assert_atomic_wave_graph(
    snapshot: _AtomicDelegationSnapshot,
    ids: RuntimeIds,
) -> None:
    assert snapshot.wave.status == "open"
    assert snapshot.wave.successor_dispatch_id is None
    assert snapshot.member.order_index == 0
    assert snapshot.member.status == "pending"
    assert snapshot.member.terminal_boundary_id is None
    assert snapshot.parent_assignment.child_assignments_remaining == 6
    assert snapshot.parent_attempt.current_dispatch_id is None
    assert snapshot.parent_attempt.current_wait_id == snapshot.parent_wait.wait_id
    assert snapshot.parent_wait.source_dispatch_id == ids.current_dispatch_id
    assert snapshot.parent_wait.human_request_id is None
    assert snapshot.parent_wait.command_run_id is None
    assert snapshot.parent_dispatch.status == "closed"
    assert snapshot.parent_dispatch.closed_reason == "delegation"


def _assert_atomic_child_snapshot(
    snapshot: _AtomicDelegationSnapshot,
    ids: RuntimeIds,
) -> None:
    assignment = snapshot.child_assignment
    assert assignment.parent_assignment_id == ids.root_assignment_id
    assert assignment.created_by_dispatch_id == ids.current_dispatch_id
    assert assignment.prompt == "Do  bounded child work.\nPreserve spacing.\n"
    assert assignment.child_assignment_limit == 7
    assert assignment.child_assignments_remaining == 7
    assert assignment.retry_limit == 4
    assert assignment.retries_remaining == 4
    assert [(row.path, row.description) for row in snapshot.file_references] == [
        ("brief.md", "Read this bounded input.")
    ]
    assert snapshot.child_attempt.status == "running"
    assert snapshot.child_dispatch.status == "starting"
    assert snapshot.child_dispatch.opened_reason == "delegation"
    assert snapshot.child_dispatch.predecessor_dispatch_id is None
    assert snapshot.child_dispatch.task_start_source_task_id is None
    assert "Do  bounded child work." in snapshot.child_request.input
    assert "<continuation>" not in snapshot.child_request.input


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
            await make_seed_child_terminal(session, ids)
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

        assert wave_count == 0
        assert new_assignment_count == 0
        assert wait_count == 0
        assert parent is not None and parent.child_assignments_remaining == 0
        assert parent_attempt is not None
        assert parent_attempt.current_dispatch_id == ids.current_dispatch_id
        assert parent_attempt.current_wait_id is None
        assert parent_dispatch is not None and parent_dispatch.status == "open"
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
