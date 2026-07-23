from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import cast

import pytest
from banksia.integrations.claude import ClaudeAdapter
from banksia.integrations.claude.native_identity import ClaudeAuthenticationState
from banksia.providers import ManagedSandboxMode, NetworkAccess, ProviderKind, ProviderNativeAccess
from banksia.runtime.contracts.provider_resolution import ClaudeProviderRoute
from banksia.runtime.providers.contracts import (
    DispatchStartRequest,
    ManagedNodeMcpConnection,
    ProviderAuthenticationMethod,
    ProviderCheckAxisStatus,
    ProviderCheckStatus,
    ProviderStopOutcome,
)
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from claude_agent_sdk.types import (
    HookCallback,
    HookJSONOutput,
    PreToolUseHookInput,
    PreToolUseHookSpecificOutput,
    SyncHookJSONOutput,
)
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


def _request(*, working_directory: Path | None = None) -> DispatchStartRequest:
    return DispatchStartRequest(
        task_id="task-1",
        dispatch_id="dispatch-1",
        provider_start_revision=0,
        working_directory=working_directory or Path.cwd(),
        instructions=b"exact instructions",
        input=b"exact input",
        provider_route=ClaudeProviderRoute(
            kind=ProviderKind.CLAUDE,
            model_override="claude-sonnet-4-5",
            effort_override="high",
        ),
        provider_native_access=ProviderNativeAccess.RESTRICTED,
        network_access=NetworkAccess.DENY,
        sandbox_mode=ManagedSandboxMode.WORKSPACE_WRITE,
        managed_node_mcp=ManagedNodeMcpConnection(
            url="http://127.0.0.1:8123/_internal/node/mcp",
            bearer_token=SecretStr("binding-secret"),
            enabled_tools=("checkpoint", "return_boundary"),
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
        assert str(client.options.cwd) == str(Path.cwd())
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
        assert "WebFetch" not in client.options.allowed_tools
        assert "WebSearch" not in client.options.allowed_tools
        assert client.options.sandbox is not None
        assert client.options.hooks is not None
        assert "PreToolUse" in client.options.hooks
        sandbox = cast(dict[str, object], client.options.sandbox)
        assert sandbox["failIfUnavailable"] is True
        assert sandbox["allowUnsandboxedCommands"] is False
        assert "mcp__banksia_node__checkpoint" in client.options.allowed_tools
        mcp_servers = cast(dict[str, object], client.options.mcp_servers)
        mcp_config = cast(dict[str, object], mcp_servers["banksia_node"])
        assert mcp_config.get("headers") == {"Authorization": "Bearer binding-secret"}

        assert await adapter.stop("dispatch-1") is ProviderStopOutcome.STOPPED
        assert client.was_interrupted is True
        assert client.was_disconnected is True


@pytest.mark.asyncio
async def test_claude_read_only_mode_has_a_distinct_native_tool_projection() -> None:
    clients: list[_FakeClaudeClient] = []

    def build_client(options: ClaudeAgentOptions) -> _FakeClaudeClient:
        client = _FakeClaudeClient(options)
        clients.append(client)
        return client

    adapter = ClaudeAdapter(
        client_factory=cast(Callable[[ClaudeAgentOptions], ClaudeSDKClient], build_client),
    )
    request = _request().model_copy(
        update={
            "sandbox_mode": ManagedSandboxMode.READ_ONLY,
            "provider_native_access": ProviderNativeAccess.DENIED,
        }
    )

    async with adapter.lifespan():
        await adapter.start(request)
        allowed = clients[0].options.allowed_tools
        assert "Read" in allowed
        assert "Glob" in allowed
        assert "Write" not in allowed
        assert "Edit" not in allowed
        assert "Bash" not in allowed
        assert await adapter.stop("dispatch-1") is ProviderStopOutcome.STOPPED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "path_field"),
    (("Write", "file_path"), ("Edit", "file_path"), ("NotebookEdit", "notebook_path")),
)
async def test_claude_workspace_write_hook_denies_every_outside_target(
    tmp_path: Path,
    tool_name: str,
    path_field: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    options = await _started_options(_request(working_directory=workspace))
    hook = _pre_tool_hook(options)

    for target in (
        str(tmp_path / "outside.txt"),
        "../outside.txt",
    ):
        outcome = await hook(
            _pre_tool_input(tool_name=tool_name, tool_input={path_field: target}),
            "tool-use-1",
            {"signal": None},
        )
        assert _permission_decision(outcome) == "deny"


@pytest.mark.asyncio
async def test_claude_workspace_write_hook_denies_symlink_escape_and_allows_regular_path(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "escape").symlink_to(outside, target_is_directory=True)
    options = await _started_options(_request(working_directory=workspace))
    hook = _pre_tool_hook(options)

    escaped = await hook(
        _pre_tool_input(tool_name="Write", tool_input={"file_path": "escape/result.txt"}),
        "tool-use-escape",
        {"signal": None},
    )
    allowed = await hook(
        _pre_tool_input(
            tool_name="Write",
            tool_input={"file_path": ".banksia/t_01234567/notes/result.txt"},
        ),
        "tool-use-inside",
        {"signal": None},
    )

    assert _permission_decision(escaped) == "deny"
    assert allowed == {}


@pytest.mark.asyncio
async def test_claude_workspace_write_hook_denies_existing_hardlink_target(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (workspace / "linked.txt").hardlink_to(outside)
    options = await _started_options(_request(working_directory=workspace))
    hook = _pre_tool_hook(options)

    outcome = await hook(
        _pre_tool_input(tool_name="Edit", tool_input={"file_path": "linked.txt"}),
        "tool-use-hardlink",
        {"signal": None},
    )

    assert _permission_decision(outcome) == "deny"


@pytest.mark.asyncio
async def test_claude_workspace_write_network_allow_exposes_network_tools_honestly(
    tmp_path: Path,
) -> None:
    options = await _started_options(
        _request(working_directory=tmp_path).model_copy(
            update={"network_access": NetworkAccess.ALLOW}
        )
    )

    assert "WebFetch" in options.allowed_tools
    assert "WebSearch" in options.allowed_tools
    assert "WebFetch" not in options.disallowed_tools
    assert "WebSearch" not in options.disallowed_tools
    assert options.sandbox is None


@pytest.mark.asyncio
async def test_claude_lifespan_disconnects_without_waiting_for_interrupt(
    tmp_path: Path,
) -> None:
    clients: list[_FakeClaudeClient] = []

    def build_client(options: ClaudeAgentOptions) -> _FakeClaudeClient:
        client = _FakeClaudeClient(options)
        clients.append(client)
        return client

    adapter = ClaudeAdapter(
        client_factory=cast(Callable[[ClaudeAgentOptions], ClaudeSDKClient], build_client),
    )

    async with adapter.lifespan():
        await adapter.start(_request().model_copy(update={"working_directory": tmp_path}))

    assert clients[0].was_disconnected is True
    assert clients[0].was_interrupted is False


async def _started_options(request: DispatchStartRequest) -> ClaudeAgentOptions:
    clients: list[_FakeClaudeClient] = []

    def build_client(options: ClaudeAgentOptions) -> _FakeClaudeClient:
        client = _FakeClaudeClient(options)
        clients.append(client)
        return client

    adapter = ClaudeAdapter(
        client_factory=cast(Callable[[ClaudeAgentOptions], ClaudeSDKClient], build_client),
    )
    async with adapter.lifespan():
        await adapter.start(request)
        options = clients[0].options
        assert await adapter.stop(request.dispatch_id) is ProviderStopOutcome.STOPPED
    return options


def _pre_tool_input(
    *,
    tool_name: str,
    tool_input: dict[str, object],
) -> PreToolUseHookInput:
    return cast(
        PreToolUseHookInput,
        {
            "session_id": "session-1",
            "transcript_path": "/tmp/transcript.jsonl",
            "cwd": str(Path.cwd()),
            "agent_id": "agent-1",
            "agent_type": "main",
            "hook_event_name": "PreToolUse",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_use_id": "tool-use-1",
        },
    )


def _pre_tool_hook(options: ClaudeAgentOptions) -> HookCallback:
    assert options.hooks is not None
    matchers = options.hooks["PreToolUse"]
    assert len(matchers) == 1
    assert len(matchers[0].hooks) == 1
    return matchers[0].hooks[0]


def _permission_decision(output: HookJSONOutput) -> str | None:
    sync_output = cast(SyncHookJSONOutput, output)
    raw_specific_output = sync_output.get("hookSpecificOutput")
    assert raw_specific_output is not None
    specific_output = cast(
        PreToolUseHookSpecificOutput,
        raw_specific_output,
    )
    return specific_output.get("permissionDecision")
