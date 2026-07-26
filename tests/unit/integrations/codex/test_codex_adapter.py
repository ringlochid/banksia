from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from openai_codex.client import CodexClient
from openai_codex.generated.v2_all import TurnCompletedNotification
from openai_codex.models import JsonObject, Notification
from pydantic import SecretStr

from banksia.integrations.codex import CodexAdapter
from banksia.providers import ManagedSandboxMode, NetworkAccess, ProviderKind, ProviderNativeAccess
from banksia.runtime.contracts.provider_resolution import CodexProviderRoute
from banksia.runtime.providers.contracts import (
    DispatchStartRequest,
    ManagedNodeMcpConnection,
    ProviderAuthenticationMethod,
    ProviderCheckAxisStatus,
    ProviderCheckStatus,
    ProviderStartError,
    ProviderStartErrorCode,
    ProviderStartFailureKind,
    ProviderStopOutcome,
)


class _DumpableConfig:
    def __init__(self, value: dict[str, object]) -> None:
        self._value = value

    def model_dump(self, **_: object) -> dict[str, object]:
        return self._value


class _FakeCodexClient:
    def __init__(
        self,
        *,
        handler: Callable[[str, JsonObject | None], JsonObject],
        suffix: int,
        ambient_config: dict[str, object] | None = None,
        thread_overrides: dict[str, object] | None = None,
        mcp_tool_names: tuple[str, ...] = ("checkpoint", "delegate"),
        account: object | None = None,
        requires_openai_auth: bool = False,
    ) -> None:
        self.handler = handler
        self.suffix = suffix
        self.ambient_config = ambient_config or {"mcp_servers": {"ambient_docs": {"enabled": True}}}
        self.thread_overrides = thread_overrides or {}
        self.mcp_tool_names = mcp_tool_names
        self.account_result = SimpleNamespace(
            account=account,
            requires_openai_auth=requires_openai_auth,
        )
        self.calls: list[tuple[str, JsonObject | None]] = []
        self.thread_params: JsonObject | None = None
        self.turn_params: JsonObject | None = None
        self.turn_input: str | None = None
        self.was_started = False
        self.was_initialized = False
        self.was_interrupted = False
        self.was_closed = False
        self._turn_finished = threading.Event()

    def start(self) -> None:
        self.was_started = True

    def initialize(self) -> object:
        self.was_initialized = True
        return object()

    def request(
        self,
        method: str,
        params: JsonObject | None,
        *,
        response_model: object,
    ) -> object:
        del response_model
        self.calls.append((method, params))
        if method == "config/read":
            return SimpleNamespace(config=_DumpableConfig(self.ambient_config))
        if method == "skills/list":
            cwd = cast(list[str], cast(dict[str, Any], params)["cwds"])[0]
            skill_path = str(Path(cwd) / ".codex" / "skills" / "ambient" / "SKILL.md")
            skill = SimpleNamespace(path=SimpleNamespace(root=skill_path))
            return SimpleNamespace(data=[SimpleNamespace(cwd=cwd, errors=[], skills=[skill])])
        if method == "thread/start":
            assert params is not None
            self.thread_params = params
            cwd = cast(str, params["cwd"])
            sandbox = cast(str, params["sandbox"])
            sandbox_type = {
                "read-only": "readOnly",
                "workspace-write": "workspaceWrite",
                "danger-full-access": "dangerFullAccess",
            }[sandbox]
            network_access = False
            config = cast(dict[str, Any], params["config"])
            if sandbox == "workspace-write":
                network_access = cast(
                    bool,
                    config["sandbox_workspace_write"]["network_access"],
                )
            response: dict[str, object] = {
                "approval_policy": SimpleNamespace(root="never"),
                "cwd": SimpleNamespace(root=cwd),
                "instruction_sources": [],
                "model": params["model"],
                "runtime_workspace_roots": [SimpleNamespace(root=cwd)],
                "sandbox": SimpleNamespace(
                    root=SimpleNamespace(
                        type=sandbox_type,
                        network_access=network_access,
                    )
                ),
                "thread": SimpleNamespace(
                    cwd=SimpleNamespace(root=cwd),
                    ephemeral=True,
                    id=f"thread-{self.suffix}",
                ),
            }
            response.update(self.thread_overrides)
            return SimpleNamespace(**response)
        if method == "mcpServerStatus/list":
            return SimpleNamespace(
                data=[
                    SimpleNamespace(
                        name="ambient_docs",
                        resource_templates=[],
                        resources=[],
                        server_info=None,
                        tools={},
                    ),
                    SimpleNamespace(
                        name="banksia_node",
                        resource_templates=[],
                        resources=[],
                        server_info=object(),
                        tools={name: object() for name in self.mcp_tool_names},
                    ),
                ],
                next_cursor=None,
            )
        raise AssertionError(f"unexpected request: {method}")

    def turn_start(
        self,
        thread_id: str,
        input_items: str,
        params: JsonObject | None = None,
    ) -> object:
        assert thread_id == f"thread-{self.suffix}"
        self.turn_input = input_items
        self.turn_params = params
        return SimpleNamespace(turn=SimpleNamespace(id=f"turn-{self.suffix}"))

    def next_turn_notification(self, turn_id: str) -> Notification:
        self._turn_finished.wait()
        payload = TurnCompletedNotification.model_validate(
            {
                "threadId": f"thread-{self.suffix}",
                "turn": {
                    "id": turn_id,
                    "items": [],
                    "status": "interrupted",
                },
            }
        )
        return Notification(method="turn/completed", payload=payload)

    def unregister_turn_notifications(self, turn_id: str) -> None:
        assert turn_id == f"turn-{self.suffix}"

    def turn_interrupt(self, thread_id: str, turn_id: str) -> object:
        assert (thread_id, turn_id) == (
            f"thread-{self.suffix}",
            f"turn-{self.suffix}",
        )
        self.was_interrupted = True
        self._turn_finished.set()
        return object()

    def account_read(self) -> object:
        return self.account_result

    def close(self) -> None:
        self.was_closed = True
        self._turn_finished.set()


