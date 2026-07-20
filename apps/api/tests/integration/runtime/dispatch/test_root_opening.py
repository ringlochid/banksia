from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any, cast

import pytest
from autoclaw.config import CodexSettings, Settings
from autoclaw.definitions.contracts.registry import NetworkAccess
from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.persistence.models import (
    DispatchCapabilitySetModel,
    DispatchPromptRefsModel,
    DispatchTurnModel,
    FlowModel,
    FlowStartSourceModel,
)
from autoclaw.runtime.dispatch.preparation import DispatchOpeningDependencies
from autoclaw.runtime.launch.continuation import open_root_dispatch
from autoclaw.runtime.launch.persistence.runtime import persist_bootstrap_runtime_from_precomputed
from autoclaw.runtime.observability import operator_trace
from autoclaw.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    DispatchStartDue,
    FlowStartCommitted,
)
from autoclaw.runtime.post_commit.bootstrap import read_dispatch_start_page, read_flow_start_page
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker
from tests.helpers.launch_foundation import (
    build_launch_foundation_definitions,
    build_launch_foundation_input,
    seed_launch_foundation_catalog,
)
from tests.helpers.sqlite_runtime import (
    SyncSessionAdapter,
    create_runtime_schema_engine,
)


@pytest.mark.parametrize(
    ("network_access", "expected_native_access", "expected_native_source"),
    (
        (None, "full", "default"),
        (NetworkAccess.DENY, "restricted", "controller"),
    ),
)
async def test_root_start_materializes_then_commits_one_starting_dispatch(
    tmp_path: Path,
    network_access: NetworkAccess | None,
    expected_native_access: str,
    expected_native_source: str,
) -> None:
    engine = create_runtime_schema_engine(tmp_path, name="root-opening.sqlite")
    role, policy, workflow = build_launch_foundation_definitions()
    if network_access is not None:
        policy = policy.model_copy(
            update={
                "capabilities": policy.capabilities.model_copy(
                    update={"network_access": network_access}
                )
            }
        )
    assert workflow.root.provider is not None
    bootstrap_input = build_launch_foundation_input(
        tmp_path,
        role=role,
        policy=policy,
        workflow=workflow,
    )
    with engine.begin() as connection:
        seed_launch_foundation_catalog(
            connection,
            role=role,
            policy=policy,
            workflow=workflow,
        )
    publisher = CapturedRuntimeEffectPublisher(should_accept=False)
    dependencies = _opening_dependencies(workflow.root.provider.kind, publisher)
    sync_factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)

    def session_context() -> AbstractAsyncContextManager[AsyncSession]:
        return cast(AbstractAsyncContextManager[AsyncSession], SyncSessionAdapter(sync_factory))

    try:
        async with SyncSessionAdapter(sync_factory) as session:
            async_session = cast(AsyncSession, session)
            await persist_bootstrap_runtime_from_precomputed(async_session, bootstrap_input)
            root_page = await read_flow_start_page(session_context, None, 2)

            first = await open_root_dispatch(
                async_session,
                signal=FlowStartCommitted("flow.task.launch-foundation"),
                dependencies=dependencies,
            )
            duplicate = await open_root_dispatch(
                async_session,
                signal=FlowStartCommitted("flow.task.launch-foundation"),
                dependencies=dependencies,
            )

            assert first.outcome == "opened"
            assert duplicate.outcome == "skipped"
            assert await session.scalar(select(func.count()).select_from(DispatchTurnModel)) == 1
            dispatch = await session.scalar(select(DispatchTurnModel))
            refs = await session.scalar(select(DispatchPromptRefsModel))
            capabilities = await session.scalar(select(DispatchCapabilitySetModel))
            source = await session.scalar(select(FlowStartSourceModel))
            flow = await session.scalar(select(FlowModel))
            starting_page = await read_dispatch_start_page(session_context, None, 2)
            trace = await operator_trace(async_session, bootstrap_input.task_id)
    finally:
        engine.dispose()

    _assert_root_opening_result(
        dispatch=dispatch,
        refs=refs,
        capabilities=capabilities,
        source=source,
        flow=flow,
        root_page=root_page,
        starting_page=starting_page,
        trace=trace,
        publisher=publisher,
        tmp_path=tmp_path,
        network_access=network_access,
        expected_native_access=expected_native_access,
        expected_native_source=expected_native_source,
    )


