from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions
from pydantic import SecretStr

from banksia.integrations.claude.native_identity import (
    ClaudeAuthenticationState,
    ClaudeEndpointPolicyState,
    ClaudeSubscriptionClass,
)
from banksia.providers import (
    ManagedExtensionMode,
    ManagedSandboxMode,
    NetworkAccess,
    ProviderKind,
    ProviderNativeAccess,
)
from banksia.runtime.contracts.provider_resolution import ClaudeProviderRoute
from banksia.runtime.providers.contracts import (
    DispatchStartRequest,
    ManagedNodeMcpConnection,
    ProviderAuthenticationMethod,
)


class FakeClaudeClient:
    def __init__(self, options: ClaudeAgentOptions) -> None:
        self.options = options
        self.query_inputs: list[str] = []
        self.was_connected = False
        self.was_interrupted = False
        self.was_disconnected = False
        self.mcp_status_reads = 0
        self._done = asyncio.Event()

    async def connect(self) -> None:
        self.was_connected = True

    async def get_server_info(self) -> dict[str, object]:
        return {"commands": []}

    async def get_context_usage(self) -> dict[str, object]:
        return {
            "memoryFiles": [],
            "agents": [],
            "mcpTools": [
                {"name": "checkpoint", "serverName": "banksia_node"},
                {"name": "delegate", "serverName": "banksia_node"},
            ],
        }

    async def get_mcp_status(self) -> dict[str, object]:
        self.mcp_status_reads += 1
        return {
            "mcpServers": [
                {
                    "name": "banksia_node",
                    "status": "pending" if self.mcp_status_reads == 1 else "connected",
                    "tools": [{"name": "checkpoint"}, {"name": "delegate"}],
                }
            ]
        }

    async def query(self, dispatch_input: str) -> None:
        self.query_inputs.append(dispatch_input)
        self._done = asyncio.Event()

    async def receive_response(self) -> AsyncIterator[object]:
        await self._done.wait()
        if False:
            yield object()

    async def interrupt(self) -> None:
        self.was_interrupted = True
        self._done.set()

    async def disconnect(self) -> None:
        self.was_disconnected = True

    @property
    def query_input(self) -> str | None:
        return self.query_inputs[-1] if self.query_inputs else None


def authentication(
    method: ProviderAuthenticationMethod = ProviderAuthenticationMethod.SUBSCRIPTION,
) -> ClaudeAuthenticationState:
    return ClaudeAuthenticationState(
        is_authenticated=True,
        method=method,
        code="claude_available",
        subscription_class=(
            ClaudeSubscriptionClass.PERSONAL
            if method is ProviderAuthenticationMethod.SUBSCRIPTION
            else None
        ),
    )


def clear_policy() -> ClaudeEndpointPolicyState:
    return ClaudeEndpointPolicyState(
        is_installed=False,
        code="claude_endpoint_policy_clear",
    )


def task_request(
    *,
    working_directory: Path | None = None,
    extension_mode: ManagedExtensionMode = ManagedExtensionMode.ISOLATED,
) -> DispatchStartRequest:
    return DispatchStartRequest(
        task_id="task-1",
        dispatch_id="dispatch-1",
        provider_start_revision=0,
        working_directory=working_directory or Path.cwd(),
        instructions="exact instructions",
        input="exact input",
        provider_route=ClaudeProviderRoute(
            kind=ProviderKind.CLAUDE,
            model_override="claude-sonnet-4-5",
            effort_override="high",
        ),
        provider_native_access=ProviderNativeAccess.RESTRICTED,
        network_access=NetworkAccess.DENY,
        sandbox_mode=ManagedSandboxMode.WORKSPACE_WRITE,
        extension_mode=extension_mode,
        managed_node_mcp=ManagedNodeMcpConnection(
            url="http://127.0.0.1:8123/_internal/node/mcp",
            bearer_token=SecretStr("binding-secret"),
            enabled_tools=("checkpoint", "delegate"),
        ),
    )
