from __future__ import annotations

from collections.abc import Mapping

import autoclaw.main as main_module
import autoclaw.runtime.node_operations.executor as executor_module
import httpx
import pytest
from autoclaw.config import Settings
from autoclaw.main import create_app
from autoclaw.runtime.node_mcp import DispatchMcpBindingRegistry
from autoclaw.runtime.node_operations import NodeOperationName
from autoclaw.runtime.post_commit import RuntimeEffectRouter
from autoclaw.runtime.projection import SupportProjectionOwner
from fastapi import FastAPI
from starlette.routing import Mount

_INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "autoclaw-main-mount-test", "version": "1"},
    },
}
_MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def test_sync_app_construction_defers_loop_scoped_session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_resolved_during_construction() -> None:
        raise AssertionError("session factory resolved before async Node operation")

    monkeypatch.setattr(
        executor_module,
        "get_session_factory",
        fail_if_resolved_during_construction,
    )

    app = create_app(should_enable_mcp_mounts=True)

    assert isinstance(app.state.dispatch_mcp_binding_registry, DispatchMcpBindingRegistry)
    assert app.state.node_operation_executor is not None
    assert app.state.dispatch_starter is not None
    assert len(app.state.mcp_lifespan_apps) == 3


async def _post_initialize(
    client: httpx.AsyncClient,
    path: str,
    *,
    headers: Mapping[str, str] | None = None,
) -> httpx.Response:
    return await client.post(
        path,
        headers={**_MCP_HEADERS, **dict(headers or {})},
        json=_INITIALIZE_REQUEST,
    )


def _install_lifespan_mocks(
    monkeypatch: pytest.MonkeyPatch,
    app: FastAPI,
    startup_calls: list[str],
) -> None:
    async def ensure_schema() -> None:
        startup_calls.append("schema")

    async def cleanup_dispatch_requests(**kwargs: object) -> dict[str, int]:
        del kwargs
        startup_calls.append("cleanup")
        return {}

    async def audit_runtime(**kwargs: object) -> dict[str, object]:
        del kwargs
        assert isinstance(app.state.runtime_effect_router, RuntimeEffectRouter)
        assert app.state.runtime_effect_publisher is app.state.runtime_effect_router
        startup_calls.append("runtime_audit")
        return {}

    async def audit_projections(**kwargs: object) -> dict[str, int]:
        del kwargs
        assert isinstance(app.state.support_projection_owner, SupportProjectionOwner)
        assert app.state.support_projection_owner.is_accepting
        assert app.state.support_projection_publisher is app.state.support_projection_owner
        startup_calls.append("projection_audit")
        return {}

    async def dispose_engine() -> None:
        startup_calls.append("dispose")

    monkeypatch.setattr(main_module, "ensure_database_schema", ensure_schema)
    monkeypatch.setattr(
        main_module,
        "cleanup_aged_dispatch_request_directories",
        cleanup_dispatch_requests,
    )
    monkeypatch.setattr(main_module, "audit_startup_runtime_effects", audit_runtime)
    monkeypatch.setattr(main_module, "audit_startup_support_projections", audit_projections)
    monkeypatch.setattr(main_module, "dispose_db_engine", dispose_engine)