class _FakeClientFactory:
    def __init__(self, **client_options: Any) -> None:
        self.client_options = client_options
        self.clients: list[_FakeCodexClient] = []

    def __call__(
        self,
        handler: Callable[[str, JsonObject | None], JsonObject],
    ) -> CodexClient:
        client = _FakeCodexClient(
            handler=handler,
            suffix=len(self.clients) + 1,
            **self.client_options,
        )
        self.clients.append(client)
        return cast(CodexClient, client)


def _request(
    working_directory: Path,
    *,
    dispatch_id: str = "dispatch-1",
    sandbox_mode: ManagedSandboxMode = ManagedSandboxMode.WORKSPACE_WRITE,
    network_access: NetworkAccess = NetworkAccess.DENY,
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
            effort_override="high",
        ),
        provider_native_access=native_access,
        network_access=network_access,
        sandbox_mode=sandbox_mode,
        managed_node_mcp=ManagedNodeMcpConnection(
            url="http://127.0.0.1:8123/_internal/node/mcp",
            bearer_token=SecretStr("binding-secret"),
            enabled_tools=("checkpoint", "delegate"),
        ),
    )


def _assert_isolated_codex_start(
    client: _FakeCodexClient,
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
    node = config["mcp_servers"]["banksia_node"]
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
                "path": str(workspace / ".codex" / "skills" / "ambient" / "SKILL.md"),
            }
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
    factory = _FakeClientFactory(
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
    factory = _FakeClientFactory()
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
async def test_codex_start_rejects_ambient_instructions_before_thread_start(
    tmp_path: Path,
) -> None:
    workspace = tmp_path
    factory = _FakeClientFactory(
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
    factory = _FakeClientFactory(thread_overrides=thread_overrides)
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
    factory = _FakeClientFactory(mcp_tool_names=("checkpoint",))
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
    factory = _FakeClientFactory()
    adapter = CodexAdapter(codex_factory=factory)

    async with adapter.lifespan():
        await adapter.start(_request(tmp_path))

    assert factory.clients[0].was_closed is True
    assert factory.clients[0].was_interrupted is False
