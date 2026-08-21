from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from xml.etree import ElementTree

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from oh_my_subagents.config import CodexSettings, RuntimeSettings, Settings
from oh_my_subagents.persistence.models import (
    AttemptModel,
    DispatchCapabilitySetModel,
    DispatchRequestModel,
    DispatchTurnModel,
    TaskModel,
    TaskStartSourceModel,
)
from oh_my_subagents.providers import ManagedSandboxMode, NetworkAccess, ProviderKind
from oh_my_subagents.runtime.dispatch.preparation import DispatchOpeningDependencies
from oh_my_subagents.runtime.launch.continuation import open_root_dispatch
from oh_my_subagents.runtime.launch.persistence.runtime import (
    persist_bootstrap_runtime_from_precomputed,
)
from oh_my_subagents.runtime.observability import support_task_trace
from oh_my_subagents.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    DispatchStartDue,
    TaskStartCommitted,
)
from oh_my_subagents.runtime.post_commit.dispatch_startup import (
    read_dispatch_start_page,
    read_task_start_page,
)
from tests.helpers.launch_foundation import (
    build_launch_foundation_input,
    build_launch_foundation_workflow_revision,
    seed_launch_foundation_workflow,
)
from tests.helpers.sqlite_runtime import (
    SyncSessionAdapter,
    create_runtime_schema_engine,
)


@dataclass(frozen=True, slots=True)
class _RootOpeningObservation:
    dispatch: DispatchTurnModel | None
    request: DispatchRequestModel | None
    capabilities: DispatchCapabilitySetModel | None
    source: TaskStartSourceModel | None
    task: TaskModel | None
    attempt: AttemptModel | None
    task_start_page: Any
    dispatch_start_page: Any
    trace: Any
    published_signal_count: int


@pytest.mark.parametrize(
    ("network_access", "expected_native_access", "expected_native_source"),
    (
        (None, "full", "default"),
        (NetworkAccess.DENY, "restricted", "controller"),
    ),
)
async def test_root_start_persists_then_commits_one_starting_dispatch(
    tmp_path: Path,
    network_access: NetworkAccess | None,
    expected_native_access: str,
    expected_native_source: str,
) -> None:
    engine = create_runtime_schema_engine(tmp_path, name="root-opening.sqlite")
    workflow_revision = build_launch_foundation_workflow_revision()
    assert workflow_revision.workflow.lead.provider is not None
    bootstrap_input = build_launch_foundation_input(
        tmp_path,
        workflow_revision=workflow_revision,
    )
    with engine.begin() as connection:
        seed_launch_foundation_workflow(
            connection,
            workflow_revision=workflow_revision,
        )
    publisher = CapturedRuntimeEffectPublisher(should_accept=False)
    dependencies = _opening_dependencies(
        ProviderKind(workflow_revision.workflow.lead.provider.kind),
        publisher,
        network_access=network_access,
    )
    sync_factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)

    def session_context() -> AbstractAsyncContextManager[AsyncSession]:
        return cast(AbstractAsyncContextManager[AsyncSession], SyncSessionAdapter(sync_factory))

    try:
        async with SyncSessionAdapter(sync_factory) as session:
            async_session = cast(AsyncSession, session)
            await persist_bootstrap_runtime_from_precomputed(async_session, bootstrap_input)
            root_page = await read_task_start_page(session_context, None, 2)

            first = await open_root_dispatch(
                async_session,
                signal=TaskStartCommitted(bootstrap_input.task_id),
                dependencies=dependencies,
            )
            duplicate = await open_root_dispatch(
                async_session,
                signal=TaskStartCommitted(bootstrap_input.task_id),
                dependencies=dependencies,
            )

            assert first.outcome == "opened"
            assert duplicate.outcome == "skipped"
            assert await session.scalar(select(func.count()).select_from(DispatchTurnModel)) == 1
            dispatch = await session.scalar(select(DispatchTurnModel))
            dispatch_request = await session.scalar(select(DispatchRequestModel))
            capabilities = await session.scalar(select(DispatchCapabilitySetModel))
            source = await session.scalar(select(TaskStartSourceModel))
            task = await session.scalar(select(TaskModel))
            attempt = await session.scalar(select(AttemptModel))
            starting_page = await read_dispatch_start_page(session_context, None, 2)
            trace = await support_task_trace(async_session, bootstrap_input.task_id)
    finally:
        engine.dispose()

    _assert_root_opening_result(
        observation=_RootOpeningObservation(
            dispatch=dispatch,
            request=dispatch_request,
            capabilities=capabilities,
            source=source,
            task=task,
            attempt=attempt,
            task_start_page=root_page,
            dispatch_start_page=starting_page,
            trace=trace,
            published_signal_count=len(publisher.signals),
        ),
        task_id=bootstrap_input.task_id,
        tmp_path=tmp_path,
        network_access=network_access,
        expected_native_access=expected_native_access,
        expected_native_source=expected_native_source,
    )


