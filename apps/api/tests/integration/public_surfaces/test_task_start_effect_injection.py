from __future__ import annotations

import argparse
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

import banksia.interfaces.cli as cli
import banksia.interfaces.http.routers.tasks as tasks_router_module
import banksia.interfaces.mcp.operator.task_start as operator_task_start_module
import httpx
import pytest
from banksia.config import CodexSettings, RuntimeSettings, Settings, get_settings
from banksia.interfaces.mcp.operator.server import (
    OperatorEffectPublishers,
    create_operator_mcp_server,
)
from banksia.main import create_app
from banksia.persistence.session import get_db_session
from banksia.providers import ProviderKind
from banksia.runtime.contracts import TaskStartRequest, TaskStartResponse
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.post_commit import CapturedRuntimeEffectPublisher
from mcp.types import CallToolResult
from sqlalchemy.ext.asyncio import AsyncSession


async def _fake_session() -> AsyncIterator[AsyncSession]:
    yield cast(AsyncSession, object())


async def test_http_task_start_injects_dispatch_dependencies_and_default_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependencies = _dependencies(tmp_path)
    captured: dict[str, object] = {}

    async def capture_start(
        request: TaskStartRequest,
        *,
        session: AsyncSession,
        dependencies: DispatchOpeningDependencies,
        default_workspace: Path | None,
    ) -> TaskStartResponse:
        captured.update(
            request=request,
            session=session,
            dependencies=dependencies,
            default_workspace=default_workspace,
        )
        return _response("t_01234567", tmp_path)

    monkeypatch.setattr(tasks_router_module, "start_task_service", capture_start)
    app = create_app(should_enable_mcp_mounts=False)
    app.state.dispatch_opening_dependencies = dependencies
    app.dependency_overrides[get_db_session] = _fake_session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 43125)),
        base_url="http://127.0.0.1:18125",
    ) as client:
        response = await client.post(
            "/tasks/start",
            json={"workflow": "reviewed-delivery", "prompt": "Do the work."},
        )

    assert response.status_code == 200, response.text
    assert captured["dependencies"] is dependencies
    assert captured["default_workspace"] == tmp_path
    request = cast(TaskStartRequest, captured["request"])
    assert request.workspace is None


async def test_http_task_start_uses_workspace_written_by_init(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    captured: dict[str, object] = {}

    async def capture_start(
        request: TaskStartRequest,
        *,
        session: AsyncSession,
        dependencies: DispatchOpeningDependencies,
        default_workspace: Path | None,
    ) -> TaskStartResponse:
        captured["default_workspace"] = default_workspace
        return _response("t_01234567", workspace)

    await cli.cmd_init(
        argparse.Namespace(
            config=str(config_path),
            data_dir=str(data_dir),
            database_url=None,
            workspace=str(workspace),
            host="127.0.0.1",
            port=18125,
            log_level="WARNING",
            force=True,
            skip_db_upgrade=True,
            json=False,
        )
    )
    monkeypatch.setattr(tasks_router_module, "start_task_service", capture_start)
    with cli.command_env(config_path=config_path):
        get_settings.cache_clear()
        app = create_app(should_enable_mcp_mounts=False)
        app.dependency_overrides[get_db_session] = _fake_session
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 43125)),
            base_url="http://127.0.0.1:18125",
        ) as client:
            response = await client.post(
                "/tasks/start",
                json={"workflow": "reviewed-delivery", "prompt": "Do the work."},
            )

    assert response.status_code == 200, response.text
    assert captured["default_workspace"] == workspace.resolve()


async def test_http_task_start_without_request_or_configured_workspace_returns_422() -> None:
    dependencies = _dependencies(None)
    app = create_app(should_enable_mcp_mounts=False)
    app.state.dispatch_opening_dependencies = dependencies
    app.dependency_overrides[get_db_session] = _fake_session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 43125)),
        base_url="http://127.0.0.1:18125",
    ) as client:
        response = await client.post(
            "/tasks/start",
            json={"workflow": "reviewed-delivery", "prompt": "Do the work."},
        )

    assert response.status_code == 422
    assert response.json() == {
        "ok": False,
        "code": "invalid_task_root",
        "summary": "Task start requires an explicit workspace",
        "retryable": False,
        "field_path": None,
        "suggested_next_step": (
            "Set the controller workspace or resend TaskStartRequest with workspace."
        ),
    }


