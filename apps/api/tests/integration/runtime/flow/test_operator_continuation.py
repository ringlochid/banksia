from __future__ import annotations

from pathlib import Path
from typing import cast
from xml.etree import ElementTree

import pytest
from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    AttemptModel,
    DispatchRequestModel,
    DispatchTurnModel,
    FlowModel,
    FlowStartSourceModel,
    HumanRequestModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.clock import utc_now
from banksia.runtime.contracts import HumanRequestResolveRequest
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.flow.continuation import continue_paused_flow
from banksia.runtime.human_request.service import resolve_human_request
from banksia.runtime.launch.persistence.runtime import persist_bootstrap_runtime_from_precomputed
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    RuntimeEffectPublisher,
    RuntimeEffectSignal,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker
from tests.helpers.executor_harness import (
    SessionFactory,
    seeded_executor,
)
from tests.helpers.launch_foundation import (
    build_launch_foundation_input,
    build_launch_foundation_workflow_revision,
    seed_launch_foundation_workflow,
)
from tests.helpers.lineage_seed import RuntimeIds
from tests.helpers.sqlite_runtime import (
    SyncSessionAdapter,
    create_runtime_schema_engine,
)


class _RaisingPublisher:
    def publish(self, signal: RuntimeEffectSignal) -> bool:
        del signal
        raise RuntimeError("post-commit publication unavailable")


async def test_continue_resumes_one_closed_lineage_tail_and_rejects_duplicate(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="operator-continue") as (
        _,
        session_factory,
        ids,
        _,
    ):
        expected_control_revision = await _pause_current_dispatch(session_factory, ids)
        async with session_factory() as session:
            result = await continue_paused_flow(
                cast(AsyncSession, session),
                task_id=ids.task_id,
                expected_active_flow_revision_id=ids.flow_revision_id,
                expected_control_revision=expected_control_revision,
                dependencies=_opening_dependencies(_RaisingPublisher()),
            )
            with pytest.raises(RuntimeOperationError) as duplicate_error:
                await continue_paused_flow(
                    cast(AsyncSession, session),
                    task_id=ids.task_id,
                    expected_active_flow_revision_id=ids.flow_revision_id,
                    expected_control_revision=expected_control_revision,
                    dependencies=_opening_dependencies(CapturedRuntimeEffectPublisher()),
                )
            flow = await session.get(FlowModel, ids.flow_id)
            attempt = await session.get(AttemptModel, ids.root_attempt_id)
            successor = await session.get(DispatchTurnModel, result.dispatch_id)
            dispatch_request = await session.get(DispatchRequestModel, result.dispatch_id)
            dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )

    assert result.outcome == "opened"
    assert flow is not None and flow.status == "running"
    assert attempt is not None and attempt.current_dispatch_id == result.dispatch_id
    assert flow.control_revision == expected_control_revision + 1
    assert flow.pause_reason is None
    assert successor is not None and successor.opened_reason == "operator_continue"
    assert successor.predecessor_dispatch_id == ids.current_dispatch_id
    assert dispatch_request is not None
    input_text = dispatch_request.input
    request_root = ElementTree.fromstring(input_text)
    assert request_root.findtext("continuation/trigger/kind") == "operator_continue"
    assert request_root.findtext("current_member/position") == "task_lead"
    assert ElementTree.fromstring(dispatch_request.instructions).find("task_lead") is not None
    assert duplicate_error.value.code == OperationFailureCode.CONFLICT
    assert dispatch_count == 4


