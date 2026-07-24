from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from xml.etree import ElementTree

import pytest
from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentDecisionModel,
    AssignmentModel,
    AttemptCheckpointModel,
    AttemptModel,
    AttemptWaitModel,
    DispatchRequestModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.boundary import open_boundary_successor
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.flow.continuation import continue_paused_flow
from banksia.runtime.flow.service import runtime_flow_read
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import (
    BoundaryAccepted,
    CapturedRuntimeEffectPublisher,
    DispatchStartDue,
)
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import (
    SessionFactory,
    seeded_executor,
)
from tests.helpers.lineage_seed import RuntimeIds
from tests.helpers.sqlite_runtime import SyncSessionAdapter


@dataclass(frozen=True, slots=True)
class _ChildRetryRollbackState:
    assignment: tuple[str | None, int | None, datetime | None, str | None]
    source_attempt: tuple[str, str | None, datetime | None, str | None, str | None, str | None]
    source_dispatch: tuple[str, str | None, datetime | None]
    parent_attempt: tuple[str | None, str | None]
    parent_wait: tuple[str, str, str | None, str]
    attempt_ids: tuple[str, ...]
    dispatch_ids: tuple[str, ...]
    request_ids: tuple[str, ...]
    checkpoint_ids: tuple[str, ...]
    boundary_ids: tuple[str, ...]


async def test_exact_yield_source_opens_one_child_dispatch_and_duplicate_loses(
    tmp_path: Path,
) -> None:
    start_publisher = CapturedRuntimeEffectPublisher()
    dependencies = _opening_dependencies_with_publisher(start_publisher)
    async with seeded_executor(tmp_path, suffix="boundary-continuation") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        child_assignment_id, child_attempt_id = await _stage_yield_decision(
            executor,
            session_factory,
            ids,
        )
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="return_boundary",
            arguments={"boundary": "yield"},
        )

        async with session_factory() as session:
            pre_open = await runtime_flow_read(cast(AsyncSession, session), ids.task_id)
            signal = BoundaryAccepted(ids.current_dispatch_id)
            first = await open_boundary_successor(
                cast(AsyncSession, session),
                signal=signal,
                dependencies=dependencies,
            )
            duplicate = await open_boundary_successor(
                cast(AsyncSession, session),
                signal=signal,
                dependencies=dependencies,
            )
            boundary = await session.scalar(
                select(AcceptedBoundaryModel).where(
                    AcceptedBoundaryModel.source_dispatch_id == ids.current_dispatch_id
                )
            )
            flow = await session.get(FlowModel, ids.flow_id)
            attempt = await session.get(AttemptModel, child_attempt_id)
            dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )
            successor = (
                await session.get(DispatchTurnModel, first.dispatch_id)
                if first.dispatch_id is not None
                else None
            )
            dispatch_request = (
                await session.get(DispatchRequestModel, first.dispatch_id)
                if first.dispatch_id is not None
                else None
            )

    assert first.outcome == "opened", flow.pause_details if flow is not None else None
    assert pre_open.current_dispatch is None
    assert pre_open.current_node_key == "child"
    assert pre_open.active_assignment_id == child_assignment_id
    assert pre_open.active_attempt_id == child_attempt_id
    assert duplicate.outcome == "skipped"
    assert dispatch_count == 4
    assert boundary is not None and boundary.successor_dispatch_id == first.dispatch_id
    assert flow is not None and flow.status == "running"
    assert attempt is not None and attempt.current_dispatch_id == first.dispatch_id
    assert successor is not None
    assert successor.status == "starting"
    assert successor.opened_reason == "boundary"
    assert successor.predecessor_dispatch_id is None
    assert successor.assignment_id == child_assignment_id
    assert successor.attempt_id == child_attempt_id
    assert dispatch_request is not None
    input_text = dispatch_request.input
    request_root = ElementTree.fromstring(input_text)
    assert request_root.findtext("continuation/trigger/kind") == "accepted_boundary"
    assert (
        request_root.findtext("continuation/trigger/source/source_dispatch_id")
        == ids.current_dispatch_id
    )
    assert request_root.findtext("current_member/behavior") == "contributor"
    assert "assign_child" not in {
        action.text for action in request_root.findall("available_actions/action")
    }
    assert len(start_publisher.signals) == 1
    start_signal = start_publisher.signals[0]
    assert isinstance(start_signal, DispatchStartDue)
    assert start_signal.dispatch_id == successor.dispatch_id
    assert start_signal.provider_start_revision == 0