@pytest.mark.parametrize(
    ("payload", "field_path"),
    [
        ({"workflow": "reviewed-delivery", "prompt": 7}, "prompt"),
        (
            {
                "workflow": "reviewed-delivery",
                "prompt": "Do the work.",
                "files": [{"path": 7}],
            },
            "files.0.path",
        ),
        (
            {
                "workflow": "reviewed-delivery",
                "prompt": "Do the work.",
                "files": [{"path": "brief.md", "description": 7}],
            },
            "files.0.description",
        ),
    ],
)
async def test_http_task_start_wrong_types_return_typed_request_failure(
    tmp_path: Path,
    payload: dict[str, object],
    field_path: str,
) -> None:
    app = create_app(should_enable_mcp_mounts=False)
    app.state.dispatch_opening_dependencies = _dependencies(tmp_path)
    app.dependency_overrides[get_db_session] = _fake_session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 43125)),
        base_url="http://127.0.0.1:18125",
    ) as client:
        response = await client.post("/tasks/start", json=payload)

    assert response.status_code == 400
    assert response.json() == {
        "ok": False,
        "code": "invalid_request_shape",
        "summary": "request shape does not match the canonical runtime surface",
        "retryable": False,
        "field_path": field_path,
        "suggested_next_step": (
            "Reread the canonical request shape and resend the request with only the live "
            "required fields."
        ),
    }


async def test_operator_task_start_uses_flat_json_fields_and_same_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependencies = _dependencies(tmp_path)
    captured: dict[str, object] = {}

    async def capture_start(
        request: TaskStartRequest,
        *,
        dependencies: DispatchOpeningDependencies,
        default_workspace: Path | None,
    ) -> TaskStartResponse:
        captured.update(
            request=request,
            dependencies=dependencies,
            default_workspace=default_workspace,
        )
        return _response("t_01234567", tmp_path)

    monkeypatch.setattr(operator_task_start_module, "start_task_service", capture_start)
    server = create_operator_mcp_server(
        effect_publishers=OperatorEffectPublishers(
            dispatch_opening_dependencies=dependencies,
        )
    )

    await server.call_tool(
        "task_start",
        {
            "workflow": "reviewed-delivery",
            "prompt": "Do the work.",
            "files": [{"path": "brief.md", "description": "Input brief."}],
        },
    )

    assert captured["dependencies"] is dependencies
    assert captured["default_workspace"] == tmp_path
    request = cast(TaskStartRequest, captured["request"])
    assert request.workflow == "reviewed-delivery"
    assert request.prompt == "Do the work."
    assert request.workspace is None
    assert request.files[0].path == "brief.md"


@pytest.mark.parametrize(
    ("arguments", "field_path"),
    [
        ({"workflow": "reviewed-delivery", "prompt": 7}, "prompt"),
        (
            {
                "workflow": "reviewed-delivery",
                "prompt": "Do the work.",
                "files": [{"path": 7}],
            },
            "files.0.path",
        ),
        (
            {
                "workflow": "reviewed-delivery",
                "prompt": "Do the work.",
                "files": [{"path": "brief.md", "description": 7}],
            },
            "files.0.description",
        ),
    ],
)
async def test_operator_task_start_wrong_types_return_typed_request_failure(
    tmp_path: Path,
    arguments: dict[str, object],
    field_path: str,
) -> None:
    server = create_operator_mcp_server(
        effect_publishers=OperatorEffectPublishers(
            dispatch_opening_dependencies=_dependencies(tmp_path),
        )
    )

    result = cast(CallToolResult, await server.call_tool("task_start", arguments))

    assert result.isError is True
    assert result.structuredContent == {
        "ok": False,
        "code": "invalid_request_shape",
        "summary": "request shape does not match the canonical runtime surface",
        "retryable": False,
        "field_path": field_path,
        "suggested_next_step": (
            "Reread the canonical request shape and resend the request with only the live "
            "required fields."
        ),
    }


def _dependencies(workspace: Path | None) -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            controller_workspace=workspace,
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=CapturedRuntimeEffectPublisher(),
    )


def _response(task_id: str, workspace: Path) -> TaskStartResponse:
    return TaskStartResponse(
        task_id=task_id,
        workflow="reviewed-delivery",
        workflow_revision=1,
        workspace=workspace,
        manifest=Path(".banksia") / task_id / "manifest.md",
    )