async def test_continue_consumes_terminal_human_source_retained_while_paused(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="operator-human") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        workspace = tmp_path / "task-operator-human" / "workspace"
        (workspace / "decision.md").write_text("Decision context.", encoding="utf-8")
        (workspace / "constraints.md").write_text("Decision constraints.", encoding="utf-8")
        request_id = await _open_human_request(executor, ids)
        await _pause_waiting_flow(session_factory, ids)
        async with session_factory() as session:
            await resolve_human_request(
                cast(AsyncSession, session),
                task_id=ids.task_id,
                request_id=request_id,
                request=HumanRequestResolveRequest.model_validate(
                    {
                        "item_responses": {
                            "direction": {
                                "kind": "option",
                                "option_id": "a",
                            }
                        }
                    }
                ),
            )
        async with session_factory() as session:
            paused_flow = await session.get(FlowModel, ids.flow_id)
            assert paused_flow is not None
            expected_control_revision = paused_flow.control_revision
            result = await continue_paused_flow(
                cast(AsyncSession, session),
                task_id=ids.task_id,
                expected_active_flow_revision_id=ids.flow_revision_id,
                expected_control_revision=expected_control_revision,
                dependencies=_opening_dependencies(CapturedRuntimeEffectPublisher()),
            )
            source = await session.get(HumanRequestModel, request_id)
            successor = await session.get(DispatchTurnModel, result.dispatch_id)
            dispatch_request = await session.get(DispatchRequestModel, result.dispatch_id)

    assert result.outcome == "opened"
    assert source is not None and source.successor_dispatch_id == result.dispatch_id
    assert successor is not None and successor.opened_reason == "operator_continue"
    assert successor.assignment_id == ids.root_assignment_id
    assert successor.attempt_id == ids.root_attempt_id
    assert dispatch_request is not None
    input_text = dispatch_request.input
    request_root = ElementTree.fromstring(input_text)
    assert request_root.findtext("continuation/trigger/kind") == "human_result"
    assert request_root.findtext("continuation/trigger/source/request_id") == request_id
    file_nodes = request_root.findall("continuation/trigger/result/request/files/file")
    assert [(node.findtext("path"), node.findtext("description")) for node in file_nodes] == [
        ("decision.md", "Decision context."),
        ("constraints.md", "Decision constraints."),
    ]


async def test_continue_preparation_failure_preserves_existing_pause(tmp_path: Path) -> None:
    async with seeded_executor(tmp_path, suffix="operator-preparation-failure") as (
        _,
        session_factory,
        ids,
        _,
    ):
        expected_control_revision = await _pause_current_dispatch(session_factory, ids)
        async with session_factory() as session:
            with pytest.raises(RuntimeOperationError) as error:
                await continue_paused_flow(
                    cast(AsyncSession, session),
                    task_id=ids.task_id,
                    expected_active_flow_revision_id=ids.flow_revision_id,
                    expected_control_revision=expected_control_revision,
                    dependencies=DispatchOpeningDependencies.create(
                        settings=Settings(),
                        available_adapter_kinds={ProviderKind.CODEX},
                        post_commit_publisher=CapturedRuntimeEffectPublisher(),
                    ),
                )
            flow = await session.get(FlowModel, ids.flow_id)
            dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )

    assert error.value.code == OperationFailureCode.ILLEGAL_STATE
    assert flow is not None and flow.status == "paused"
    assert flow.control_revision == expected_control_revision
    assert dispatch_count == 3