async def test_root_start_route_failure_pauses_without_consuming_source(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path, name="root-route-failure.sqlite")
    workflow_revision = build_launch_foundation_workflow_revision()
    assert workflow_revision.workflow.lead.provider is not None
    bootstrap_input = build_launch_foundation_input(
        tmp_path,
        workflow_revision=workflow_revision,
    )
    with engine.begin() as connection:
        seed_launch_foundation_workflow(
            connection,
            workflow_revision=workflow_revision,
        )
    dependencies = DispatchOpeningDependencies.create(
        settings=Settings(),
        available_adapter_kinds={ProviderKind(workflow_revision.workflow.lead.provider.kind)},
        post_commit_publisher=CapturedRuntimeEffectPublisher(),
    )
    sync_factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with SyncSessionAdapter(sync_factory) as session:
            async_session = cast(AsyncSession, session)
            await persist_bootstrap_runtime_from_precomputed(async_session, bootstrap_input)
            result = await open_root_dispatch(
                async_session,
                signal=TaskStartCommitted(bootstrap_input.task_id),
                dependencies=dependencies,
            )
            count = await session.scalar(select(func.count()).select_from(DispatchTurnModel))
            source = await session.scalar(select(TaskStartSourceModel))
            task = await session.scalar(select(TaskModel))
            attempt = await session.scalar(select(AttemptModel))
    finally:
        engine.dispose()

    assert result.outcome == "paused"
    assert count == 0
    assert source is not None and source.successor_dispatch_id is None
    assert task is not None and task.status == "paused"
    assert task.pause_reason == "runtime_transition_failed"
    assert attempt is not None and attempt.current_dispatch_id is None


def _assert_root_opening_result(
    *,
    observation: _RootOpeningObservation,
    task_id: str,
    tmp_path: Path,
    network_access: NetworkAccess | None,
    expected_native_access: str,
    expected_native_source: str,
) -> None:
    dispatch = observation.dispatch
    assert dispatch is not None and dispatch.status == "starting"
    _assert_dispatch_provider_snapshot(
        dispatch,
        observation,
        network_access=network_access,
        expected_native_access=expected_native_access,
        expected_native_source=expected_native_source,
    )
    _assert_controller_startup_snapshot(observation, task_id=task_id)
    _assert_prompt_and_support_snapshot(
        observation,
        task_id=task_id,
        tmp_path=tmp_path,
        expected_native_access=expected_native_access,
    )


