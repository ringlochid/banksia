from __future__ import annotations

from collections.abc import Mapping

import httpx
import pytest
from autoclaw.interfaces.mcp.transport import node_mcp_transport_policy
from autoclaw.runtime.node_operations import NodeOperationName
from starlette.applications import Starlette
from tests.integration.mcp.node_server.transport_support import (
    RecordingNodeOperationExecutor,
    create_test_node_mcp_apps,
    issue_test_binding,
    managed_headers,
)

_INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "autoclaw-node-transport-test", "version": "1"},
    },
}
_MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def test_node_transport_policy_accepts_only_exact_loopback_authorities() -> None:
    policy = node_mcp_transport_policy(
        host="127.0.0.1",
        port=18125,
        allowed_origins=("http://127.0.0.1:5173",),
    )

    assert "127.0.0.1:18125" in policy.allowed_hosts
    assert "http://127.0.0.1:5173" in policy.allowed_origins
    assert not any("*" in value for value in (*policy.allowed_hosts, *policy.allowed_origins))

    with pytest.raises(ValueError, match="loopback-only"):
        node_mcp_transport_policy(host="0.0.0.0", port=18125)
    with pytest.raises(ValueError, match="valid port"):
        node_mcp_transport_policy(
            host="127.0.0.1",
            port=18125,
            allowed_origins=("http://localhost:*",),
        )
    with pytest.raises(ValueError, match="user information"):
        node_mcp_transport_policy(
            host="127.0.0.1",
            port=18125,
            allowed_origins=("http://user@127.0.0.1:5173",),
        )


def test_node_transport_policy_formats_ipv6_authorities_for_http_headers() -> None:
    policy = node_mcp_transport_policy(
        host="::1",
        port=18125,
        allowed_origins=("http://[::1]:5173",),
    )

    assert "[::1]:18125" in policy.allowed_hosts
    assert "http://[::1]:18125" in policy.allowed_origins
    assert "http://[::1]:5173" in policy.allowed_origins
    assert not any("*" in value for value in (*policy.allowed_hosts, *policy.allowed_origins))


async def _initialize(
    app: Starlette,
    *,
    headers: Mapping[str, str] | None = None,
    client_host: str = "127.0.0.1",
) -> httpx.Response:
    request_headers = {**_MCP_HEADERS, **dict(headers or {})}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(client_host, 43125)),
        base_url="http://127.0.0.1:18125",
    ) as client:
        return await client.post("/mcp", headers=request_headers, json=_INITIALIZE_REQUEST)


async def test_managed_transport_requires_a_valid_bearer_before_mcp_handling() -> None:
    applications, registry = create_test_node_mcp_apps(RecordingNodeOperationExecutor())
    issued = issue_test_binding(
        registry,
        task_id="task.managed-auth",
        dispatch_id="dispatch.managed-auth",
        exposure_ceiling=(NodeOperationName.GET_CURRENT_CONTEXT,),
    )

    async with applications.managed.router.lifespan_context(applications.managed):
        missing = await _initialize(applications.managed)
        wrong = await _initialize(
            applications.managed,
            headers={"Authorization": "Bearer wrong-credential"},
        )
        admitted = await _initialize(
            applications.managed,
            headers=managed_headers(issued),
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert wrong.headers["www-authenticate"] == "Bearer"
    assert admitted.status_code == 200
    assert issued.credential not in missing.text
    assert issued.credential not in wrong.text
    assert issued.credential not in admitted.text


async def test_managed_transport_rejects_non_loopback_peer_forged_host_and_origin() -> None:
    applications, registry = create_test_node_mcp_apps(RecordingNodeOperationExecutor())
    issued = issue_test_binding(
        registry,
        task_id="task.managed-http-boundary",
        dispatch_id="dispatch.managed-http-boundary",
        exposure_ceiling=(NodeOperationName.GET_CURRENT_CONTEXT,),
    )
    authorization = managed_headers(issued)

    async with applications.managed.router.lifespan_context(applications.managed):
        remote_peer = await _initialize(
            applications.managed,
            headers=authorization,
            client_host="198.51.100.12",
        )
        forged_host = await _initialize(
            applications.managed,
            headers={**authorization, "Host": "attacker.example"},
        )
        disallowed_origin = await _initialize(
            applications.managed,
            headers={**authorization, "Origin": "https://attacker.example"},
        )
        allowed_origin = await _initialize(
            applications.managed,
            headers={**authorization, "Origin": "http://127.0.0.1:5173"},
        )

    assert remote_peer.status_code == 403
    assert forged_host.status_code == 421
    assert disallowed_origin.status_code == 403
    assert allowed_origin.status_code == 200


async def test_compatibility_transport_requires_exact_host_origin_without_bearer() -> None:
    applications, _registry = create_test_node_mcp_apps(RecordingNodeOperationExecutor())

    async with applications.compatibility.router.lifespan_context(applications.compatibility):
        admitted = await _initialize(applications.compatibility)
        forged_host = await _initialize(
            applications.compatibility,
            headers={"Host": "attacker.example"},
        )
        disallowed_origin = await _initialize(
            applications.compatibility,
            headers={"Origin": "https://attacker.example"},
        )
        allowed_origin = await _initialize(
            applications.compatibility,
            headers={"Origin": "http://127.0.0.1:5173"},
        )

    assert admitted.status_code == 200
    assert "www-authenticate" not in admitted.headers
    assert forged_host.status_code == 421
    assert disallowed_origin.status_code == 403
    assert allowed_origin.status_code == 200


async def test_managed_app_shutdown_revokes_every_issued_binding() -> None:
    applications, registry = create_test_node_mcp_apps(RecordingNodeOperationExecutor())
    first = issue_test_binding(
        registry,
        task_id="task.shutdown-a",
        dispatch_id="dispatch.shutdown-a",
        exposure_ceiling=(NodeOperationName.GET_CURRENT_CONTEXT,),
    )
    second = issue_test_binding(
        registry,
        task_id="task.shutdown-b",
        dispatch_id="dispatch.shutdown-b",
        exposure_ceiling=(NodeOperationName.LIST_FILES,),
    )

    async with applications.managed.router.lifespan_context(applications.managed):
        assert registry.authenticate(first.credential) == first.binding
        assert registry.authenticate(second.credential) == second.binding

    assert registry.authenticate(first.credential) is None
    assert registry.authenticate(second.credential) is None
