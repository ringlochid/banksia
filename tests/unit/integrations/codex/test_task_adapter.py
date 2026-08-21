from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import SecretStr

from oh_my_subagents.integrations.codex import CodexAdapter
from oh_my_subagents.providers import (
    ManagedExtensionMode,
    ManagedSandboxMode,
    NetworkAccess,
    ProviderKind,
    ProviderNativeAccess,
)
from oh_my_subagents.runtime.contracts.provider_resolution import CodexProviderRoute
from oh_my_subagents.runtime.providers.contracts import (
    DispatchStartRequest,
    ManagedNodeMcpConnection,
    ProviderAuthenticationMethod,
    ProviderCheckAxisStatus,
    ProviderCheckStatus,
    ProviderStartError,
    ProviderStartErrorCode,
    ProviderStartFailureKind,
    ProviderSteerOutcome,
    ProviderStopOutcome,
)
from tests.unit.integrations.codex.task_adapter_test_support import (
    FakeCodexClient,
    FakeCodexClientFactory,
)


def _request(
    working_directory: Path,
    *,
    dispatch_id: str = "dispatch-1",
    sandbox_mode: ManagedSandboxMode = ManagedSandboxMode.WORKSPACE_WRITE,
    network_access: NetworkAccess = NetworkAccess.DENY,
    extension_mode: ManagedExtensionMode = ManagedExtensionMode.ISOLATED,
    effort: str = "high",
) -> DispatchStartRequest:
    native_access = {
        ManagedSandboxMode.READ_ONLY: ProviderNativeAccess.DENIED,
        ManagedSandboxMode.WORKSPACE_WRITE: ProviderNativeAccess.RESTRICTED,
        ManagedSandboxMode.FULL_ACCESS: ProviderNativeAccess.FULL,
    }[sandbox_mode]
    return DispatchStartRequest(
        task_id="task-1",
        dispatch_id=dispatch_id,
        provider_start_revision=0,
        working_directory=working_directory,
        instructions="exact instructions",
        input="exact input",
        provider_route=CodexProviderRoute(
            kind=ProviderKind.CODEX,
            model_override="gpt-5",
            effort_override=effort,
        ),
        provider_native_access=native_access,
        network_access=network_access,
        sandbox_mode=sandbox_mode,
        extension_mode=extension_mode,
        managed_node_mcp=ManagedNodeMcpConnection(
            url="http://127.0.0.1:8123/_internal/node/mcp",
            bearer_token=SecretStr("binding-secret"),
            enabled_tools=("checkpoint", "delegate"),
        ),
    )


