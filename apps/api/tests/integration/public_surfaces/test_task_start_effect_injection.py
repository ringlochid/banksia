from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

import banksia.interfaces.http.routers.tasks as tasks_router_module
import banksia.interfaces.mcp.operator.task_start as operator_task_start_module
import httpx
import pytest
from banksia.interfaces.mcp.operator.server import (
    OperatorEffectPublishers,
    create_operator_mcp_server,
)
from banksia.main import create_app
from banksia.persistence.session import get_db_session
from banksia.runtime.contracts import (
    FlowStatus,
    TaskStartRequest,
    TaskStartResponse,
    WorkflowManifestRef,
)
from banksia.runtime.node_operations.follow_on import SupportProjectionPublisher
from banksia.runtime.post_commit import RuntimeEffectPublisher, RuntimeEffectSignal
from banksia.runtime.projection.signals import SupportProjectionSignal
from sqlalchemy.ext.asyncio import AsyncSession


class _RuntimePublisher:
    def publish(self, signal: RuntimeEffectSignal) -> bool:
        del signal
        return True


class _SupportPublisher:
    def publish(self, signal: SupportProjectionSignal) -> bool:
        del signal
        return True


async def _fake_session() -> AsyncIterator[AsyncSession]:
    yield cast(AsyncSession, object())


async def test_http_task_start_injects_both_app_owned_publishers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_publisher = _RuntimePublisher()
    support_publisher = _SupportPublisher()
    captured: dict[str, object] = {}

    async def capture_start(
        request: TaskStartRequest,
        *,
        session: AsyncSession,
        runtime_effect_publisher: RuntimeEffectPublisher,
        support_projection_publisher: SupportProjectionPublisher,
    ) -> TaskStartResponse:
        del request
        captured.update(
            session=session,
            runtime=runtime_effect_publisher,
            support=support_projection_publisher,
        )
        return _response("task.http-effect-injection")

    monkeypatch.setattr(tasks_router_module, "start_task_service", capture_start)
    app = create_app(should_enable_mcp_mounts=False)
    app.state.runtime_effect_publisher = runtime_publisher
    app.state.support_projection_publisher = support_publisher
    app.dependency_overrides[get_db_session] = _fake_session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 43125)),
        base_url="http://127.0.0.1:18125",
    ) as client:
        response = await client.post("/tasks/start", json=_request().model_dump(mode="json"))

    assert response.status_code == 200, response.text
    assert "session" in captured
    assert captured["runtime"] is runtime_publisher
    assert captured["support"] is support_publisher


async def test_operator_task_start_injects_both_server_owned_publishers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_publisher = _RuntimePublisher()
    support_publisher = _SupportPublisher()
    captured: dict[str, object] = {}

    async def capture_start(
        request: TaskStartRequest,
        *,
        runtime_effect_publisher: RuntimeEffectPublisher,
        support_projection_publisher: SupportProjectionPublisher,
    ) -> TaskStartResponse:
        captured.update(
            request=request,
            runtime=runtime_effect_publisher,
            support=support_projection_publisher,
        )
        return _response("task.operator-effect-injection")

    request = _request()
    monkeypatch.setattr(
        operator_task_start_module,
        "task_start_request_from_path",
        lambda _path: request,
    )
    monkeypatch.setattr(operator_task_start_module, "start_task_service", capture_start)
    server = create_operator_mcp_server(
        effect_publishers=OperatorEffectPublishers(
            runtime_effect_publisher=runtime_publisher,
            support_projection_publisher=support_publisher,
        )
    )

    await server.call_tool("start_task", {"task_compose_path": "/tmp/task-compose.yaml"})

    assert captured == {
        "request": request,
        "runtime": runtime_publisher,
        "support": support_publisher,
    }


def _request() -> TaskStartRequest:
    return TaskStartRequest.model_validate(
        {
            "task": {
                "key": "effect-injection",
                "title": "Task start effect injection",
                "summary": "Prove transport-owned publishers reach the start service.",
            },
            "workflow": {"key": "reviewed-delivery"},
        }
    )


def _response(task_id: str) -> TaskStartResponse:
    return TaskStartResponse(
        task_id=task_id,
        compiled_plan_id=f"compiled-plan.{task_id}",
        active_flow_revision_id=f"flow-revision.flow.{task_id}.01",
        flow_status=FlowStatus.RUNNING,
        workflow_manifest_ref=WorkflowManifestRef(
            path=Path("_runtime/workflow-manifest.md"),
            description="Committed Workflow manifest projection.",
        ),
    )