async def test_main_app_mounts_one_managed_and_one_compatibility_node_mcp_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    startup_calls: list[str] = []
    app = create_app(should_enable_mcp_mounts=True)
    _install_lifespan_mocks(monkeypatch, app, startup_calls)

    registry = app.state.dispatch_mcp_binding_registry
    assert isinstance(registry, DispatchMcpBindingRegistry)
    issued = registry.issue_binding(
        task_id="task.main-managed-mount",
        dispatch_id="dispatch.main-managed-mount",
        provider_start_revision=0,
        exposure_ceiling=(NodeOperationName.GET_CURRENT_CONTEXT,),
    )

    mounts = {route.path: route.app for route in app.routes if isinstance(route, Mount)}
    assert {"/operator", "/_internal/node", "/node"} <= set(mounts)
    assert len({id(mounts["/_internal/node"]), id(mounts["/node"])}) == 2
    assert app.state.mcp_lifespan_apps == (
        mounts["/operator"],
        mounts["/_internal/node"],
        mounts["/node"],
    )

    async with app.router.lifespan_context(app):
        assert startup_calls == ["schema", "cleanup", "runtime_audit", "projection_audit"]
        assert app.state.runtime_startup_audit == {}
        assert app.state.support_projection_startup_audit == {}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 43125)),
            base_url="http://127.0.0.1:18125",
        ) as client:
            operator = await _post_initialize(
                client,
                "/operator/mcp",
            )
            managed = await _post_initialize(
                client,
                "/_internal/node/mcp",
                headers={"Authorization": f"Bearer {issued.credential}"},
            )
            compatibility = await _post_initialize(client, "/node/mcp")

            assert operator.status_code == 200
            assert managed.status_code == 200
            assert compatibility.status_code == 200
            assert registry.authenticate(issued.credential) == issued.binding

    assert startup_calls == [
        "schema",
        "cleanup",
        "runtime_audit",
        "projection_audit",
        "dispose",
    ]
    assert registry.authenticate(issued.credential) is None
    assert not app.state.support_projection_owner.is_accepting


async def test_ipv6_loopback_mount_admits_operator_without_managed_node_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        api_host="::1",
        api_port=18125,
        console_origins=["http://[::1]:5173"],
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    startup_calls: list[str] = []
    app = create_app(should_enable_mcp_mounts=True)
    _install_lifespan_mocks(monkeypatch, app, startup_calls)

    registry = app.state.dispatch_mcp_binding_registry
    assert isinstance(registry, DispatchMcpBindingRegistry)
    issued = registry.issue_binding(
        task_id="task.main-ipv6-mount",
        dispatch_id="dispatch.main-ipv6-mount",
        provider_start_revision=0,
        exposure_ceiling=(NodeOperationName.GET_CURRENT_CONTEXT,),
    )

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("::1", 43125)),
            base_url="http://[::1]:18125",
        ) as client:
            operator = await _post_initialize(
                client,
                "/operator/mcp",
                headers={"Origin": "http://[::1]:5173"},
            )
            wrong_port = await _post_initialize(
                client,
                "/operator/mcp",
                headers={"Host": "[::1]:18126"},
            )
            wrong_origin = await _post_initialize(
                client,
                "/operator/mcp",
                headers={"Origin": "http://[::1]:5174"},
            )
            managed_without_bearer = await _post_initialize(
                client,
                "/_internal/node/mcp",
            )
            managed = await _post_initialize(
                client,
                "/_internal/node/mcp",
                headers={"Authorization": f"Bearer {issued.credential}"},
            )

    assert operator.status_code == 200
    assert wrong_port.status_code == 400
    assert wrong_port.json()["code"] == "local_admission_denied"
    assert wrong_origin.status_code == 403
    assert wrong_origin.json()["code"] == "local_admission_denied"
    assert managed_without_bearer.status_code == 401
    assert managed.status_code == 200


async def test_main_app_openapi_and_http_routes_exclude_private_mcp_and_callback_lanes() -> None:
    app = create_app(should_enable_mcp_mounts=True)

    openapi = app.openapi()
    openapi_paths = set(openapi["paths"])
    route_paths = {getattr(route, "path", "") for route in app.routes}

    assert {
        "/authoring/task-compose/preview",
        "/control/tasks/{task_id}",
        "/control/tasks/{task_id}/snapshot",
        "/control/tasks/{task_id}/trace",
        "/control/tasks/{task_id}/events",
        "/control/tasks/{task_id}/events/stream",
    } <= openapi_paths
    assert "/_internal/node/mcp" not in openapi_paths
    assert "/node/mcp" not in openapi_paths
    assert not any(path.startswith("/callback") for path in openapi_paths)
    assert not any(path.startswith("/callback") for path in route_paths)
    assert openapi.get("components", {}).get("securitySchemes", {}) == {}
