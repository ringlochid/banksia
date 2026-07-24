from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    AssignmentModel,
    AttemptModel,
    AttemptWaitModel,
    CommandRunModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
    HumanRequestModel,
    TaskEventModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.clock import utc_now
from banksia.runtime.command_run.service import cancel_command_run
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.flow.service import (
    cancel_runtime_flow,
    continue_runtime_flow,
    list_runtime_flows,
    pause_runtime_flow,
    runtime_flow_read,
)
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    CommandRunCancellationRequested,
    DispatchCleanupRequested,
    DispatchStartDue,
    HumanRequestTerminal,
)
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import (
    seeded_executor,
)
from tests.helpers.lineage_seed import RuntimeIds


async def test_flow_reads_expose_current_controller_identity(tmp_path: Path) -> None:
    async with seeded_executor(tmp_path, suffix="flow-read") as (
        _,
        session_factory,
        ids,
        _,
    ):
        async with session_factory() as session:
            flow = await runtime_flow_read(cast(AsyncSession, session), ids.task_id)
            page = await list_runtime_flows(cast(AsyncSession, session))

    assert flow.status.value == "running"
    assert flow.terminal_outcome is None
    assert flow.active_flow_revision_id == ids.flow_revision_id
    assert flow.current_dispatch is not None
    assert flow.current_dispatch.dispatch_id == ids.current_dispatch_id
    assert flow.active_assignment_id == ids.root_assignment_id
    assert flow.active_attempt_id == ids.root_attempt_id
    assert flow.control_revision >= 0
    assert len(page.items) == 1 and page.items[0].task_id == ids.task_id
    assert page.items[0].terminal_outcome is None


async def test_flow_reads_expose_blocked_terminal_outcome(tmp_path: Path) -> None:
    async with seeded_executor(tmp_path, suffix="flow-outcome") as (
        _,
        session_factory,
        ids,
        _,
    ):
        async with session_factory() as session:
            completed_at = utc_now()
            await session.execute(
                update(DispatchTurnModel)
                .where(DispatchTurnModel.dispatch_id == ids.current_dispatch_id)
                .values(
                    status="closed",
                    closed_reason="task_terminal",
                    closed_at=completed_at,
                    next_provider_start_at=None,
                    provider_start_retry_kind=None,
                )
            )
            await session.execute(
                update(AttemptModel)
                .where(AttemptModel.attempt_id == ids.root_attempt_id)
                .values(
                    status="completed",
                    terminal_outcome="blocked",
                    current_dispatch_id=None,
                    closed_at=completed_at,
                )
            )
            await session.execute(
                update(FlowModel)
                .where(FlowModel.task_id == ids.task_id)
                .values(
                    status="completed",
                    terminal_outcome="blocked",
                )
            )
            await session.commit()
        async with session_factory() as session:
            flow = await runtime_flow_read(cast(AsyncSession, session), ids.task_id)
            page = await list_runtime_flows(cast(AsyncSession, session))
            blocked_page = await list_runtime_flows(cast(AsyncSession, session), status="blocked")
            completed_page = await list_runtime_flows(
                cast(AsyncSession, session), status="completed"
            )

    assert flow.status.value == "completed"
    assert flow.terminal_outcome == "blocked"
    assert flow.current_dispatch is None
    assert len(page.items) == 1 and page.items[0].terminal_outcome == "blocked"
    assert [item.task_id for item in blocked_page.items] == [ids.task_id]
    assert completed_page.items == ()


