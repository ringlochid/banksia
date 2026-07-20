from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

import httpx
from autoclaw.config import ClaudeSettings, CodexSettings, RuntimeSettings, Settings
from autoclaw.definitions.contracts import WorkflowDefinitionInput
from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.definitions.registry.task_start import (
    preview_task_compose,
    start_task_from_definition,
)
from autoclaw.main import create_app
from autoclaw.persistence.models import CompiledPlanModel, TaskModel
from autoclaw.persistence.session import get_db_session
from autoclaw.runtime.contracts import TaskComposePreviewResponse, TaskStartRequest
from autoclaw.runtime.dispatch.preparation import DispatchOpeningDependencies
from autoclaw.runtime.flow.reads import read_runtime_flow
from autoclaw.runtime.observability import operator_snapshot
from sqlalchemy import Engine, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker
from tests.helpers.launch_foundation import (
    build_launch_foundation_definitions,
    seed_launch_foundation_catalog,
)
from tests.helpers.sqlite_runtime import (
    SyncSessionAdapter,
    create_runtime_schema_engine,
)


async def test_task_compose_preview_http_reuses_current_truth_without_creating_runtime(
    tmp_path: Path,
) -> None:
    async with _current_registry_session(tmp_path, suffix="ready") as session:
        before = await _runtime_row_counts(session)
        app = create_app(should_enable_mcp_mounts=False)
        app.state.dispatch_opening_dependencies = DispatchOpeningDependencies.create(
            settings=_preview_settings(tmp_path),
            available_adapter_kinds=set(ProviderKind),
            post_commit_publisher=app.state.runtime_effect_publisher,
        )

        async def same_session() -> AsyncIterator[AsyncSession]:
            yield session

        app.dependency_overrides[get_db_session] = same_session
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 43125)),
            base_url="http://127.0.0.1:18125",
        ) as client:
            ready_http = await client.post(
                "/authoring/task-compose/preview",
                json=_task_start_request("preview-only").model_dump(mode="json"),
            )
            invalid_http = await client.post(
                "/authoring/task-compose/preview",
                json=_task_start_request(
                    "missing-workflow",
                    workflow_key="does-not-exist",
                ).model_dump(mode="json"),
            )
            malformed_http = await client.post(
                "/authoring/task-compose/preview",
                json={
                    **_task_start_request("malformed-preview").model_dump(mode="json"),
                    "unexpected": True,
                },
            )
            app.state.dispatch_opening_dependencies = DispatchOpeningDependencies.create(
                settings=_preview_settings(tmp_path),
                available_adapter_kinds={ProviderKind.CLAUDE},
                post_commit_publisher=app.state.runtime_effect_publisher,
            )
            unavailable_http = await client.post(
                "/authoring/task-compose/preview",
                json=_task_start_request("unavailable-adapter").model_dump(mode="json"),
            )
        after = await _runtime_row_counts(session)

    assert ready_http.status_code == 200
    response = TaskComposePreviewResponse.model_validate(ready_http.json())
    assert response.status == "ready"
    assert response.errors == ()
    assert response.nodes
    assert all(
        node.provider_resolution.resolved_provider == ProviderKind.CODEX for node in response.nodes
    )
    assert all(node.provider_resolution.selection_basis == "explicit" for node in response.nodes)
    assert all(node.provider_native_access.source == "default" for node in response.nodes)
    assert all(node.network_access.source == "default" for node in response.nodes)
    assert invalid_http.status_code == 200
    assert invalid_http.json()["status"] == "invalid"
    assert invalid_http.json()["errors"][0]["kind"] == "cross_reference"
    assert malformed_http.status_code == 400
    assert malformed_http.json()["code"] == "invalid_request_shape"
    assert unavailable_http.status_code == 200
    assert unavailable_http.json()["status"] == "invalid"
    assert unavailable_http.json()["errors"][0]["code"] == "provider_adapter_unavailable"
    assert before == after == (0, 0)
    assert not (tmp_path / "data" / "tasks" / "_task-compose-preview").exists()


