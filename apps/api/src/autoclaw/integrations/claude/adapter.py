from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import cast

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from claude_agent_sdk.types import EffortLevel, McpHttpServerConfig, SandboxSettings

from autoclaw.definitions.contracts.registry import NetworkAccess, ProviderNativeAccess
from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.integrations.claude.native_identity import (
    ClaudeAuthenticationState,
    read_claude_authentication,
)
from autoclaw.platform.provider_environment import (
    ANTHROPIC_API_KEY,
    provider_subprocess_environment_overrides,
)
from autoclaw.runtime.contracts.provider_resolution import ClaudeProviderRoute
from autoclaw.runtime.providers.contracts import (
    MANAGED_NODE_MCP_SERVER_NAME,
    DispatchStartRequest,
    ManagedNodeMcpConnection,
    ProviderCheckAxisStatus,
    ProviderCheckResult,
    ProviderCheckStatus,
    ProviderStartAccepted,
    ProviderStartError,
    ProviderStartErrorCode,
    ProviderStartFailureKind,
    ProviderStopOutcome,
)

_CLAUDE_FULL_NATIVE_TOOLS = (
    "Agent",
    "Bash",
    "Edit",
    "Glob",
    "Grep",
    "NotebookEdit",
    "Read",
    "Skill",
    "SlashCommand",
    "TodoWrite",
    "WebFetch",
    "WebSearch",
    "Write",
)
_CLAUDE_RESTRICTED_NATIVE_TOOLS = (
    "Edit",
    "Glob",
    "Grep",
    "NotebookEdit",
    "Read",
    "Skill",
    "TodoWrite",
    "Write",
)
_CLAUDE_NETWORK_TOOLS = ("WebFetch", "WebSearch")
_CLAUDE_ALWAYS_DISALLOWED_TOOLS = ("AskUserQuestion",)
_CLAUDE_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})


@dataclass(slots=True)
class _ClaudeExecution:
    client: ClaudeSDKClient
    consumer: asyncio.Task[None]


