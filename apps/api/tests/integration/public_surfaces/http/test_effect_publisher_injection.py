from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import autoclaw.interfaces.http.routers.control as control_router_module
import autoclaw.interfaces.http.routers.tasks as tasks_router_module
import httpx
import pytest
from autoclaw.main import create_app
from autoclaw.persistence.session import get_db_session
from autoclaw.runtime.contracts import (
    FlowStatus,
    HumanRequestResolution,
    HumanRequestResolutionKind,
    HumanRequestResolutionSurface,
    HumanRequestResolveResponse,
    RuntimeFlowPauseResponse,
    RuntimeFlowRead,
    RuntimeLifecycleStatus,
    TaskStartResponse,
    WorkflowManifestRef,
)
from sqlalchemy.ext.asyncio import AsyncSession


async def _fake_session() -> AsyncIterator[AsyncSession]:
    yield cast(AsyncSession, object())


class _WritableSession:
    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


async def _fake_writable_session() -> AsyncIterator[AsyncSession]:
    yield cast(AsyncSession, _WritableSession())


async def test_task_start_route_injects_app_owned_effect_publishers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(should_enable_mcp_mounts=False)
    app.dependency_overrides[get_db_session] = _fake_session
    captured: dict[str, object] = {}

    async def fake_start_task(
        request: object,
        *,
        data_dir: Path | None = None,
        session: AsyncSession | None = None,
        runtime_effect_publisher: object = None,
        support_projection_publisher: object = None,
    ) -> TaskStartResponse:
        del request, data_dir, session
        captured["runtime"] = runtime_effect_publisher
        captured["projection"] = support_projection_publisher
        return TaskStartResponse(
            task_id="task.http-injection",
            compiled_plan_id="compiled-plan.task.http-injection",
            active_flow_revision_id="flow-revision.http-injection.1",
            flow_status=FlowStatus.RUNNING,
            workflow_manifest_ref=WorkflowManifestRef(
                path=Path("_runtime/workflow-manifest.md"),
                description="Committed workflow manifest support projection.",
            ),
        )

    monkeypatch.setattr(
        tasks_router_module,
        "start_task_from_definition",
        fake_start_task,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:18125",
    ) as client:
        response = await client.post(
            "/tasks/start",
            json={
                "task": {
                    "key": "http-injection",
                    "title": "HTTP publisher injection",
                    "summary": "Keep task-start effects explicit.",
                },
                "workflow": {"key": "bounded-change"},
            },
        )

    assert response.status_code == 200
    assert captured == {
        "runtime": app.state.runtime_effect_publisher,
        "projection": app.state.support_projection_publisher,
    }


async def test_human_resolution_route_injects_app_owned_runtime_publisher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(should_enable_mcp_mounts=False)
    app.dependency_overrides[get_db_session] = _fake_session
    captured: dict[str, object] = {}

    async def fake_resolve_human_request(
        session: AsyncSession,
        *,
        task_id: str,
        request_id: str,
        request: object,
        actor_ref: str | None = None,
        resolved_by_surface: object = None,
        runtime_effect_publisher: object = None,
    ) -> HumanRequestResolveResponse:
        del session, request, resolved_by_surface
        captured["runtime"] = runtime_effect_publisher
        captured["actor_ref"] = actor_ref
        return HumanRequestResolveResponse(
            task_id=task_id,
            resolution=HumanRequestResolution(
                request_id=request_id,
                task_id=task_id,
                resolution_kind=HumanRequestResolutionKind.ANSWERED,
                item_responses={"direction": "a"},
                policy_basis={"policy_basis": "test"},
                summary="Human answered the controller-owned request.",
                resolved_at=datetime.now(UTC),
                resolved_by_actor_ref=actor_ref,
                resolved_by_surface=HumanRequestResolutionSurface.CONTROL_API,
            ),
        )

    monkeypatch.setattr(
        control_router_module,
        "resolve_human_request",
        fake_resolve_human_request,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:18125",
    ) as client:
        response = await client.post(
            "/control/tasks/task.http-injection/human-requests/request.http-injection/resolve",
            json={"item_responses": {"direction": "a"}},
        )

    assert response.status_code == 200
    assert captured == {
        "runtime": app.state.runtime_effect_publisher,
        "actor_ref": "local_operator",
    }


async def test_flow_control_routes_inject_current_guards_and_runtime_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(should_enable_mcp_mounts=False)
    app.dependency_overrides[get_db_session] = _fake_writable_session
    captured: dict[str, object] = {}

    async def fake_pause_runtime_flow(
        session: AsyncSession,
        task_id: str,
        **kwargs: object,
    ) -> RuntimeFlowPauseResponse:
        del session
        captured["pause"] = kwargs
        return RuntimeFlowPauseResponse(flow=_runtime_flow_read(task_id, control_revision=8))

    async def fake_continue_runtime_flow(
        session: AsyncSession,
        task_id: str,
        **kwargs: object,
    ) -> RuntimeFlowRead:
        del session
        captured["continue"] = kwargs
        return _runtime_flow_read(task_id, control_revision=8)

    async def fake_cancel_runtime_flow(
        session: AsyncSession,
        task_id: str,
        **kwargs: object,
    ) -> RuntimeFlowRead:
        del session
        captured["cancel"] = kwargs
        return _runtime_flow_read(task_id, control_revision=8)

    monkeypatch.setattr(control_router_module, "pause_runtime_flow", fake_pause_runtime_flow)
    monkeypatch.setattr(
        control_router_module,
        "continue_runtime_flow",
        fake_continue_runtime_flow,
    )
    monkeypatch.setattr(control_router_module, "cancel_runtime_flow", fake_cancel_runtime_flow)

    request = {
        "expected_active_flow_revision_id": "flow-revision.http-injection.1",
        "expected_control_revision": 7,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:18125",
    ) as client:
        responses = [
            await client.post(
                f"/control/tasks/task.http-injection/{operation}",
                json=request,
            )
            for operation in ("pause", "continue", "cancel")
        ]

    assert [response.status_code for response in responses] == [200, 200, 200], [
        response.text for response in responses
    ]
    expected_guards = {
        "expected_active_flow_revision_id": "flow-revision.http-injection.1",
        "expected_control_revision": 7,
        "actor_ref": "local_operator",
    }
    assert captured["pause"] == {
        **expected_guards,
        "runtime_effect_publisher": app.state.runtime_effect_publisher,
    }
    assert captured["continue"] == {
        **expected_guards,
        "dependencies": app.state.dispatch_opening_dependencies,
    }
    assert captured["cancel"] == {
        **expected_guards,
        "runtime_effect_publisher": app.state.runtime_effect_publisher,
    }


def _runtime_flow_read(task_id: str, *, control_revision: int) -> RuntimeFlowRead:
    return RuntimeFlowRead(
        task_id=task_id,
        task_title="HTTP publisher injection",
        task_summary="Keep flow-control runtime ownership explicit.",
        status=RuntimeLifecycleStatus.RUNNING,
        active_flow_revision_id="flow-revision.http-injection.1",
        control_revision=control_revision,
        workflow_manifest_ref=WorkflowManifestRef(
            path=Path("_runtime/workflow-manifest.md"),
            description="Committed workflow manifest support projection.",
        ),
        updated_at=datetime.now(UTC),
    )