async def test_failed_boundary_open_retains_exact_operator_continuation(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="boundary-operator-recovery") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        _, child_attempt_id = await _stage_yield_decision(executor, session_factory, ids)
        await executor.execute(
            scope=_current_scope(ids),
            operation_name="return_boundary",
            arguments={"boundary": "yield"},
        )
        async with session_factory() as session:
            failed = await open_boundary_successor(
                cast(AsyncSession, session),
                signal=BoundaryAccepted(ids.current_dispatch_id),
                dependencies=_disabled_opening_dependencies(),
            )
            boundary = await session.scalar(
                select(AcceptedBoundaryModel).where(
                    AcceptedBoundaryModel.source_dispatch_id == ids.current_dispatch_id
                )
            )
            flow = await session.get(FlowModel, ids.flow_id)
            assert flow is not None
            expected_control_revision = flow.control_revision

        async with session_factory() as session:
            resumed = await continue_paused_flow(
                cast(AsyncSession, session),
                task_id=ids.task_id,
                expected_active_flow_revision_id=ids.flow_revision_id,
                expected_control_revision=expected_control_revision,
                dependencies=_opening_dependencies_with_publisher(publisher),
            )
            with pytest.raises(RuntimeOperationError) as duplicate_error:
                await continue_paused_flow(
                    cast(AsyncSession, session),
                    task_id=ids.task_id,
                    expected_active_flow_revision_id=ids.flow_revision_id,
                    expected_control_revision=expected_control_revision,
                    dependencies=_opening_dependencies(),
                )
            resumed_boundary = await session.scalar(
                select(AcceptedBoundaryModel)
                .where(AcceptedBoundaryModel.source_dispatch_id == ids.current_dispatch_id)
                .execution_options(populate_existing=True)
            )
            resumed_flow = await session.scalar(
                select(FlowModel)
                .where(FlowModel.flow_id == ids.flow_id)
                .execution_options(populate_existing=True)
            )
            resumed_attempt = await session.get(AttemptModel, child_attempt_id)
            successor = await session.get(DispatchTurnModel, resumed.dispatch_id)

    assert failed.outcome == "paused"
    assert boundary is not None and boundary.successor_dispatch_id is None
    assert flow.status == "paused" and flow.pause_reason == "runtime_transition_failed"
    assert resumed.outcome == "opened"
    assert resumed_boundary is not None
    assert resumed_boundary.successor_dispatch_id == resumed.dispatch_id
    assert resumed_flow is not None and resumed_flow.status == "running"
    assert resumed_attempt is not None
    assert resumed_attempt.current_dispatch_id == resumed.dispatch_id
    assert resumed_flow.control_revision == expected_control_revision + 1
    assert successor is not None and successor.opened_reason == "boundary"
    assert successor.predecessor_dispatch_id is None
    assert duplicate_error.value.code == OperationFailureCode.CONFLICT
    assert len(publisher.signals) == 1