def _assert_isolated_codex_start(
    client: FakeCodexClient,
    workspace: Path,
    *,
    expected_sandbox: str,
    sandbox_mode: ManagedSandboxMode,
) -> None:
    assert [method for method, _ in client.calls] == [
        "config/read",
        "skills/list",
        "thread/start",
        "mcpServerStatus/list",
    ]
    assert client.turn_input == "exact input"
    assert client.thread_params is not None
    params = client.thread_params
    assert params["approvalPolicy"] == "never"
    assert params["allowProviderModelFallback"] is False
    assert params["cwd"] == str(workspace)
    assert params["developerInstructions"] == "exact instructions"
    assert params["ephemeral"] is True
    assert params["model"] == "gpt-5"
    assert params["personality"] == "none"
    assert params["runtimeWorkspaceRoots"] == [str(workspace)]
    assert params["sandbox"] == expected_sandbox
    assert params["selectedCapabilityRoots"] == []
    assert "environments" not in params

    config = cast(dict[str, Any], params["config"])
    assert config["projects"] == {str(workspace): {"trust_level": "untrusted"}}
    assert config["project_doc_max_bytes"] == 0
    assert config["mcp_servers"]["ambient_docs"] == {"enabled": False}
    node = config["mcp_servers"]["oms_node"]
    assert node == {
        "default_tools_approval_mode": "approve",
        "enabled": True,
        "enabled_tools": ["checkpoint", "delegate"],
        "http_headers": {"Authorization": "Bearer binding-secret"},
        "required": True,
        "url": "http://127.0.0.1:8123/_internal/node/mcp",
    }
    assert config["skills"] == {
        "bundled": {"enabled": False},
        "config": [
            {
                "enabled": False,
                "path": str(workspace / ".agents" / "skills" / "review" / "SKILL.md"),
            },
            {
                "enabled": False,
                "path": str(workspace / ".codex" / "skills" / "ambient" / "SKILL.md"),
            },
        ],
        "include_instructions": False,
    }
    assert config["features"]["plugins"] is False
    assert config["features"]["remote_plugin"] is False
    assert config["features"]["multi_agent"] is False
    assert config["features"]["hooks"] is False
    assert config["features"]["artifact"] is False
    assert config["features"]["shell_tool"] is True
    assert config["features"]["unified_exec"] is True
    assert "include_environment_context" not in config
    assert "include_permissions_instructions" not in config
    if sandbox_mode is ManagedSandboxMode.WORKSPACE_WRITE:
        assert config["sandbox_workspace_write"] == {"network_access": False}
    else:
        assert "sandbox_workspace_write" not in config
    assert client.turn_params == {
        "approvalPolicy": "never",
        "effort": "high",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "account",
        "requires_openai_auth",
        "expected_status",
        "expected_authentication",
        "expected_method",
    ),
    (
        (
            SimpleNamespace(root=SimpleNamespace(type="chatgpt")),
            False,
            ProviderCheckStatus.AVAILABLE,
            ProviderCheckAxisStatus.PASSED,
            ProviderAuthenticationMethod.SUBSCRIPTION,
        ),
        (
            SimpleNamespace(root=SimpleNamespace(type="apiKey")),
            True,
            ProviderCheckStatus.AVAILABLE,
            ProviderCheckAxisStatus.PASSED,
            ProviderAuthenticationMethod.API_KEY,
        ),
        (
            SimpleNamespace(root=SimpleNamespace(type="amazonBedrock")),
            False,
            ProviderCheckStatus.AVAILABLE,
            ProviderCheckAxisStatus.NOT_CHECKED,
            None,
        ),
        (
            None,
            False,
            ProviderCheckStatus.AVAILABLE,
            ProviderCheckAxisStatus.NOT_CHECKED,
            None,
        ),
        (
            None,
            True,
            ProviderCheckStatus.UNAVAILABLE,
            ProviderCheckAxisStatus.FAILED,
            None,
        ),
    ),
)
async def test_codex_check_uses_a_bounded_low_level_client(
    account: object | None,
    requires_openai_auth: bool,
    expected_status: ProviderCheckStatus,
    expected_authentication: ProviderCheckAxisStatus,
    expected_method: ProviderAuthenticationMethod | None,
) -> None:
    factory = FakeCodexClientFactory(
        account=account,
        requires_openai_auth=requires_openai_auth,
    )
    adapter = CodexAdapter(codex_factory=factory)

    async with adapter.lifespan():
        result = await adapter.read_availability()

    assert result.status is expected_status
    assert result.authentication is expected_authentication
    assert result.authentication_method is expected_method
    assert result.reachability is ProviderCheckAxisStatus.NOT_CHECKED
    assert len(factory.clients) == 1
    assert factory.clients[0].was_closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sandbox_mode", "network_access", "expected_sandbox"),
    (
        (
            ManagedSandboxMode.READ_ONLY,
            NetworkAccess.DENY,
            "read-only",
        ),
        (
            ManagedSandboxMode.WORKSPACE_WRITE,
            NetworkAccess.DENY,
            "workspace-write",
        ),
        (
            ManagedSandboxMode.FULL_ACCESS,
            NetworkAccess.ALLOW,
            "danger-full-access",
        ),
    ),
)
async def test_codex_start_isolates_each_dispatch_before_starting_its_turn(
    tmp_path: Path,
    sandbox_mode: ManagedSandboxMode,
    network_access: NetworkAccess,
    expected_sandbox: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    factory = FakeCodexClientFactory()
    adapter = CodexAdapter(codex_factory=factory)

    async with adapter.lifespan():
        await adapter.start(
            _request(
                workspace,
                sandbox_mode=sandbox_mode,
                network_access=network_access,
            )
        )
        await adapter.start(
            _request(
                workspace,
                dispatch_id="dispatch-2",
                sandbox_mode=sandbox_mode,
                network_access=network_access,
            )
        )

        assert len(factory.clients) == 2
        assert factory.clients[0] is not factory.clients[1]
        _assert_isolated_codex_start(
            factory.clients[0],
            workspace,
            expected_sandbox=expected_sandbox,
            sandbox_mode=sandbox_mode,
        )

        assert await adapter.stop("dispatch-1") is ProviderStopOutcome.STOPPED
        assert await adapter.stop("dispatch-2") is ProviderStopOutcome.STOPPED
        assert all(client.was_interrupted for client in factory.clients)

    assert all(client.was_closed for client in factory.clients)


@pytest.mark.asyncio
async def test_codex_steers_only_the_live_dispatch_turn(tmp_path: Path) -> None:
    factory = FakeCodexClientFactory()
    adapter = CodexAdapter(codex_factory=factory)

    async with adapter.lifespan():
        await adapter.start(_request(tmp_path))
        assert await adapter.can_steer("dispatch-1") is True
        assert (
            await adapter.steer("dispatch-1", "Re-read AGENTS.md before continuing.")
            is ProviderSteerOutcome.DELIVERED
        )
        assert factory.clients[0].steer_messages == ["Re-read AGENTS.md before continuing."]
        assert (
            await adapter.steer("dispatch-missing", "Do not deliver this.")
            is ProviderSteerOutcome.NOT_RUNNING
        )
        assert await adapter.stop("dispatch-1") is ProviderStopOutcome.STOPPED


@pytest.mark.asyncio
async def test_codex_inherits_skills_mcp_and_accepts_max(tmp_path: Path) -> None:
    factory = FakeCodexClientFactory(
        ambient_config={
            "mcp_servers": {"ambient_docs": {"enabled": True}},
            "service_tier": "fast",
        },
        ambient_mcp_tool_names=("search",),
    )
    adapter = CodexAdapter(codex_factory=factory)

    async with adapter.lifespan():
        accepted = await adapter.start(
            _request(
                tmp_path,
                sandbox_mode=ManagedSandboxMode.FULL_ACCESS,
                network_access=NetworkAccess.ALLOW,
                extension_mode=ManagedExtensionMode.INHERIT,
                effort="max",
            )
        )
        client = factory.clients[0]
        assert accepted.extension_inventory is not None
        assert accepted.extension_inventory.model_dump(mode="json") == {
            "skills": ["ambient-skill", "project-review"],
            "mcp_servers": [{"name": "ambient_docs", "tools": ["search"]}],
        }
        assert client.thread_params is not None
        config = cast(dict[str, Any], client.thread_params["config"])
        assert config["mcp_servers"] == {
            "oms_node": cast(dict[str, object], config["mcp_servers"])["oms_node"]
        }
        assert config["skills"] == {
            "bundled": {"enabled": False},
            "config": [],
            "include_instructions": True,
        }
        assert client.turn_params == {"approvalPolicy": "never", "effort": "max"}
        assert "service_tier" not in config
        assert "serviceTier" not in client.thread_params
        assert await adapter.stop("dispatch-1") is ProviderStopOutcome.STOPPED


@pytest.mark.asyncio
async def test_codex_start_rejects_ambient_instructions_before_thread_start(
    tmp_path: Path,
) -> None:
    workspace = tmp_path
    factory = FakeCodexClientFactory(
        ambient_config={
            "instructions": "ambient poison",
            "mcp_servers": {},
        }
    )
    adapter = CodexAdapter(codex_factory=factory)

    async with adapter.lifespan():
        with pytest.raises(ProviderStartError) as captured:
            await adapter.start(_request(workspace))

    assert captured.value.kind is ProviderStartFailureKind.DEFINITE_FAILURE
    assert captured.value.code is ProviderStartErrorCode.CONFIGURATION
    assert factory.clients[0].thread_params is None
    assert factory.clients[0].turn_input is None
    assert factory.clients[0].was_closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "thread_overrides",
    (
        {"instruction_sources": [SimpleNamespace(root="/tmp/AGENTS.md")]},
        {"runtime_workspace_roots": []},
    ),
)
async def test_codex_start_rejects_unproven_thread_isolation_before_turn(
    tmp_path: Path,
    thread_overrides: dict[str, object],
) -> None:
    workspace = tmp_path
    factory = FakeCodexClientFactory(thread_overrides=thread_overrides)
    adapter = CodexAdapter(codex_factory=factory)

    async with adapter.lifespan():
        with pytest.raises(ProviderStartError) as captured:
            await adapter.start(_request(workspace))

    assert captured.value.kind is ProviderStartFailureKind.DEFINITE_FAILURE
    assert captured.value.code is ProviderStartErrorCode.CONFIGURATION
    assert factory.clients[0].turn_input is None
    assert factory.clients[0].was_closed is True


@pytest.mark.asyncio
async def test_codex_start_rejects_an_inexact_node_tool_surface_before_turn(
    tmp_path: Path,
) -> None:
    workspace = tmp_path
    factory = FakeCodexClientFactory(mcp_tool_names=("checkpoint",))
    adapter = CodexAdapter(codex_factory=factory)

    async with adapter.lifespan():
        with pytest.raises(ProviderStartError) as captured:
            await adapter.start(_request(workspace))

    assert captured.value.kind is ProviderStartFailureKind.DEFINITE_FAILURE
    assert captured.value.code is ProviderStartErrorCode.CONFIGURATION
    assert factory.clients[0].turn_input is None
    assert factory.clients[0].was_closed is True


@pytest.mark.asyncio
async def test_codex_lifespan_closes_a_running_dispatch_transport(
    tmp_path: Path,
) -> None:
    factory = FakeCodexClientFactory()
    adapter = CodexAdapter(codex_factory=factory)

    async with adapter.lifespan():
        await adapter.start(_request(tmp_path))

    assert factory.clients[0].was_closed is True
    assert factory.clients[0].was_interrupted is False