async def test_pause_closes_exact_current_dispatch_and_rejects_stale_control(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="flow-pause") as (
        _,
        session_factory,
        ids,
        _,
    ):
        async with session_factory() as session:
            flow = await session.get(FlowModel, ids.flow_id)
            assert flow is not None
            control_revision = flow.control_revision
            response = await pause_runtime_flow(
                cast(AsyncSession, session),
                ids.task_id,
                expected_active_flow_revision_id=ids.flow_revision_id,
                expected_control_revision=control_revision,
                actor_ref="operator.test",
                runtime_effect_publisher=publisher,
            )
            with pytest.raises(RuntimeOperationError) as stale:
                await pause_runtime_flow(
                    cast(AsyncSession, session),
                    ids.task_id,
                    expected_active_flow_revision_id=ids.flow_revision_id,
                    expected_control_revision=control_revision,
                )
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            page = await list_runtime_flows(cast(AsyncSession, session))
            event = await session.scalar(
                select(TaskEventModel).where(TaskEventModel.event_type == "task_paused")
            )

    assert response.flow.status.value == "paused"
    assert response.flow.control_revision == control_revision + 1
    assert response.flow.current_dispatch is None
    assert response.flow.pause_reason == "paused_by_operator"
    assert page.items[0].current_node_key == "root"
    assert page.items[0].active_assignment_id == ids.root_assignment_id
    assert page.items[0].active_attempt_id == ids.root_attempt_id
    assert dispatch is not None and dispatch.status == "closed"
    assert dispatch.closed_reason == "paused"
    assert event is not None and event.actor_ref == "operator.test"
    assert stale.value.code == OperationFailureCode.CONFLICT
    assert publisher.signals == (DispatchCleanupRequested(dispatch_id=ids.current_dispatch_id),)


async def test_pause_retains_open_human_wait(tmp_path: Path) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="flow-pause-wait") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        request_id = await _open_human_request(executor, ids)
        async with session_factory() as session:
            flow = await session.get(FlowModel, ids.flow_id)
            assert flow is not None
            response = await pause_runtime_flow(
                cast(AsyncSession, session),
                ids.task_id,
                expected_active_flow_revision_id=ids.flow_revision_id,
                expected_control_revision=flow.control_revision,
                runtime_effect_publisher=publisher,
            )
            request = await session.get(HumanRequestModel, request_id)
            wait = await session.scalar(
                select(AttemptWaitModel).where(AttemptWaitModel.human_request_id == request_id)
            )
            page = await list_runtime_flows(cast(AsyncSession, session))

    assert response.flow.status.value == "paused"
    assert response.flow.waiting_cause == "human_request"
    assert response.flow.active_attempt_id == ids.root_attempt_id
    assert page.items[0].current_node_key == "root"
    assert page.items[0].active_assignment_id == ids.root_assignment_id
    assert page.items[0].active_attempt_id == ids.root_attempt_id
    assert request is not None and request.status == "open"
    assert wait is not None and wait.human_request_id == request_id
    assert publisher.signals == ()


async def test_continue_opens_one_successor_at_the_exact_control_revision(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="flow-continue") as (
        _,
        session_factory,
        ids,
        _,
    ):
        async with session_factory() as session:
            flow = await session.get(FlowModel, ids.flow_id)
            assert flow is not None
            paused = await pause_runtime_flow(
                cast(AsyncSession, session),
                ids.task_id,
                expected_active_flow_revision_id=ids.flow_revision_id,
                expected_control_revision=flow.control_revision,
                runtime_effect_publisher=publisher,
            )
            resumed = await continue_runtime_flow(
                cast(AsyncSession, session),
                ids.task_id,
                expected_active_flow_revision_id=ids.flow_revision_id,
                expected_control_revision=paused.flow.control_revision,
                dependencies=_opening_dependencies(publisher),
            )
            assert resumed.current_dispatch is not None
            successor = await session.get(
                DispatchTurnModel,
                resumed.current_dispatch.dispatch_id,
            )
            resumed_event = await session.scalar(
                select(TaskEventModel).where(TaskEventModel.event_type == "task_resumed")
            )

    assert resumed.status.value == "running"
    assert resumed.control_revision == paused.flow.control_revision + 1
    assert successor is not None and successor.opened_reason == "operator_continue"
    assert successor.predecessor_dispatch_id == ids.current_dispatch_id
    assert resumed_event is not None and resumed_event.dispatch_id == successor.dispatch_id
    assert publisher.signals[0] == DispatchCleanupRequested(dispatch_id=ids.current_dispatch_id)
    assert isinstance(publisher.signals[1], DispatchStartDue)