async def test_child_green_opens_parent_same_attempt_successor(
    tmp_path: Path,
) -> None:
    dependencies = _opening_dependencies()
    async with seeded_executor(tmp_path, suffix="boundary-child-return") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        child_assignment_id, _child_attempt_id = await _stage_yield_decision(
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
            child_open = await open_boundary_successor(
                cast(AsyncSession, session),
                signal=BoundaryAccepted(ids.current_dispatch_id),
                dependencies=dependencies,
            )
        assert child_open.dispatch_id is not None
        checkpoint_id = await _commit_terminal_checkpoint(
            executor,
            session_factory,
            ids,
            dispatch_id=child_open.dispatch_id,
            outcome="green",
        )
        async with session_factory() as session:
            result = await open_boundary_successor(
                cast(AsyncSession, session),
                signal=BoundaryAccepted(child_open.dispatch_id),
                dependencies=dependencies,
            )
            successor = (
                await session.get(DispatchTurnModel, result.dispatch_id)
                if result.dispatch_id is not None
                else None
            )
            dispatch_request = (
                await session.get(DispatchRequestModel, result.dispatch_id)
                if result.dispatch_id is not None
                else None
            )

    assert result.outcome == "opened"
    assert successor is not None and successor.opened_reason == "child_return"
    assert successor.predecessor_dispatch_id == ids.current_dispatch_id
    assert successor.assignment_id == ids.root_assignment_id
    assert successor.attempt_id == ids.root_attempt_id
    assert dispatch_request is not None
    input_text = dispatch_request.input
    request_root = ElementTree.fromstring(input_text)
    assert request_root.findtext("continuation/trigger/kind") == "child_return"
    assert (
        request_root.findtext("continuation/trigger/source/child_assignment_id")
        == child_assignment_id
    )
    instructions_root = ElementTree.fromstring(dispatch_request.instructions)
    assert request_root.findtext("current_member/position") == "task_lead"
    assert instructions_root.find("task_lead") is not None
    assert input_text.count(checkpoint_id) == 1


async def test_child_retry_replaces_only_child_attempt_and_preserves_parent_wait(
    tmp_path: Path,
) -> None:
    retry_publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(
        tmp_path,
        suffix="boundary-child-retry",
        runtime_effect_publisher=retry_publisher,
    ) as (
        executor,
        session_factory,
        ids,
        _,
    ):
        child_assignment_id, child_attempt_id, child_dispatch_id = await _open_fresh_child(
            executor,
            session_factory,
            ids,
        )
        async with session_factory() as session:
            child_assignment_before = await session.get(
                AssignmentModel,
                child_assignment_id,
            )
            parent_attempt_before = await session.get(AttemptModel, ids.root_attempt_id)
            assert child_assignment_before is not None
            assert parent_attempt_before is not None
            assert parent_attempt_before.current_wait_id is not None
            parent_wait_id = parent_attempt_before.current_wait_id
            retries_before = child_assignment_before.retries_remaining
            signal_count_before = len(retry_publisher.signals)

        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=child_dispatch_id,
            ),
            operation_name="checkpoint",
            arguments={
                "outcome": "retry",
                "summary": "Retry the delegated assignment with the corrected approach.",
            },
        )
        await _assert_committed_child_retry(
            session_factory,
            ids,
            child_assignment_id=child_assignment_id,
            child_attempt_id=child_attempt_id,
            child_dispatch_id=child_dispatch_id,
            parent_wait_id=parent_wait_id,
            retries_before=retries_before,
            retry_publisher=retry_publisher,
            signal_count_before=signal_count_before,
        )


async def test_child_retry_database_failure_rolls_back_every_semantic_write(
    tmp_path: Path,
) -> None:
    retry_publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(
        tmp_path,
        suffix="boundary-child-retry-rollback",
        runtime_effect_publisher=retry_publisher,
    ) as (
        executor,
        session_factory,
        ids,
        _,
    ):
        child_assignment_id, child_attempt_id, child_dispatch_id = await _open_fresh_child(
            executor,
            session_factory,
            ids,
        )
        async with session_factory() as session:
            await session.execute(
                text(
                    """
                    CREATE TRIGGER reject_retry_dispatch_request
                    AFTER INSERT ON dispatch_requests
                    BEGIN
                        SELECT RAISE(ABORT, 'injected retry request failure');
                    END
                    """
                )
            )
            await session.commit()

        async with session_factory() as session:
            before = await _read_child_retry_rollback_state(
                session,
                ids,
                child_assignment_id=child_assignment_id,
                child_attempt_id=child_attempt_id,
                child_dispatch_id=child_dispatch_id,
            )
        signals_before = retry_publisher.signals

        with pytest.raises(RuntimeOperationError) as rejected:
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=child_dispatch_id,
                ),
                operation_name="checkpoint",
                arguments={
                    "outcome": "retry",
                    "summary": "This retry must roll back as one transaction.",
                },
            )

        async with session_factory() as session:
            after = await _read_child_retry_rollback_state(
                session,
                ids,
                child_assignment_id=child_assignment_id,
                child_attempt_id=child_attempt_id,
                child_dispatch_id=child_dispatch_id,
            )

    assert rejected.value.code == OperationFailureCode.CONFLICT
    assert before.checkpoint_ids == ()
    assert before.boundary_ids == ()
    assert after == before
    assert retry_publisher.signals == signals_before


def _opening_dependencies() -> DispatchOpeningDependencies:
    return _opening_dependencies_with_publisher(CapturedRuntimeEffectPublisher())


def _opening_dependencies_with_publisher(
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


def _disabled_opening_dependencies() -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=False),
        ),
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=CapturedRuntimeEffectPublisher(),
    )


def _current_scope(ids: RuntimeIds) -> NodeOperationScope:
    return NodeOperationScope(
        task_id=ids.task_id,
        dispatch_id=ids.current_dispatch_id,
    )