def _assert_dispatch_provider_snapshot(
    dispatch: DispatchTurnModel,
    observation: _RootOpeningObservation,
    *,
    network_access: NetworkAccess | None,
    expected_native_access: str,
    expected_native_source: str,
) -> None:
    assert dispatch.opened_reason == "root"
    assert dispatch.provider_selection_basis == "explicit"
    assert dispatch.model_source == "provider_configuration"
    assert dispatch.effort_source == "provider_configuration"
    assert dispatch.gateway_profile_source is None
    assert dispatch.provider_start_retry_kind == "initial"
    request = observation.request
    assert request is not None
    assert request.instructions.endswith("\n")
    assert "\r" not in request.instructions
    capabilities = observation.capabilities
    assert capabilities is not None
    assert capabilities.provider_kind == "codex"
    assert capabilities.provider_native_access == expected_native_access
    assert capabilities.provider_native_access_source == expected_native_source
    assert capabilities.network_access == (network_access or NetworkAccess.ALLOW).value
    assert capabilities.network_access_source == (
        "controller" if network_access is not None else "default"
    )
    assert capabilities.requested_human_request_source == "default"
    assert {
        capabilities.human_direction_source,
        capabilities.human_approval_source,
        capabilities.human_input_source,
        capabilities.human_review_source,
    } == {"default"}
    assert capabilities.requested_command_run_source == "default"


def _assert_controller_startup_snapshot(
    observation: _RootOpeningObservation,
    *,
    task_id: str,
) -> None:
    dispatch = observation.dispatch
    assert dispatch is not None
    assert observation.source is not None
    assert observation.source.successor_dispatch_id == dispatch.dispatch_id
    assert observation.task is not None and observation.task.status == "running"
    assert observation.attempt is not None
    assert observation.attempt.current_dispatch_id == dispatch.dispatch_id
    assert observation.task_start_page.sources == (TaskStartCommitted(task_id),)
    assert dispatch.next_provider_start_at is not None
    assert observation.dispatch_start_page.sources == (
        DispatchStartDue(
            dispatch.dispatch_id,
            dispatch.provider_start_revision,
            dispatch.next_provider_start_at,
        ),
    )


def _assert_prompt_and_support_snapshot(
    observation: _RootOpeningObservation,
    *,
    task_id: str,
    tmp_path: Path,
    expected_native_access: str,
) -> None:
    dispatch = observation.dispatch
    request = observation.request
    assert dispatch is not None and request is not None
    trace = observation.trace
    assert len(trace.entries) == 1
    trace_dispatch = trace.entries[0]
    assert trace_dispatch.kind == "dispatch"
    assert trace_dispatch.dispatch_id == dispatch.dispatch_id
    assert trace_dispatch.status == "starting"
    assert (
        trace_dispatch.effective_capabilities.provider_native_access.effective
        == expected_native_access
    )
    assert len(trace.team_members) == 1
    assert trace.team_members[0].is_task_lead is True
    assert trace.team_members[0].behavior == "contributor"
    assert trace.current_paths[0].path == f".banksia/{task_id}/manifest.md"
    request_text = request.input
    assert "\r" not in request_text
    request_root = ElementTree.fromstring(request_text)
    assert request_root.tag == "banksia_dispatch_request"
    assert request_root.find("continuation") is None
    assert request_root.findtext("dispatch/id") == dispatch.dispatch_id
    assert request_root.findtext("assignment/prompt")
    assert tuple(item.text for item in request_root.findall("available_actions/action")) == (
        "get_current_context",
        "set_work_plan",
        "checkpoint",
        "add_child",
    )
    assert not (tmp_path / "task-root" / "_runtime" / "dispatch").exists()
    assert observation.published_signal_count == 0


def _opening_dependencies(
    provider_kind: ProviderKind,
    publisher: CapturedRuntimeEffectPublisher,
    *,
    network_access: NetworkAccess | None,
) -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(
                managed_provider_sandbox_mode=(
                    ManagedSandboxMode.WORKSPACE_WRITE
                    if network_access is NetworkAccess.DENY
                    else ManagedSandboxMode.FULL_ACCESS
                ),
                managed_provider_network_access=network_access or NetworkAccess.ALLOW,
            ),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds={provider_kind},
        post_commit_publisher=publisher,
    )
