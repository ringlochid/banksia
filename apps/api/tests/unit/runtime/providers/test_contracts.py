from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from autoclaw.definitions.contracts.registry import NetworkAccess, ProviderNativeAccess
from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.runtime.contracts.provider_resolution import (
    CodexProviderRoute,
    OpenClawProviderRoute,
)
from autoclaw.runtime.providers.contracts import (
    CompatibilityNodeMcpConnection,
    DispatchStartRequest,
    ManagedNodeMcpConnection,
    ProviderCheckResult,
    ProviderCheckStatus,
    ProviderStartAccepted,
    ProviderStopOutcome,
)
from autoclaw.runtime.providers.registry import ProviderAdapterRegistry
from pydantic import SecretStr, ValidationError


def test_managed_connection_redacts_credential_and_requires_loopback() -> None:
    connection = ManagedNodeMcpConnection(
        url="http://127.0.0.1:8123/_internal/node/mcp",
        bearer_token=SecretStr("dispatch-secret"),
        enabled_tools=("record_checkpoint",),
    )

    assert "dispatch-secret" not in repr(connection)
    assert connection.authorization_header == "Bearer dispatch-secret"
    with pytest.raises(ValidationError, match="loopback HTTP"):
        ManagedNodeMcpConnection(
            url="https://example.com/_internal/node/mcp",
            bearer_token=SecretStr("dispatch-secret"),
            enabled_tools=("record_checkpoint",),
        )


def test_dispatch_start_request_requires_provider_projection() -> None:
    with pytest.raises(ValidationError, match="managed providers require"):
        DispatchStartRequest(
            task_id="task-1",
            dispatch_id="dispatch-1",
            provider_start_revision=0,
            working_directory=Path("/tmp/workspace"),
            instructions=b"instructions",
            input=b"input",
            provider_route=CodexProviderRoute(kind=ProviderKind.CODEX),
            provider_native_access=ProviderNativeAccess.FULL,
            network_access=NetworkAccess.ALLOW,
            compatibility_node_mcp=CompatibilityNodeMcpConnection(
                url="http://127.0.0.1:8123/node/mcp"
            ),
        )

    request = DispatchStartRequest(
        task_id="task-1",
        dispatch_id="dispatch-1",
        provider_start_revision=0,
        working_directory=Path("/tmp/workspace"),
        instructions=b"instructions",
        input=b"input",
        provider_route=OpenClawProviderRoute(
            kind=ProviderKind.OPENCLAW,
            gateway_profile="default",
        ),
        provider_native_access=ProviderNativeAccess.FULL,
        network_access=NetworkAccess.ALLOW,
        compatibility_node_mcp=CompatibilityNodeMcpConnection(url="http://127.0.0.1:8123/node/mcp"),
    )

    assert request.compatibility_node_mcp is not None


class _RegistryAdapter:
    def __init__(self, kind: ProviderKind, events: list[str]) -> None:
        self.kind = kind
        self.events = events

    async def start(self, request: DispatchStartRequest) -> ProviderStartAccepted:
        del request
        return ProviderStartAccepted()

    async def stop(self, dispatch_id: str) -> ProviderStopOutcome:
        del dispatch_id
        return ProviderStopOutcome.NOT_RUNNING

    async def read_availability(self) -> ProviderCheckResult:
        return ProviderCheckResult(
            kind=self.kind,
            status=ProviderCheckStatus.AVAILABLE,
            code="available",
        )

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        self.events.append(f"open:{self.kind.value}")
        try:
            yield
        finally:
            self.events.append(f"close:{self.kind.value}")


@pytest.mark.asyncio
async def test_registry_routes_exact_kind_and_owns_lifespans() -> None:
    events: list[str] = []
    codex = _RegistryAdapter(ProviderKind.CODEX, events)
    claude = _RegistryAdapter(ProviderKind.CLAUDE, events)
    registry = ProviderAdapterRegistry([codex, claude])

    async with registry.lifespan():
        assert registry.get(ProviderKind.CODEX) is codex
        assert registry.available_kinds == {ProviderKind.CODEX, ProviderKind.CLAUDE}
        with pytest.raises(LookupError, match="openclaw"):
            registry.get(ProviderKind.OPENCLAW)

    assert events == ["open:codex", "open:claude", "close:claude", "close:codex"]