async def test_nested_sequential_pause_continue_cancel_preserves_exact_lane(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="flow-nested-controls") as (
        _,
        session_factory,
        ids,
        _,
    ):
        async with session_factory() as session:
            parent_wait_id = await _seed_nested_sequential_lane(
                cast(AsyncSession, session),
                ids,
            )

        async with session_factory() as session:
            flow = await session.get(FlowModel, ids.flow_id)
            assert flow is not None
            paused = await pause_runtime_flow(
                cast(AsyncSession, session),
                ids.task_id,
                expected_active_flow_revision_id=ids.flow_revision_id,
                expected_control_revision=flow.control_revision,
                runtime_effect_publisher=publisher,
            )
            parent_after_pause = await session.get(AttemptModel, ids.root_attempt_id)
            child_after_pause = await session.get(AttemptModel, ids.child_attempt_id)
            retained_wait = await session.get(AttemptWaitModel, parent_wait_id)
            paused_leaf = await session.get(DispatchTurnModel, ids.child_dispatch_id)

        assert parent_after_pause is not None
        assert parent_after_pause.current_wait_id == parent_wait_id
        assert child_after_pause is not None and child_after_pause.current_dispatch_id is None
        assert retained_wait is not None
        assert retained_wait.sequential_child_assignment_id == ids.child_assignment_id
        assert paused_leaf is not None and paused_leaf.closed_reason == "paused"

        async with session_factory() as session:
            resumed = await continue_runtime_flow(
                cast(AsyncSession, session),
                ids.task_id,
                expected_active_flow_revision_id=ids.flow_revision_id,
                expected_control_revision=paused.flow.control_revision,
                dependencies=_opening_dependencies(publisher),
            )
            assert resumed.current_dispatch is not None
            resumed_dispatch_id = resumed.current_dispatch.dispatch_id
            resumed_leaf = await session.get(DispatchTurnModel, resumed_dispatch_id)
            parent_after_resume = await session.get(AttemptModel, ids.root_attempt_id)
            child_after_resume = await session.get(AttemptModel, ids.child_attempt_id)
            dispatch_count_before_cancel = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )

        assert resumed.active_assignment_id == ids.child_assignment_id
        assert resumed.active_attempt_id == ids.child_attempt_id
        assert resumed_leaf is not None
        assert resumed_leaf.attempt_id == ids.child_attempt_id
        assert resumed_leaf.predecessor_dispatch_id == ids.child_dispatch_id
        assert parent_after_resume is not None
        assert parent_after_resume.current_wait_id == parent_wait_id
        assert child_after_resume is not None
        assert child_after_resume.current_dispatch_id == resumed_dispatch_id

        async with session_factory() as session:
            cancelled = await cancel_runtime_flow(
                cast(AsyncSession, session),
                ids.task_id,
                expected_active_flow_revision_id=ids.flow_revision_id,
                expected_control_revision=resumed.control_revision,
                runtime_effect_publisher=publisher,
            )
            remaining_waits = await session.scalar(
                select(func.count()).select_from(AttemptWaitModel)
            )
            active_attempts = await session.scalar(
                select(func.count())
                .select_from(AttemptModel)
                .where(AttemptModel.status.in_(("pending", "running")))
            )
            selected_attempts = await session.scalar(
                select(func.count())
                .select_from(AttemptModel)
                .where(
                    (AttemptModel.current_dispatch_id.is_not(None))
                    | (AttemptModel.current_wait_id.is_not(None))
                )
            )
            dispatch_count_after_cancel = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )
            cancelled_leaf = await session.get(DispatchTurnModel, resumed_dispatch_id)

    assert cancelled.status.value == "cancelled"
    assert remaining_waits == 0
    assert active_attempts == 0
    assert selected_attempts == 0
    assert dispatch_count_after_cancel == dispatch_count_before_cancel
    assert cancelled_leaf is not None and cancelled_leaf.closed_reason == "cancelled"
    assert len(publisher.signals) == 3
    assert publisher.signals[0] == DispatchCleanupRequested(dispatch_id=ids.child_dispatch_id)
    assert isinstance(publisher.signals[1], DispatchStartDue)
    assert publisher.signals[2] == DispatchCleanupRequested(dispatch_id=resumed_dispatch_id)


