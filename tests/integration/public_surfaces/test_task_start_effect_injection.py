from __future__ import annotations

import argparse
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

import httpx
import pytest
from mcp.types import CallToolResult
from sqlalchemy.ext.asyncio import AsyncSession

import banksia.interfaces.cli as cli
import banksia.interfaces.http.routers.tasks as tasks_router_module
import banksia.interfaces.mcp.operator.task_start as operator_task_start_module
from banksia.config import CodexSettings, RuntimeSettings, Settings, get_settings
from banksia.interfaces.http.contracts.operation_failure import ProductFailureCode
from banksia.interfaces.http.runtime_exception_mapping import runtime_exception_failure
from banksia.interfaces.mcp.operator.server import (
    OperatorEffectPublishers,
    create_operator_mcp_server,
)
from banksia.main import create_app
from banksia.persistence.session import get_db_session
from banksia.providers import ProviderKind
from banksia.runtime.contracts import TaskStartRequest
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.contracts.task import TaskStartReceipt
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.post_commit import CapturedRuntimeEffectPublisher


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
    ) -> TaskStartReceipt:
        captured.update(
            request=request,
            session=session,
            dependencies=dependencies,
            default_workspace=default_workspace,
        )
        return _receipt("t_01234567", tmp_path)

    monkeypatch.setattr(tasks_router_module, "start_product_task", capture_start)
    app = create_app(should_enable_mcp_mounts=False)
    app.state.dispatch_opening_dependencies = dependencies
    app.dependency_overrides[get_db_session] = _fake_session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 43125)),
        base_url="http://127.0.0.1:18125",
    ) as client:
        response = await client.post(
            "/tasks",
            json={"workflow": "reviewed-delivery", "prompt": "Do the work."},
        )

    assert response.status_code == 202, response.text
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
    ) -> TaskStartReceipt:
        captured["default_workspace"] = default_workspace
        return _receipt("t_01234567", workspace)

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
    monkeypatch.setattr(tasks_router_module, "start_product_task", capture_start)
    with cli.command_env(config_path=config_path):
        get_settings.cache_clear()
        app = create_app(should_enable_mcp_mounts=False)
        app.dependency_overrides[get_db_session] = _fake_session
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 43125)),
            base_url="http://127.0.0.1:18125",
        ) as client:
            response = await client.post(
                "/tasks",
                json={"workflow": "reviewed-delivery", "prompt": "Do the work."},
            )

    assert response.status_code == 202, response.text
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
            "/tasks",
            json={"workflow": "reviewed-delivery", "prompt": "Do the work."},
        )

    assert response.status_code == 422
    assert response.json() == {
        "ok": False,
        "code": "invalid_request",
        "summary": "The request cannot be applied.",
        "retryable": False,
        "field_path": None,
        "suggested_next_step": (
            "Check the request fields against the current action and try again."
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
        response = await client.post("/tasks", json=payload)

    assert response.status_code == 400
    assert response.json() == {
        "ok": False,
        "code": "invalid_request",
        "summary": "The request contains an unsupported or invalid field.",
        "retryable": False,
        "field_path": field_path,
        "suggested_next_step": ("Correct the highlighted field and resend the request."),
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
    ) -> TaskStartReceipt:
        captured.update(
            request=request,
            dependencies=dependencies,
            default_workspace=default_workspace,
        )
        return _receipt("t_01234567", tmp_path)

    monkeypatch.setattr(operator_task_start_module, "start_product_task", capture_start)
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
        "code": "invalid_request",
        "summary": "The request contains an unsupported or invalid field.",
        "retryable": False,
        "field_path": field_path,
        "suggested_next_step": (
            "Check the tool's current input fields and resend the request with only supported "
            "values."
        ),
    }


@pytest.mark.parametrize("code", tuple(OperationFailureCode))
def test_every_runtime_failure_maps_to_closed_product_vocabulary_without_leaks(
    code: OperationFailureCode,
) -> None:
    _status_code, failure = runtime_exception_failure(
        RuntimeOperationError(
            code=code,
            summary="secret dispatch_id assignment_id team_revision controller detail",
            is_retryable=True,
            suggested_next_step="Reread the canonical runtime surface and internal manifest.",
        )
    )

    assert failure.code in ProductFailureCode
    serialized = json.dumps(failure.model_dump(mode="json"), sort_keys=True).casefold()
    for technical_term in (
        "dispatch_id",
        "assignment_id",
        "team_revision",
        "canonical runtime",
        "internal manifest",
    ):
        assert technical_term not in serialized


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


def _receipt(task_id: str, workspace: Path) -> TaskStartReceipt:
    return TaskStartReceipt(
        receipt_id=f"receipt.{task_id}",
        task_id=task_id,
        workflow_id="reviewed-delivery",
        workflow_revision=1,
        workspace=str(workspace),
        manifest=str(Path(".banksia") / task_id / "manifest.md"),
    )
