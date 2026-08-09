from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from claude_agent_sdk.types import (
    HookCallback,
    HookJSONOutput,
    PreToolUseHookInput,
    PreToolUseHookSpecificOutput,
    SyncHookJSONOutput,
)

from banksia.integrations.claude import ClaudeAdapter
from banksia.integrations.claude.native_identity import (
    ClaudeAuthenticationState,
    ClaudeEndpointPolicyState,
    ClaudeSubscriptionClass,
)
from banksia.providers import (
    ManagedSandboxMode,
    NetworkAccess,
    ProviderNativeAccess,
)
from banksia.runtime.providers.contracts import (
    DispatchStartRequest,
    ProviderAuthenticationMethod,
    ProviderCheckAxisStatus,
    ProviderCheckStatus,
    ProviderStartError,
    ProviderStartErrorCode,
    ProviderSteerOutcome,
    ProviderStopOutcome,
)
from tests.unit.integrations.claude.task_adapter_test_support import (
    FakeClaudeClient,
    authentication,
    clear_policy,
    task_request,
)


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
        authentication_reader=lambda: authentication(method),
        endpoint_policy_reader=clear_policy,
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
        ),
        endpoint_policy_reader=clear_policy,
    )

    async with adapter.lifespan():
        result = await adapter.read_availability()

    assert result.status is ProviderCheckStatus.UNAVAILABLE
    assert result.authentication is ProviderCheckAxisStatus.FAILED


@pytest.mark.asyncio
async def test_claude_start_uses_disposable_scoped_client_and_returns_before_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients: list[FakeClaudeClient] = []

    def build_client(options: ClaudeAgentOptions) -> FakeClaudeClient:
        client = FakeClaudeClient(options)
        clients.append(client)
        return client

    adapter = ClaudeAdapter(
        client_factory=cast(Callable[[ClaudeAgentOptions], ClaudeSDKClient], build_client),
        authentication_reader=authentication,
        endpoint_policy_reader=clear_policy,
    )

    async with adapter.lifespan():
        await adapter.start(task_request())
        client = clients[0]

        assert client.was_connected is True
        assert client.mcp_status_reads == 2
        assert client.query_input == "exact input"
        assert str(client.options.cwd) == str(Path.cwd())
        assert client.options.system_prompt == "exact instructions"
        assert client.options.permission_mode == "dontAsk"
        assert client.options.strict_mcp_config is True
        assert client.options.setting_sources == []
        assert client.options.skills == []
        assert client.options.plugins == []
        assert client.options.agents == {}
        assert client.options.continue_conversation is False
        assert client.options.resume is None
        assert client.options.extra_args == {
            "disable-slash-commands": None,
            "no-chrome": None,
            "no-session-persistence": None,
        }
        assert "safe-mode" not in client.options.extra_args
        assert "bare" not in client.options.extra_args
        settings = json.loads(cast(str, client.options.settings))
        assert settings["attribution"] == {"commit": "", "pr": ""}
        assert settings["autoMemoryEnabled"] is False
        assert settings["disableClaudeAiConnectors"] is True
        assert settings["disableAgentView"] is True
        assert settings["disableArtifact"] is True
        assert client.options.env["CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS"] == "1"
        assert client.options.env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
        assert client.options.env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] == "1"
        assert client.options.env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
        assert client.options.env["CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS"] == "1"
        assert client.options.env["CLAUDE_CODE_SKIP_PROMPT_HISTORY"] == "1"
        assert {"Agent", "Artifact", "Skill", "SlashCommand"} <= set(
            client.options.disallowed_tools
        )
        assert {"Agent", "Artifact", "Skill", "SlashCommand"}.isdisjoint(
            client.options.allowed_tools
        )
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
async def test_claude_interrupts_then_steers_the_same_live_session() -> None:
    clients: list[FakeClaudeClient] = []

    def build_client(options: ClaudeAgentOptions) -> FakeClaudeClient:
        client = FakeClaudeClient(options)
        clients.append(client)
        return client

    adapter = ClaudeAdapter(
        client_factory=cast(Callable[[ClaudeAgentOptions], ClaudeSDKClient], build_client),
        authentication_reader=authentication,
        endpoint_policy_reader=clear_policy,
    )

    async with adapter.lifespan():
        await adapter.start(task_request())
        assert await adapter.can_steer("dispatch-1") is True
        assert (
            await adapter.steer("dispatch-1", "Re-read AGENTS.md before continuing.")
            is ProviderSteerOutcome.DELIVERED
        )
        assert clients[0].was_interrupted is True
        assert clients[0].query_inputs == [
            "exact input",
            "Re-read AGENTS.md before continuing.",
        ]
        assert await adapter.can_steer("dispatch-1") is True
        assert await adapter.stop("dispatch-1") is ProviderStopOutcome.STOPPED


