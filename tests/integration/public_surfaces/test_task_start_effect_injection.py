from __future__ import annotations

import argparse
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import oh_my_subagents.interfaces.cli as cli
import oh_my_subagents.interfaces.http.routers.tasks as tasks_router_module
from oh_my_subagents.config import CodexSettings, RuntimeSettings, Settings, get_settings
from oh_my_subagents.interfaces.http.contracts.operation_failure import ProductFailureCode
from oh_my_subagents.interfaces.http.runtime_exception_mapping import runtime_exception_failure
from oh_my_subagents.main import create_app
from oh_my_subagents.persistence.session import get_db_session
from oh_my_subagents.providers import ProviderKind
from oh_my_subagents.runtime.contracts import TaskStartRequest
from oh_my_subagents.runtime.contracts.operation_failure import OperationFailureCode
from oh_my_subagents.runtime.contracts.task import TaskStartReceipt
from oh_my_subagents.runtime.dispatch.preparation import DispatchOpeningDependencies
from oh_my_subagents.runtime.errors import RuntimeOperationError
from oh_my_subagents.runtime.post_commit import CapturedRuntimeEffectPublisher
from tests.helpers.generic_workflow import GENERIC_WORKFLOW_ID


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
            "/api/tasks",
            json={"workflow": GENERIC_WORKFLOW_ID, "prompt": "Do the work."},
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
                "/api/tasks",
                json={"workflow": GENERIC_WORKFLOW_ID, "prompt": "Do the work."},
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
            "/api/tasks",
            json={"workflow": GENERIC_WORKFLOW_ID, "prompt": "Do the work."},
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
        ({"workflow": GENERIC_WORKFLOW_ID, "prompt": 7}, "prompt"),
        (
            {
                "workflow": GENERIC_WORKFLOW_ID,
                "prompt": "Do the work.",
                "files": [{"path": 7}],
            },
            "files.0.path",
        ),
        (
            {
                "workflow": GENERIC_WORKFLOW_ID,
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
        response = await client.post("/api/tasks", json=payload)

    assert response.status_code == 400
    assert response.json() == {
        "ok": False,
        "code": "invalid_request",
        "summary": "The request contains an unsupported or invalid field.",
        "retryable": False,
        "field_path": field_path,
        "suggested_next_step": ("Correct the highlighted field and resend the request."),
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
        workflow_id=GENERIC_WORKFLOW_ID,
        workflow_revision=1,
        workspace=str(workspace),
        manifest=str(Path(".oms") / task_id / "manifest.md"),
    )