async def test_pre_root_continue_consumes_flow_start_without_synthetic_predecessor(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path, name="pre-root-continue.sqlite")
    workflow_revision = build_launch_foundation_workflow_revision()
    bootstrap_input = build_launch_foundation_input(
        tmp_path,
        workflow_revision=workflow_revision,
    )
    with engine.begin() as connection:
        seed_launch_foundation_workflow(
            connection,
            workflow_revision=workflow_revision,
        )
    sync_factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with SyncSessionAdapter(sync_factory) as session:
            async_session = cast(AsyncSession, session)
            await persist_bootstrap_runtime_from_precomputed(async_session, bootstrap_input)
            flow = await session.scalar(select(FlowModel))
            assert flow is not None
            flow.status = "paused"
            flow.pause_reason = "runtime_transition_failed"
            flow.pause_details = {"source": "flow_start"}
            flow.paused_at = utc_now()
            flow.paused_by_actor_ref = "controller.runtime"
            flow.control_revision += 1
            await session.commit()
            expected_control_revision = flow.control_revision

            publisher = CapturedRuntimeEffectPublisher()
            result = await continue_paused_flow(
                async_session,
                task_id=flow.task_id,
                expected_active_flow_revision_id=cast(str, flow.active_flow_revision_id),
                expected_control_revision=expected_control_revision,
                dependencies=_opening_dependencies(publisher),
            )
            source = await session.scalar(select(FlowStartSourceModel))
            successor = await session.get(DispatchTurnModel, result.dispatch_id)
            dispatch_request = await session.get(DispatchRequestModel, result.dispatch_id)
            resumed_flow = await session.scalar(
                select(FlowModel)
                .where(FlowModel.flow_id == flow.flow_id)
                .execution_options(populate_existing=True)
            )
            resumed_attempt = await session.scalar(
                select(AttemptModel).where(AttemptModel.task_id == flow.task_id)
            )
    finally:
        engine.dispose()

    assert result.outcome == "opened"
    assert source is not None and source.successor_dispatch_id == result.dispatch_id
    assert successor is not None
    assert successor.opened_reason == "operator_continue"
    assert successor.predecessor_dispatch_id is None
    assert successor.flow_start_source_flow_id == flow.flow_id
    assert resumed_flow is not None
    assert resumed_flow.status == "running"
    assert resumed_attempt is not None
    assert resumed_attempt.current_dispatch_id == result.dispatch_id
    assert resumed_flow.control_revision == expected_control_revision + 1
    assert dispatch_request is not None
    request_root = ElementTree.fromstring(dispatch_request.input)
    assert request_root.findtext("continuation/trigger/kind") == "operator_continue"
    assert request_root.findtext("continuation/trigger/source/source_task_id") == flow.task_id
    assert len(publisher.signals) == 1


async def _pause_current_dispatch(
    session_factory: SessionFactory,
    ids: RuntimeIds,
) -> int:
    paused_at = utc_now()
    async with session_factory() as session:
        flow = await session.get(FlowModel, ids.flow_id)
        attempt = await session.get(AttemptModel, ids.root_attempt_id)
        dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
        assert flow is not None
        assert attempt is not None
        assert dispatch is not None
        dispatch.status = "closed"
        dispatch.closed_reason = "paused"
        dispatch.closed_at = paused_at
        flow.status = "paused"
        attempt.current_dispatch_id = None
        flow.pause_reason = "paused_by_operator"
        flow.pause_details = {"reason": "test"}
        flow.paused_at = paused_at
        flow.paused_by_actor_ref = "local_operator"
        flow.control_revision += 1
        await session.commit()
        return cast(int, flow.control_revision)


async def _pause_waiting_flow(session_factory: SessionFactory, ids: RuntimeIds) -> None:
    async with session_factory() as session:
        flow = await session.get(FlowModel, ids.flow_id)
        assert flow is not None
        flow.status = "paused"
        flow.pause_reason = "paused_by_operator"
        flow.pause_details = {"reason": "test"}
        flow.paused_at = utc_now()
        flow.paused_by_actor_ref = "local_operator"
        flow.control_revision += 1
        await session.commit()


async def _open_human_request(executor: NodeOperationExecutor, ids: RuntimeIds) -> str:
    opened = await executor.execute(
        scope=NodeOperationScope(task_id=ids.task_id, dispatch_id=ids.current_dispatch_id),
        operation_name="open_human_request",
        arguments={
            "request": {
                "kind": "direction",
                "summary": "Choose one exact direction.",
                "items": [
                    {
                        "id": "direction",
                        "prompt": "Which direction?",
                        "options": [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}],
                    }
                ],
                "files": [
                    {
                        "path": "decision.md",
                        "description": "Decision context.",
                    },
                    {
                        "path": "constraints.md",
                        "description": "Decision constraints.",
                    },
                ],
            }
        },
    )
    return cast(str, opened.model_dump()["request_id"])


def _opening_dependencies(
    publisher: RuntimeEffectPublisher,
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