@pytest.mark.asyncio
async def test_claude_api_key_task_uses_standard_mode_and_rejects_endpoint_policy() -> None:
    clients: list[FakeClaudeClient] = []

    def build_client(options: ClaudeAgentOptions) -> FakeClaudeClient:
        client = FakeClaudeClient(options)
        clients.append(client)
        return client

    adapter = ClaudeAdapter(
        client_factory=cast(Callable[[ClaudeAgentOptions], ClaudeSDKClient], build_client),
        authentication_reader=lambda: authentication(ProviderAuthenticationMethod.API_KEY),
        endpoint_policy_reader=clear_policy,
    )

    async with adapter.lifespan():
        await adapter.start(task_request())
        assert "bare" not in clients[0].options.extra_args
        assert "safe-mode" not in clients[0].options.extra_args
        assert await adapter.stop("dispatch-1") is ProviderStopOutcome.STOPPED

    blocked = ClaudeAdapter(
        client_factory=cast(Callable[[ClaudeAgentOptions], ClaudeSDKClient], build_client),
        authentication_reader=lambda: authentication(ProviderAuthenticationMethod.API_KEY),
        endpoint_policy_reader=lambda: ClaudeEndpointPolicyState(
            is_installed=True,
            code="claude_endpoint_policy_unsupported",
        ),
    )
    async with blocked.lifespan():
        with pytest.raises(ProviderStartError) as error:
            await blocked.start(task_request())
    assert error.value.code is ProviderStartErrorCode.UNAVAILABLE
    assert len(clients) == 1


@pytest.mark.asyncio
async def test_claude_start_fails_before_query_for_managed_identity_or_wrong_mcp_readback() -> None:
    clients: list[FakeClaudeClient] = []

    class WrongMcpClient(FakeClaudeClient):
        async def get_mcp_status(self) -> dict[str, object]:
            status = await super().get_mcp_status()
            server = cast(dict[str, object], cast(list[object], status["mcpServers"])[0])
            server["tools"] = [
                {"name": "checkpoint"},
                {"name": "delegate"},
                {"name": "ambient"},
            ]
            return status

    def build_client(options: ClaudeAgentOptions) -> FakeClaudeClient:
        client = WrongMcpClient(options)
        clients.append(client)
        return client

    managed_adapter = ClaudeAdapter(
        client_factory=cast(Callable[[ClaudeAgentOptions], ClaudeSDKClient], build_client),
        authentication_reader=lambda: ClaudeAuthenticationState(
            is_authenticated=True,
            method=ProviderAuthenticationMethod.SUBSCRIPTION,
            code="claude_available",
            subscription_class=ClaudeSubscriptionClass.MANAGED,
        ),
        endpoint_policy_reader=clear_policy,
    )
    async with managed_adapter.lifespan():
        with pytest.raises(ProviderStartError) as managed_error:
            await managed_adapter.start(task_request())

    assert managed_error.value.code is ProviderStartErrorCode.UNAVAILABLE
    assert clients == []

    wrong_mcp_adapter = ClaudeAdapter(
        client_factory=cast(Callable[[ClaudeAgentOptions], ClaudeSDKClient], build_client),
        authentication_reader=authentication,
        endpoint_policy_reader=clear_policy,
    )
    async with wrong_mcp_adapter.lifespan():
        with pytest.raises(ProviderStartError) as wrong_mcp_error:
            await wrong_mcp_adapter.start(task_request())

    assert wrong_mcp_error.value.code is ProviderStartErrorCode.UNAVAILABLE
    assert clients[0].query_input is None
    assert clients[0].was_disconnected is True


@pytest.mark.asyncio
async def test_claude_read_only_mode_has_a_distinct_native_tool_projection() -> None:
    clients: list[FakeClaudeClient] = []

    def build_client(options: ClaudeAgentOptions) -> FakeClaudeClient:
        client = FakeClaudeClient(options)
        clients.append(client)
        return client

    adapter = ClaudeAdapter(
        client_factory=cast(Callable[[ClaudeAgentOptions], ClaudeSDKClient], build_client),
        authentication_reader=authentication,
        endpoint_policy_reader=clear_policy,
    )
    request = task_request().model_copy(
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
    options = await _started_options(task_request(working_directory=workspace))
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
    options = await _started_options(task_request(working_directory=workspace))
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
    options = await _started_options(task_request(working_directory=workspace))
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
        task_request(working_directory=tmp_path).model_copy(
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
    clients: list[FakeClaudeClient] = []

    def build_client(options: ClaudeAgentOptions) -> FakeClaudeClient:
        client = FakeClaudeClient(options)
        clients.append(client)
        return client

    adapter = ClaudeAdapter(
        client_factory=cast(Callable[[ClaudeAgentOptions], ClaudeSDKClient], build_client),
        authentication_reader=authentication,
        endpoint_policy_reader=clear_policy,
    )

    async with adapter.lifespan():
        await adapter.start(task_request().model_copy(update={"working_directory": tmp_path}))

    assert clients[0].was_disconnected is True
    assert clients[0].was_interrupted is False


async def _started_options(request: DispatchStartRequest) -> ClaudeAgentOptions:
    clients: list[FakeClaudeClient] = []

    def build_client(options: ClaudeAgentOptions) -> FakeClaudeClient:
        client = FakeClaudeClient(options)
        clients.append(client)
        return client

    adapter = ClaudeAdapter(
        client_factory=cast(Callable[[ClaudeAgentOptions], ClaudeSDKClient], build_client),
        authentication_reader=authentication,
        endpoint_policy_reader=clear_policy,
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