async def test_root_start_route_failure_pauses_without_consuming_source(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path, name="root-route-failure.sqlite")
    role, policy, workflow = build_launch_foundation_definitions()
    assert workflow.root.provider is not None
    bootstrap_input = build_launch_foundation_input(
        tmp_path,
        role=role,
        policy=policy,
        workflow=workflow,
    )
    with engine.begin() as connection:
        seed_launch_foundation_catalog(
            connection,
            role=role,
            policy=policy,
            workflow=workflow,
        )
    dependencies = DispatchOpeningDependencies.create(
        settings=Settings(),
        available_adapter_kinds={workflow.root.provider.kind},
        post_commit_publisher=CapturedRuntimeEffectPublisher(),
    )
    sync_factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with SyncSessionAdapter(sync_factory) as session:
            async_session = cast(AsyncSession, session)
            await persist_bootstrap_runtime_from_precomputed(async_session, bootstrap_input)
            result = await open_root_dispatch(
                async_session,
                signal=FlowStartCommitted("flow.task.launch-foundation"),
                dependencies=dependencies,
            )
            count = await session.scalar(select(func.count()).select_from(DispatchTurnModel))
            source = await session.scalar(select(FlowStartSourceModel))
            flow = await session.scalar(select(FlowModel))
    finally:
        engine.dispose()

    assert result.outcome == "paused"
    assert count == 0
    assert source is not None and source.successor_dispatch_id is None
    assert flow is not None and flow.status == "paused"
    assert flow.pause_reason == "runtime_transition_failed"


def _assert_root_opening_result(
    *,
    dispatch: DispatchTurnModel | None,
    refs: DispatchPromptRefsModel | None,
    capabilities: DispatchCapabilitySetModel | None,
    source: FlowStartSourceModel | None,
    flow: FlowModel | None,
    root_page: Any,
    starting_page: Any,
    trace: Any,
    publisher: CapturedRuntimeEffectPublisher,
    tmp_path: Path,
    network_access: NetworkAccess | None,
    expected_native_access: str,
    expected_native_source: str,
) -> None:
    assert dispatch is not None and dispatch.status == "starting"
    assert dispatch.opened_reason == "root"
    assert dispatch.provider_selection_basis == "explicit"
    assert dispatch.provider_start_retry_kind == "initial"
    assert refs is not None and refs.dynamic_input_version == 1
    assert capabilities is not None
    assert capabilities.provider_native_access == expected_native_access
    assert capabilities.provider_native_access_source == expected_native_source
    assert capabilities.network_access == (network_access or NetworkAccess.ALLOW).value
    assert capabilities.network_access_source == (
        "policy_definition" if network_access is not None else "default"
    )
    assert source is not None and source.successor_dispatch_id == dispatch.dispatch_id
    assert flow is not None and flow.current_dispatch_id == dispatch.dispatch_id
    assert root_page.sources == (FlowStartCommitted("flow.task.launch-foundation"),)
    assert dispatch.next_provider_start_at is not None
    assert starting_page.sources == (
        DispatchStartDue(
            dispatch.dispatch_id,
            dispatch.provider_start_revision,
            dispatch.next_provider_start_at,
        ),
    )
    assert tuple(item.dispatch_id for item in trace.dispatch_history) == (dispatch.dispatch_id,)
    assert trace.dispatch_history[0].status == "starting"
    assert trace.dispatch_history[0].effective_capabilities.provider_native_access.effective == (
        expected_native_access
    )
    assert trace.graph_nodes
    request_text = (tmp_path / "task-root" / refs.input_logical_path).read_text(encoding="utf-8")
    assert '"kind": "root_start"' in request_text
    assert f'"dispatch_id": "{dispatch.dispatch_id}"' in request_text
    assert publisher.signals == ()


def _opening_dependencies(
    provider_kind: ProviderKind,
    publisher: CapturedRuntimeEffectPublisher,
) -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(codex=CodexSettings(enabled=True)),
        available_adapter_kinds={provider_kind},
        post_commit_publisher=publisher,
    )
