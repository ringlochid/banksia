from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import cast

import pytest
from autoclaw.definitions.contracts.registry import NetworkAccess, ProviderNativeAccess
from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.integrations.claude import ClaudeAdapter
from autoclaw.integrations.claude.native_identity import ClaudeAuthenticationState
from autoclaw.runtime.contracts.provider_resolution import ClaudeProviderRoute
from autoclaw.runtime.providers.contracts import (
    DispatchStartRequest,
    ManagedNodeMcpConnection,
    ProviderAuthenticationMethod,
    ProviderCheckAxisStatus,
    ProviderCheckStatus,
    ProviderStopOutcome,
)
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from pydantic import SecretStr


class _FakeClaudeClient:
    def __init__(self, options: ClaudeAgentOptions) -> None:
        self.options = options
        self.query_input: str | None = None
        self.was_connected = False
        self.was_interrupted = False
        self.was_disconnected = False
        self._done = asyncio.Event()

    async def connect(self) -> None:
        self.was_connected = True

    async def query(self, dispatch_input: str) -> None:
        self.query_input = dispatch_input

    async def receive_response(self) -> AsyncIterator[object]:
        await self._done.wait()
        if False:
            yield object()

    async def interrupt(self) -> None:
        self.was_interrupted = True
        self._done.set()

    async def disconnect(self) -> None:
        self.was_disconnected = True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method",
    (
        ProviderAuthenticationMethod.SUBSCRIPTION,
        ProviderAuthenticationMethod.API_KEY,
    ),
)
async def test_claude_check_confirms_supported_native_authentication(
    method: ProviderAuthenticationMethod,
) -> None:
    adapter = ClaudeAdapter(
        authentication_reader=lambda: ClaudeAuthenticationState(
            is_authenticated=True,
            method=method,
            code="claude_available",
        )
    )

    async with adapter.lifespan():
        result = await adapter.read_availability()

    assert result.status is ProviderCheckStatus.AVAILABLE
    assert result.authentication is ProviderCheckAxisStatus.PASSED
    assert result.authentication_method is method
    assert result.reachability is ProviderCheckAxisStatus.NOT_CHECKED


@pytest.mark.asyncio
async def test_claude_check_rejects_missing_native_authentication() -> None:
    adapter = ClaudeAdapter(
        authentication_reader=lambda: ClaudeAuthenticationState(
            is_authenticated=False,
            method=None,
            code="claude_authentication_required",
        )
    )

    async with adapter.lifespan():
        result = await adapter.read_availability()

    assert result.status is ProviderCheckStatus.UNAVAILABLE
    assert result.authentication is ProviderCheckAxisStatus.FAILED


def _request() -> DispatchStartRequest:
    return DispatchStartRequest(
        task_id="task-1",
        dispatch_id="dispatch-1",
        provider_start_revision=0,
        working_directory=Path("/tmp/workspace"),
        instructions=b"exact instructions",
        input=b"exact input",
        provider_route=ClaudeProviderRoute(
            kind=ProviderKind.CLAUDE,
            model_override="claude-sonnet-4-5",
            effort_override="high",
        ),
        provider_native_access=ProviderNativeAccess.RESTRICTED,
        network_access=NetworkAccess.DENY,
        managed_node_mcp=ManagedNodeMcpConnection(
            url="http://127.0.0.1:8123/_internal/node/mcp",
            bearer_token=SecretStr("binding-secret"),
            enabled_tools=("record_checkpoint", "return_boundary"),
        ),
    )


@pytest.mark.asyncio
async def test_claude_start_uses_disposable_scoped_client_and_returns_before_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients: list[_FakeClaudeClient] = []
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "must-not-reach-claude")

    def build_client(options: ClaudeAgentOptions) -> _FakeClaudeClient:
        client = _FakeClaudeClient(options)
        clients.append(client)
        return client

    adapter = ClaudeAdapter(
        client_factory=cast(Callable[[ClaudeAgentOptions], ClaudeSDKClient], build_client),
    )

    async with adapter.lifespan():
        await adapter.start(_request())
        client = clients[0]

        assert client.was_connected is True
        assert client.query_input == "exact input"
        assert str(client.options.cwd) == "/tmp/workspace"
        assert client.options.system_prompt == {
            "type": "preset",
            "preset": "claude_code",
            "append": "exact instructions",
        }
        assert client.options.permission_mode == "dontAsk"
        assert client.options.strict_mcp_config is True
        assert client.options.setting_sources == ["user", "project", "local"]
        assert client.options.env["OPENCLAW_GATEWAY_TOKEN"] == ""
        assert "AskUserQuestion" in client.options.disallowed_tools
        assert "WebFetch" in client.options.disallowed_tools
        assert client.options.sandbox is not None
        sandbox = cast(dict[str, object], client.options.sandbox)
        assert sandbox["failIfUnavailable"] is True
        assert sandbox["allowUnsandboxedCommands"] is False
        assert "mcp__autoclaw_node__record_checkpoint" in client.options.allowed_tools
        mcp_servers = cast(dict[str, object], client.options.mcp_servers)
        mcp_config = cast(dict[str, object], mcp_servers["autoclaw_node"])
        assert mcp_config.get("headers") == {"Authorization": "Bearer binding-secret"}

        assert await adapter.stop("dispatch-1") is ProviderStopOutcome.STOPPED
        assert client.was_interrupted is True
        assert client.was_disconnected is True