async def _stage_yield_decision(
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


async def _open_fresh_child(
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    ids: RuntimeIds,
) -> tuple[str, str, str]:
    child_assignment_id, child_attempt_id = await _stage_yield_decision(
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
        opened = await open_boundary_successor(
            cast(AsyncSession, session),
            signal=BoundaryAccepted(ids.current_dispatch_id),
            dependencies=_opening_dependencies(),
        )
    assert opened.outcome == "opened"
    assert opened.dispatch_id is not None
    return child_assignment_id, child_attempt_id, opened.dispatch_id


async def _assert_committed_child_retry(
    session_factory: SessionFactory,
    ids: RuntimeIds,
    *,
    child_assignment_id: str,
    child_attempt_id: str,
    child_dispatch_id: str,
    parent_wait_id: str,
    retries_before: int | None,
    retry_publisher: CapturedRuntimeEffectPublisher,
    signal_count_before: int,
) -> None:
    async with session_factory() as session:
        boundary = await session.scalar(
            select(AcceptedBoundaryModel).where(
                AcceptedBoundaryModel.source_dispatch_id == child_dispatch_id
            )
        )
        child_assignment = await session.get(AssignmentModel, child_assignment_id)
        source_attempt = await session.get(AttemptModel, child_attempt_id)
        parent_attempt = await session.get(AttemptModel, ids.root_attempt_id)
        parent_wait = await session.get(AttemptWaitModel, parent_wait_id)
        assert boundary is not None and boundary.successor_dispatch_id is not None
        assert child_assignment is not None
        retry_attempt = await session.get(
            AttemptModel,
            child_assignment.current_attempt_id,
        )
        retry_dispatch = await session.get(
            DispatchTurnModel,
            boundary.successor_dispatch_id,
        )
        retry_request = await session.get(
            DispatchRequestModel,
            boundary.successor_dispatch_id,
        )

    assert source_attempt is not None
    assert boundary.outcome == "retry"
    assert boundary.checkpoint_id is not None
    assert (source_attempt.status, source_attempt.terminal_outcome) == (
        "completed",
        "retry",
    )
    assert child_assignment.current_attempt_id != child_attempt_id
    assert child_assignment.retries_remaining == (
        retries_before - 1 if retries_before is not None else None
    )
    assert child_assignment.closed_at is None
    assert child_assignment.terminal_outcome is None
    assert retry_attempt is not None and retry_dispatch is not None
    assert retry_attempt.retry_of_attempt_id == child_attempt_id
    assert retry_attempt.status == "running"
    assert retry_attempt.current_dispatch_id == retry_dispatch.dispatch_id
    assert retry_attempt.current_wait_id is None
    assert retry_dispatch.attempt_id == retry_attempt.attempt_id
    assert retry_dispatch.status == "starting"
    assert retry_dispatch.opened_reason == "semantic_retry"
    assert retry_dispatch.predecessor_dispatch_id is None
    assert parent_attempt is not None
    assert parent_attempt.current_dispatch_id is None
    assert parent_attempt.current_wait_id == parent_wait_id
    assert parent_wait is not None
    assert parent_wait.source_dispatch_id == ids.current_dispatch_id
    assert parent_wait.sequential_child_assignment_id == child_assignment_id
    assert retry_request is not None
    _assert_semantic_retry_prompt(
        retry_request,
        boundary,
        child_attempt_id=child_attempt_id,
        child_dispatch_id=child_dispatch_id,
    )
    retry_signals = retry_publisher.signals[signal_count_before:]
    assert len(retry_signals) == 1
    retry_due = retry_signals[0]
    assert isinstance(retry_due, DispatchStartDue)
    assert retry_due.dispatch_id == retry_dispatch.dispatch_id
    assert retry_due.provider_start_revision == 0


def _assert_semantic_retry_prompt(
    retry_request: DispatchRequestModel,
    boundary: AcceptedBoundaryModel,
    *,
    child_attempt_id: str,
    child_dispatch_id: str,
) -> None:
    retry_input = ElementTree.fromstring(retry_request.input)
    assert retry_input.findtext("continuation/trigger/kind") == "semantic_retry"
    assert (
        retry_input.findtext("continuation/trigger/source/source_dispatch_id") == child_dispatch_id
    )
    assert (
        retry_input.findtext("continuation/trigger/source/previous_attempt_id") == child_attempt_id
    )
    assert (
        retry_input.findtext("continuation/trigger/source/accepted_boundary_id")
        == boundary.accepted_boundary_id
    )
    assert retry_input.findtext("continuation/trigger/result/checkpoint/id") == (
        boundary.checkpoint_id
    )


async def _read_child_retry_rollback_state(
    session: SyncSessionAdapter,
    ids: RuntimeIds,
    *,
    child_assignment_id: str,
    child_attempt_id: str,
    child_dispatch_id: str,
) -> _ChildRetryRollbackState:
    child_assignment = await session.get(AssignmentModel, child_assignment_id)
    source_attempt = await session.get(AttemptModel, child_attempt_id)
    source_dispatch = await session.get(DispatchTurnModel, child_dispatch_id)
    parent_attempt = await session.get(AttemptModel, ids.root_attempt_id)
    assert child_assignment is not None
    assert source_attempt is not None
    assert source_dispatch is not None
    assert parent_attempt is not None and parent_attempt.current_wait_id is not None
    parent_wait = await session.get(AttemptWaitModel, parent_attempt.current_wait_id)
    assert parent_wait is not None
    (
        attempt_ids,
        dispatch_ids,
        request_ids,
        checkpoint_ids,
        boundary_ids,
    ) = await _read_child_retry_row_ids(
        session,
        child_assignment_id=child_assignment_id,
        child_dispatch_id=child_dispatch_id,
    )
    return _ChildRetryRollbackState(
        assignment=(
            child_assignment.current_attempt_id,
            child_assignment.retries_remaining,
            child_assignment.closed_at,
            child_assignment.terminal_outcome,
        ),
        source_attempt=(
            source_attempt.status,
            source_attempt.terminal_outcome,
            source_attempt.closed_at,
            source_attempt.current_dispatch_id,
            source_attempt.current_wait_id,
            source_attempt.latest_checkpoint_id,
        ),
        source_dispatch=(
            source_dispatch.status,
            source_dispatch.closed_reason,
            source_dispatch.closed_at,
        ),
        parent_attempt=(
            parent_attempt.current_dispatch_id,
            parent_attempt.current_wait_id,
        ),
        parent_wait=(
            parent_wait.wait_id,
            parent_wait.source_dispatch_id,
            parent_wait.sequential_child_assignment_id,
            parent_wait.attempt_id,
        ),
        attempt_ids=attempt_ids,
        dispatch_ids=dispatch_ids,
        request_ids=request_ids,
        checkpoint_ids=checkpoint_ids,
        boundary_ids=boundary_ids,
    )


async def _read_child_retry_row_ids(
    session: SyncSessionAdapter,
    *,
    child_assignment_id: str,
    child_dispatch_id: str,
) -> tuple[
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    attempt_ids = tuple(
        await session.scalars(
            select(AttemptModel.attempt_id)
            .where(AttemptModel.assignment_id == child_assignment_id)
            .order_by(AttemptModel.attempt_id)
        )
    )
    dispatch_ids = tuple(
        await session.scalars(
            select(DispatchTurnModel.dispatch_id)
            .where(DispatchTurnModel.assignment_id == child_assignment_id)
            .order_by(DispatchTurnModel.dispatch_id)
        )
    )
    request_ids = tuple(
        await session.scalars(
            select(DispatchRequestModel.dispatch_id)
            .join(
                DispatchTurnModel,
                DispatchTurnModel.dispatch_id == DispatchRequestModel.dispatch_id,
            )
            .where(DispatchTurnModel.assignment_id == child_assignment_id)
            .order_by(DispatchRequestModel.dispatch_id)
        )
    )
    checkpoint_ids = tuple(
        await session.scalars(
            select(AttemptCheckpointModel.checkpoint_id).where(
                AttemptCheckpointModel.authoring_dispatch_id == child_dispatch_id
            )
        )
    )
    boundary_ids = tuple(
        await session.scalars(
            select(AcceptedBoundaryModel.accepted_boundary_id).where(
                AcceptedBoundaryModel.source_dispatch_id == child_dispatch_id
            )
        )
    )
    return (
        attempt_ids,
        dispatch_ids,
        request_ids,
        checkpoint_ids,
        boundary_ids,
    )


async def _commit_terminal_checkpoint(
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    ids: RuntimeIds,
    *,
    dispatch_id: str,
    outcome: str,
) -> str:
    await executor.execute(
        scope=NodeOperationScope(task_id=ids.task_id, dispatch_id=dispatch_id),
        operation_name="checkpoint",
        arguments={
            "outcome": outcome,
            "summary": f"The worker returned {outcome}.",
            "details": "Open the exact routed continuation.",
        },
    )
    async with session_factory() as session:
        checkpoint_id = cast(
            str | None,
            await session.scalar(
                select(AcceptedBoundaryModel.checkpoint_id).where(
                    AcceptedBoundaryModel.source_dispatch_id == dispatch_id
                )
            ),
        )
    assert checkpoint_id is not None
    return checkpoint_id


__all__ = []