async def test_task_compose_preview_resolves_an_omitted_provider_from_the_default(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        claude=ClaudeSettings(enabled=True),
        runtime=RuntimeSettings(default_provider=ProviderKind.CLAUDE),
    )
    async with _current_registry_session(
        tmp_path,
        suffix="default-provider",
        omit_provider=True,
    ) as session:
        response = await preview_task_compose(
            session,
            _task_start_request("default-provider"),
            settings=settings,
            available_adapter_kinds={ProviderKind.CLAUDE},
        )

    assert response.status == "ready"
    assert response.errors == ()
    assert response.nodes
    assert all(
        node.provider_resolution.requested_provider == ProviderKind.CLAUDE
        and node.provider_resolution.resolved_provider == ProviderKind.CLAUDE
        and node.provider_resolution.selection_basis == "default"
        for node in response.nodes
    )


async def test_task_compose_preview_returns_bounded_cross_reference_error(
    tmp_path: Path,
) -> None:
    request = _task_start_request("missing-workflow", workflow_key="does-not-exist")
    async with _current_registry_session(tmp_path, suffix="invalid") as session:
        response = await preview_task_compose(
            session,
            request,
            settings=_preview_settings(tmp_path),
            available_adapter_kinds=set(ProviderKind),
        )

    assert response.status == "invalid"
    assert response.nodes == ()
    assert len(response.errors) == 1
    assert response.errors[0].kind == "cross_reference"


async def test_runtime_read_and_snapshot_use_controller_rows_before_first_dispatch(
    tmp_path: Path,
) -> None:
    async with _current_registry_session(tmp_path, suffix="runtime-read") as session:
        started = await start_task_from_definition(
            _task_start_request("runtime-read-before-dispatch"),
            data_dir=tmp_path / "data",
            session=session,
        )
        flow = await read_runtime_flow(session, started.task_id)
        snapshot = await operator_snapshot(session, started.task_id)

    assert flow.status == "running"
    assert flow.current_node_key == "root"
    assert flow.active_assignment_id is not None
    assert flow.active_attempt_id is not None
    assert flow.current_dispatch is None
    assert flow.latest_dispatch_id is None
    assert flow.watchdog_recovery_count == 0
    assert snapshot.flow == flow
    assert snapshot.stream_head_event_id is not None
    assert tuple(path.kind for path in snapshot.current_paths) == ("manifest",)


@asynccontextmanager
async def _current_registry_session(
    tmp_path: Path,
    *,
    suffix: str,
    omit_provider: bool = False,
) -> AsyncIterator[AsyncSession]:
    engine: Engine = create_runtime_schema_engine(tmp_path, name=f"preview-{suffix}.sqlite")
    role, policy, workflow = build_launch_foundation_definitions()
    if omit_provider:
        workflow_content = workflow.model_dump(mode="json")
        workflow_content["root"]["provider"] = None
        workflow = WorkflowDefinitionInput.model_validate(workflow_content)
    with engine.begin() as connection:
        seed_launch_foundation_catalog(
            connection,
            role=role,
            policy=policy,
            workflow=workflow,
        )
    sync_factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with SyncSessionAdapter(sync_factory) as session:
            yield cast(AsyncSession, session)
    finally:
        engine.dispose()


def _task_start_request(
    task_key: str,
    *,
    workflow_key: str = "workflow.target",
) -> TaskStartRequest:
    return TaskStartRequest.model_validate(
        {
            "task": {
                "key": task_key,
                "title": "Task compose preview",
                "summary": "Resolve current definitions without reserving runtime.",
            },
            "workflow": {"key": workflow_key},
        }
    )


def _preview_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        codex=CodexSettings(enabled=True),
        runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
    )


async def _runtime_row_counts(session: AsyncSession) -> tuple[int, int]:
    task_count = await session.scalar(select(func.count()).select_from(TaskModel))
    compiled_plan_count = await session.scalar(select(func.count()).select_from(CompiledPlanModel))
    return int(task_count or 0), int(compiled_plan_count or 0)
