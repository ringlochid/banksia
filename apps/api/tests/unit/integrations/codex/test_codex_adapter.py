from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from banksia.integrations.codex import CodexAdapter
from banksia.providers import ManagedSandboxMode, NetworkAccess, ProviderKind, ProviderNativeAccess
from banksia.runtime.contracts.provider_resolution import CodexProviderRoute
from banksia.runtime.providers.contracts import (
    DispatchStartRequest,
    ManagedNodeMcpConnection,
    ProviderAuthenticationMethod,
    ProviderCheckAxisStatus,
    ProviderCheckStatus,
    ProviderStopOutcome,
)
from openai_codex import AsyncCodex, Sandbox
from pydantic import SecretStr


class _FakeCodexTurn:
    def __init__(self) -> None:
        self.was_interrupted = False
        self._done = asyncio.Event()

    async def run(self) -> None:
        await self._done.wait()

    async def interrupt(self) -> object:
        self.was_interrupted = True
        self._done.set()
        return object()


class _FakeCodexThread:
    def __init__(self, turn: _FakeCodexTurn) -> None:
        self.turn_handle = turn
        self.input: str | None = None
        self.turn_kwargs: dict[str, object] = {}

    async def turn(self, dispatch_input: str, **kwargs: object) -> _FakeCodexTurn:
        self.input = dispatch_input
        self.turn_kwargs = kwargs
        return self.turn_handle


class _FakeCodex:
    def __init__(self) -> None:
        self.turn = _FakeCodexTurn()
        self.thread = _FakeCodexThread(self.turn)
        self.thread_kwargs: dict[str, Any] = {}
        self.was_closed = False

    async def thread_start(self, **kwargs: Any) -> _FakeCodexThread:
        self.thread_kwargs = kwargs
        return self.thread

    async def close(self) -> None:
        self.was_closed = True


class _FakeAvailabilityCodex:
    def __init__(self, *, account: object | None, requires_openai_auth: bool) -> None:
        self.account_result = SimpleNamespace(
            account=account,
            requires_openai_auth=requires_openai_auth,
        )
        self.was_closed = False

    async def account(self) -> object:
        return self.account_result

    async def close(self) -> None:
        self.was_closed = True


def _request(*, working_directory: Path | None = None) -> DispatchStartRequest:
    return DispatchStartRequest(
        task_id="task-1",
        dispatch_id="dispatch-1",
        provider_start_revision=0,
        working_directory=working_directory or Path("/tmp/workspace"),
        instructions="exact instructions",
        input="exact input",
        provider_route=CodexProviderRoute(
            kind=ProviderKind.CODEX,
            model_override="gpt-5",
            effort_override="high",
        ),
        provider_native_access=ProviderNativeAccess.RESTRICTED,
        network_access=NetworkAccess.DENY,
        sandbox_mode=ManagedSandboxMode.WORKSPACE_WRITE,
        managed_node_mcp=ManagedNodeMcpConnection(
            url="http://127.0.0.1:8123/_internal/node/mcp",
            bearer_token=SecretStr("binding-secret"),
            enabled_tools=("checkpoint", "delegate"),
        ),
    )


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
            SimpleNamespace(
                root=SimpleNamespace(
                    type="amazonBedrock",
                    credential_source="awsManaged",
                )
            ),
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
async def test_codex_check_reports_only_missing_required_authentication(
    account: object | None,
    requires_openai_auth: bool,
    expected_status: ProviderCheckStatus,
    expected_authentication: ProviderCheckAxisStatus,
    expected_method: ProviderAuthenticationMethod | None,
) -> None:
    fake = _FakeAvailabilityCodex(
        account=account,
        requires_openai_auth=requires_openai_auth,
    )
    adapter = CodexAdapter(
        codex_factory=cast(Callable[[], AsyncCodex], lambda: fake),
    )

    async with adapter.lifespan():
        result = await adapter.read_availability()

    assert result.status is expected_status
    assert result.authentication is expected_authentication
    assert result.authentication_method is expected_method
    assert result.reachability is ProviderCheckAxisStatus.NOT_CHECKED
    assert fake.was_closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sandbox_mode", "provider_native_access", "network_access", "expected_sandbox"),
    (
        (
            ManagedSandboxMode.READ_ONLY,
            ProviderNativeAccess.DENIED,
            NetworkAccess.DENY,
            Sandbox.read_only,
        ),
        (
            ManagedSandboxMode.WORKSPACE_WRITE,
            ProviderNativeAccess.RESTRICTED,
            NetworkAccess.DENY,
            Sandbox.workspace_write,
        ),
        (
            ManagedSandboxMode.FULL_ACCESS,
            ProviderNativeAccess.FULL,
            NetworkAccess.ALLOW,
            Sandbox.full_access,
        ),
    ),
)
async def test_codex_start_uses_ephemeral_overlay_and_returns_before_output(
    tmp_path: Path,
    sandbox_mode: ManagedSandboxMode,
    provider_native_access: ProviderNativeAccess,
    network_access: NetworkAccess,
    expected_sandbox: Sandbox,
) -> None:
    fake = _FakeCodex()
    adapter = CodexAdapter(
        codex_factory=cast(Callable[[], AsyncCodex], lambda: fake),
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".banksia").mkdir()
    request = _request(working_directory=workspace).model_copy(
        update={
            "provider_native_access": provider_native_access,
            "network_access": network_access,
            "sandbox_mode": sandbox_mode,
        }
    )

    async with adapter.lifespan():
        await adapter.start(request)

        assert fake.thread_kwargs["developer_instructions"] == "exact instructions"
        assert fake.thread_kwargs["cwd"] == str(workspace)
        assert fake.thread_kwargs["ephemeral"] is True
        assert fake.thread_kwargs["sandbox"] is expected_sandbox
        assert fake.thread.input == "exact input"
        config = cast(dict[str, Any], fake.thread_kwargs["config"])
        node_config = config["mcp_servers"]["banksia_node"]
        assert node_config["http_headers"] == {"Authorization": "Bearer binding-secret"}
        assert node_config["enabled_tools"] == ["checkpoint", "delegate"]
        if expected_sandbox is Sandbox.workspace_write:
            assert config["sandbox_workspace_write"]["network_access"] is False
        else:
            assert "sandbox_workspace_write" not in config

        assert await adapter.stop("dispatch-1") is ProviderStopOutcome.STOPPED
        assert fake.turn.was_interrupted is True

    assert fake.was_closed is True


@pytest.mark.asyncio
async def test_codex_lifespan_closes_transport_without_waiting_for_turn_interrupt() -> None:
    fake = _FakeCodex()
    adapter = CodexAdapter(
        codex_factory=cast(Callable[[], AsyncCodex], lambda: fake),
    )

    async with adapter.lifespan():
        await adapter.start(_request())

    assert fake.was_closed is True
    assert fake.turn.was_interrupted is False