class ClaudeAdapter:
    """Narrow Claude Agent SDK adapter with one disposable client per dispatch."""

    kind = ProviderKind.CLAUDE

    def __init__(
        self,
        *,
        client_factory: Callable[[ClaudeAgentOptions], ClaudeSDKClient] = ClaudeSDKClient,
        authentication_reader: Callable[[], ClaudeAuthenticationState] = read_claude_authentication,
    ) -> None:
        self._client_factory = client_factory
        self._authentication_reader = authentication_reader
        self._executions: dict[str, _ClaudeExecution] = {}
        self._consumer_tasks: set[asyncio.Task[None]] = set()
        self._starting_dispatches: set[str] = set()
        self._lock = asyncio.Lock()
        self._is_active = False

    async def start(self, request: DispatchStartRequest) -> ProviderStartAccepted:
        route, connection = _validate_claude_request(request)
        instructions = _decode_request_lane(request.instructions)
        dispatch_input = _decode_request_lane(request.input)
        options = _build_claude_options(request, route, connection, instructions)

        await self._reserve_start(request.dispatch_id)
        client = self._client_factory(options)
        try:
            await client.connect()
        except Exception as exc:
            await _disconnect_client(client)
            await self._release_start_reservation(request.dispatch_id)
            raise ProviderStartError(
                kind=ProviderStartFailureKind.DEFINITE_FAILURE,
                code=ProviderStartErrorCode.CONNECTION,
            ) from exc

        try:
            await client.query(dispatch_input)
        except Exception as exc:
            await _disconnect_client(client)
            await self._release_start_reservation(request.dispatch_id)
            raise ProviderStartError(
                kind=ProviderStartFailureKind.UNCERTAIN_ACCEPTANCE,
                code=ProviderStartErrorCode.UNCERTAIN,
            ) from exc

        async with self._lock:
            consumer = asyncio.create_task(
                self._consume_response(request.dispatch_id, client),
                name=f"claude-response-{request.dispatch_id}",
            )
            execution = _ClaudeExecution(client=client, consumer=consumer)
            self._starting_dispatches.discard(request.dispatch_id)
            self._executions[request.dispatch_id] = execution
            self._consumer_tasks.add(consumer)
        return ProviderStartAccepted()

    async def stop(self, dispatch_id: str) -> ProviderStopOutcome:
        async with self._lock:
            execution = self._executions.get(dispatch_id)
            is_starting = dispatch_id in self._starting_dispatches
        if execution is None:
            return ProviderStopOutcome.FAILED if is_starting else ProviderStopOutcome.NOT_RUNNING

        try:
            await execution.client.interrupt()
        except Exception:
            return ProviderStopOutcome.FAILED

        await _disconnect_client(execution.client)
        execution.consumer.cancel()
        async with self._lock:
            if self._executions.get(dispatch_id) is execution:
                self._executions.pop(dispatch_id, None)
        return ProviderStopOutcome.STOPPED

    async def read_availability(self) -> ProviderCheckResult:
        if not self._is_active:
            return ProviderCheckResult(
                kind=self.kind,
                status=ProviderCheckStatus.UNAVAILABLE,
                code="claude_adapter_inactive",
            )
        try:
            state = await asyncio.to_thread(self._authentication_reader)
        except Exception:
            return ProviderCheckResult(
                kind=self.kind,
                status=ProviderCheckStatus.UNAVAILABLE,
                code="claude_check_failed",
            )
        if not state.is_authenticated:
            authentication = (
                ProviderCheckAxisStatus.FAILED
                if state.code.startswith("claude_authentication_")
                else ProviderCheckAxisStatus.NOT_CHECKED
            )
            return ProviderCheckResult(
                kind=self.kind,
                status=ProviderCheckStatus.UNAVAILABLE,
                code=state.code,
                authentication=authentication,
            )
        return ProviderCheckResult(
            kind=self.kind,
            status=ProviderCheckStatus.AVAILABLE,
            code=state.code,
            authentication=ProviderCheckAxisStatus.PASSED,
            authentication_method=state.method,
        )

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        if self._is_active:
            raise RuntimeError("Claude adapter lifespan is already active")
        self._is_active = True
        try:
            yield
        finally:
            self._is_active = False
            await self._cleanup()

    async def _reserve_start(self, dispatch_id: str) -> None:
        async with self._lock:
            if not self._is_active:
                raise ProviderStartError(
                    kind=ProviderStartFailureKind.DEFINITE_FAILURE,
                    code=ProviderStartErrorCode.UNAVAILABLE,
                )
            if dispatch_id in self._starting_dispatches or dispatch_id in self._executions:
                raise ProviderStartError(
                    kind=ProviderStartFailureKind.UNCERTAIN_ACCEPTANCE,
                    code=ProviderStartErrorCode.UNCERTAIN,
                )
            self._starting_dispatches.add(dispatch_id)

    async def _release_start_reservation(self, dispatch_id: str) -> None:
        async with self._lock:
            self._starting_dispatches.discard(dispatch_id)

    async def _consume_response(self, dispatch_id: str, client: ClaudeSDKClient) -> None:
        current_task = asyncio.current_task()
        try:
            async for _message in client.receive_response():
                pass
        except BaseException:
            pass
        finally:
            await _disconnect_client(client)
            async with self._lock:
                execution = self._executions.get(dispatch_id)
                if execution is not None and execution.client is client:
                    self._executions.pop(dispatch_id, None)
                if current_task is not None:
                    self._consumer_tasks.discard(current_task)

    async def _cleanup(self) -> None:
        async with self._lock:
            executions = tuple(self._executions.values())
            consumers = tuple(self._consumer_tasks)
            self._executions.clear()
            self._consumer_tasks.clear()
            self._starting_dispatches.clear()

        await asyncio.gather(
            *(execution.client.interrupt() for execution in executions),
            return_exceptions=True,
        )
        await asyncio.gather(
            *(_disconnect_client(execution.client) for execution in executions),
            return_exceptions=True,
        )
        for consumer in consumers:
            consumer.cancel()
        if consumers:
            await asyncio.gather(*consumers, return_exceptions=True)