async def test_cancel_closes_execution_authority_without_successor(tmp_path: Path) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="flow-cancel") as (
        _,
        session_factory,
        ids,
        _,
    ):
        async with session_factory() as session:
            flow = await session.get(FlowModel, ids.flow_id)
            assert flow is not None
            dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )
            response = await cancel_runtime_flow(
                cast(AsyncSession, session),
                ids.task_id,
                expected_active_flow_revision_id=ids.flow_revision_id,
                expected_control_revision=flow.control_revision,
                actor_ref="operator.test",
                runtime_effect_publisher=publisher,
            )
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            active_attempts = await session.scalar(
                select(func.count())
                .select_from(AttemptModel)
                .where(AttemptModel.status.in_(("pending", "running")))
            )
            active_nodes = await session.scalar(
                select(func.count())
                .select_from(FlowNodeModel)
                .where(FlowNodeModel.state.in_(("ready", "running", "waiting", "paused")))
            )
            final_dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )

    assert response.status.value == "cancelled"
    assert response.current_dispatch is None
    assert dispatch is not None and dispatch.closed_reason == "cancelled"
    assert active_attempts == 0
    assert active_nodes == 0
    assert final_dispatch_count == dispatch_count
    assert publisher.signals == (DispatchCleanupRequested(dispatch_id=ids.current_dispatch_id),)


async def test_cancel_wins_over_stale_continue_without_opening_a_successor(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="flow-cancel-continue") as (
        _,
        session_factory,
        ids,
        _,
    ):
        async with session_factory() as session:
            flow = await session.get(FlowModel, ids.flow_id)
            assert flow is not None
            dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )
            paused = await pause_runtime_flow(
                cast(AsyncSession, session),
                ids.task_id,
                expected_active_flow_revision_id=ids.flow_revision_id,
                expected_control_revision=flow.control_revision,
                runtime_effect_publisher=publisher,
            )
            await cancel_runtime_flow(
                cast(AsyncSession, session),
                ids.task_id,
                expected_active_flow_revision_id=ids.flow_revision_id,
                expected_control_revision=paused.flow.control_revision,
                runtime_effect_publisher=publisher,
            )
            with pytest.raises(RuntimeOperationError) as stale_continue:
                await continue_runtime_flow(
                    cast(AsyncSession, session),
                    ids.task_id,
                    expected_active_flow_revision_id=ids.flow_revision_id,
                    expected_control_revision=paused.flow.control_revision,
                    dependencies=_opening_dependencies(publisher),
                )
            final_dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )

    assert stale_continue.value.code == OperationFailureCode.CONFLICT
    assert final_dispatch_count == dispatch_count
    assert not any(isinstance(signal, DispatchStartDue) for signal in publisher.signals)


async def test_cancel_terminalizes_human_wait_and_requests_command_cancellation(
    tmp_path: Path,
) -> None:
    human_publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="flow-cancel-human") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        request_id = await _open_human_request(executor, ids)
        async with session_factory() as session:
            flow = await session.get(FlowModel, ids.flow_id)
            assert flow is not None
            paused = await pause_runtime_flow(
                cast(AsyncSession, session),
                ids.task_id,
                expected_active_flow_revision_id=ids.flow_revision_id,
                expected_control_revision=flow.control_revision,
                runtime_effect_publisher=human_publisher,
            )
            await cancel_runtime_flow(
                cast(AsyncSession, session),
                ids.task_id,
                expected_active_flow_revision_id=ids.flow_revision_id,
                expected_control_revision=paused.flow.control_revision,
                runtime_effect_publisher=human_publisher,
            )
            request = await session.get(HumanRequestModel, request_id)
            wait = await session.scalar(
                select(AttemptWaitModel).where(AttemptWaitModel.human_request_id == request_id)
            )

    assert request is not None and request.status == "cancelled"
    assert request.resolution_kind == "cancelled"
    assert wait is None
    assert human_publisher.signals == (HumanRequestTerminal(request_id=request_id),)

    command_publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="flow-cancel-command") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        run_id = await _open_command_run(executor, ids)
        async with session_factory() as session:
            flow = await session.get(FlowModel, ids.flow_id)
            assert flow is not None
            waiting_page = await list_runtime_flows(cast(AsyncSession, session))
            await cancel_runtime_flow(
                cast(AsyncSession, session),
                ids.task_id,
                expected_active_flow_revision_id=ids.flow_revision_id,
                expected_control_revision=flow.control_revision,
                runtime_effect_publisher=command_publisher,
            )
            source = await session.get(CommandRunModel, run_id)
            wait = await session.scalar(
                select(AttemptWaitModel).where(AttemptWaitModel.command_run_id == run_id)
            )
            with pytest.raises(RuntimeOperationError) as stale_command_cancel:
                await cancel_command_run(
                    cast(AsyncSession, session),
                    task_id=ids.task_id,
                    run_id=run_id,
                )

    assert source is not None and source.state == "cancellation_requested"
    assert wait is None
    assert waiting_page.items[0].current_node_key == "root"
    assert waiting_page.items[0].active_assignment_id == ids.root_assignment_id
    assert waiting_page.items[0].active_attempt_id == ids.root_attempt_id
    assert stale_command_cancel.value.code == OperationFailureCode.CONFLICT
    assert command_publisher.signals == (
        CommandRunCancellationRequested(
            run_id=run_id,
            ownership_revision=source.ownership_revision,
        ),
    )


