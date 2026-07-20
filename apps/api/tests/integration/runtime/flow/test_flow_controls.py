from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from autoclaw.config import CodexSettings, RuntimeSettings, Settings
from autoclaw.definitions.contracts.registry import PolicyDefinitionInput
from autoclaw.definitions.contracts.workflow import NodeKind, ProviderKind
from autoclaw.persistence.models import (
    AttemptModel,
    CommandRunModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
    FlowWaitModel,
    HumanRequestModel,
    PolicyRevisionModel,
    TaskEventModel,
)
from autoclaw.runtime.command_run.service import cancel_command_run
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.dispatch.preparation import DispatchOpeningDependencies
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.flow.service import (
    cancel_runtime_flow,
    continue_runtime_flow,
    list_runtime_flows,
    pause_runtime_flow,
    runtime_flow_read,
)
from autoclaw.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from autoclaw.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    CommandRunCancellationRequested,
    DispatchCleanupRequested,
    DispatchStartDue,
    HumanRequestTerminal,
)
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import (
    SessionFactory,
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
            await session.execute(
                update(FlowModel)
                .where(FlowModel.task_id == ids.task_id)
                .values(
                    status="completed",
                    terminal_outcome="blocked",
                    current_dispatch_id=None,
                )
            )
            await session.commit()
        async with session_factory() as session:
            flow = await runtime_flow_read(cast(AsyncSession, session), ids.task_id)
            page = await list_runtime_flows(cast(AsyncSession, session))

    assert flow.status.value == "completed"
    assert flow.terminal_outcome == "blocked"
    assert flow.current_dispatch is None
    assert len(page.items) == 1 and page.items[0].terminal_outcome == "blocked"


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
            wait = await session.get(FlowWaitModel, ids.flow_id)
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
        await _enable_target_policy(session_factory)
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
        await _enable_target_policy(session_factory)
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
            wait = await session.get(FlowWaitModel, ids.flow_id)

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
            wait = await session.get(FlowWaitModel, ids.flow_id)
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
                        "options": [{"id": "a", "title": "A"}],
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
    return cast(str, result.model_dump()["run_id"])


async def _enable_target_policy(session_factory: SessionFactory) -> None:
    async with session_factory() as session:
        policy = await session.get(PolicyRevisionModel, "policy-revision.target.1")
        assert policy is not None
        policy.content_json = PolicyDefinitionInput(
            id="policy.target",
            description="Allow exact-source continuation in the integration fixture.",
            applies_to=[NodeKind.ROOT, NodeKind.WORKER],
        ).model_dump(mode="json")
        await session.commit()


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