def _validate_claude_request(
    request: DispatchStartRequest,
) -> tuple[ClaudeProviderRoute, ManagedNodeMcpConnection]:
    if not isinstance(request.provider_route, ClaudeProviderRoute):
        raise ProviderStartError(
            kind=ProviderStartFailureKind.DEFINITE_FAILURE,
            code=ProviderStartErrorCode.CONFIGURATION,
        )
    if request.managed_node_mcp is None:
        raise ProviderStartError(
            kind=ProviderStartFailureKind.DEFINITE_FAILURE,
            code=ProviderStartErrorCode.CONFIGURATION,
        )
    return request.provider_route, request.managed_node_mcp


def _decode_request_lane(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProviderStartError(
            kind=ProviderStartFailureKind.DEFINITE_FAILURE,
            code=ProviderStartErrorCode.CONFIGURATION,
        ) from exc


def _build_claude_options(
    request: DispatchStartRequest,
    route: ClaudeProviderRoute,
    connection: ManagedNodeMcpConnection,
    instructions: str,
) -> ClaudeAgentOptions:
    native_tools = _resolve_native_tools(request.provider_native_access)
    managed_tools = tuple(
        f"mcp__{MANAGED_NODE_MCP_SERVER_NAME}__{tool}" for tool in connection.enabled_tools
    )
    available_tools = [*native_tools, *managed_tools]
    disallowed_tools = [*_CLAUDE_ALWAYS_DISALLOWED_TOOLS]
    if request.network_access is NetworkAccess.DENY:
        disallowed_tools.extend(_CLAUDE_NETWORK_TOOLS)

    mcp_server: McpHttpServerConfig = {
        "type": "http",
        "url": connection.url,
        "headers": {"Authorization": connection.authorization_header},
    }
    return ClaudeAgentOptions(
        tools=available_tools,
        allowed_tools=available_tools,
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": instructions,
        },
        mcp_servers={MANAGED_NODE_MCP_SERVER_NAME: mcp_server},
        strict_mcp_config=True,
        permission_mode="dontAsk",
        disallowed_tools=disallowed_tools,
        model=route.model_override,
        cwd=request.working_directory,
        setting_sources=["user", "project", "local"],
        sandbox=_build_sandbox(request.network_access),
        effort=_resolve_effort(route.effort_override),
        env=provider_subprocess_environment_overrides(allowed_keys=frozenset({ANTHROPIC_API_KEY})),
    )


def _resolve_native_tools(access: ProviderNativeAccess) -> tuple[str, ...]:
    if access is ProviderNativeAccess.FULL:
        return _CLAUDE_FULL_NATIVE_TOOLS
    if access is ProviderNativeAccess.RESTRICTED:
        return _CLAUDE_RESTRICTED_NATIVE_TOOLS
    return ()


def _build_sandbox(network_access: NetworkAccess) -> SandboxSettings | None:
    if network_access is NetworkAccess.ALLOW:
        return None
    sandbox: dict[str, object] = {
        "enabled": True,
        "failIfUnavailable": True,
        "autoAllowBashIfSandboxed": True,
        "excludedCommands": [],
        "allowUnsandboxedCommands": False,
        "network": {
            "allowedDomains": ["127.0.0.1", "localhost", "::1"],
            "allowUnixSockets": [],
            "allowAllUnixSockets": False,
            "allowLocalBinding": False,
        },
    }
    return cast(SandboxSettings, sandbox)


def _resolve_effort(value: str | None) -> EffortLevel | None:
    if value is None:
        return None
    if value not in _CLAUDE_EFFORTS:
        raise ProviderStartError(
            kind=ProviderStartFailureKind.DEFINITE_FAILURE,
            code=ProviderStartErrorCode.CONFIGURATION,
        )
    return cast(EffortLevel, value)


async def _disconnect_client(client: ClaudeSDKClient) -> None:
    try:
        await client.disconnect()
    except Exception:
        pass


__all__ = ["ClaudeAdapter"]