async def _open_human_request(executor: NodeOperationExecutor, ids: RuntimeIds) -> str:
    result = await executor.execute(
        scope=NodeOperationScope(task_id=ids.task_id, dispatch_id=ids.current_dispatch_id),
        operation_name="open_human_request",
        arguments={
            "request": {
                "kind": "direction",
                "summary": "Choose one direction.",
                "items": [
                    {
                        "id": "direction",
                        "prompt": "Which direction?",
                        "options": [
                            {"id": "a", "title": "A"},
                            {"id": "b", "title": "B"},
                        ],
                    }
                ],
            }
        },
    )
    return cast(str, result.model_dump()["request_id"])


async def _open_command_run(executor: NodeOperationExecutor, ids: RuntimeIds) -> str:
    result = await executor.execute(
        scope=NodeOperationScope(task_id=ids.task_id, dispatch_id=ids.current_dispatch_id),
        operation_name="start_command_run",
        arguments={
            "request": {
                "command": {"kind": "argv", "argv": ["python", "-V"]},
                "summary": "Read the Python version.",
            }
        },
    )
    return cast(str, result.model_dump()["command_id"])


async def _seed_nested_sequential_lane(
    session: AsyncSession,
    ids: RuntimeIds,
) -> str:
    parent_assignment = await session.get(AssignmentModel, ids.root_assignment_id)
    parent_attempt = await session.get(AttemptModel, ids.root_attempt_id)
    child_assignment = await session.get(AssignmentModel, ids.child_assignment_id)
    child_attempt = await session.get(AttemptModel, ids.child_attempt_id)
    parent_node = await session.get(FlowNodeModel, ids.root_node_id)
    parent_dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
    child_dispatch = await session.get(DispatchTurnModel, ids.child_dispatch_id)
    assert parent_assignment is not None
    assert parent_attempt is not None
    assert child_assignment is not None
    assert child_attempt is not None
    assert parent_node is not None
    assert parent_dispatch is not None
    assert child_dispatch is not None

    created_at = utc_now()
    wait_id = f"attempt-wait.{ids.suffix}.sequential"
    child_assignment.created_by_dispatch_id = parent_dispatch.dispatch_id
    parent_node.state = "waiting"
    parent_dispatch.status = "closed"
    parent_dispatch.closed_at = created_at
    parent_dispatch.closed_reason = "boundary"
    parent_dispatch.next_provider_start_at = None
    parent_dispatch.provider_start_retry_kind = None
    parent_attempt.current_dispatch_id = None
    parent_attempt.current_wait_id = wait_id
    child_dispatch.status = "open"
    child_dispatch.closed_at = None
    child_dispatch.closed_reason = None
    child_attempt.current_dispatch_id = child_dispatch.dispatch_id
    child_attempt.current_wait_id = None
    session.add(
        AttemptWaitModel(
            wait_id=wait_id,
            task_id=ids.task_id,
            flow_id=ids.flow_id,
            assignment_id=parent_assignment.assignment_id,
            attempt_id=parent_attempt.attempt_id,
            source_dispatch_id=parent_dispatch.dispatch_id,
            sequential_child_assignment_id=child_assignment.assignment_id,
            human_request_id=None,
            command_run_id=None,
            created_at=created_at,
        )
    )
    await session.commit()
    return wait_id


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


__all__ = []
