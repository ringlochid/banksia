from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from autoclaw.definitions.contracts.registry import NetworkAccess, ProviderNativeAccess
from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.integrations.codex import CodexAdapter
from autoclaw.runtime.contracts.provider_resolution import CodexProviderRoute
from autoclaw.runtime.providers.contracts import (
    DispatchStartRequest,
    ManagedNodeMcpConnection,
    ProviderAuthenticationMethod,
    ProviderCheckAxisStatus,
    ProviderCheckStatus,
    ProviderStartError,
    ProviderStartErrorCode,
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


def _request() -> DispatchStartRequest:
    return DispatchStartRequest(
        task_id="task-1",
        dispatch_id="dispatch-1",
        provider_start_revision=0,
        working_directory=Path("/tmp/workspace"),
        instructions=b"exact instructions",
        input=b"exact input",
        provider_route=CodexProviderRoute(
            kind=ProviderKind.CODEX,
            model_override="gpt-5",
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
    ("provider_native_access", "network_access", "expected_sandbox"),
    (
        (ProviderNativeAccess.RESTRICTED, NetworkAccess.DENY, Sandbox.workspace_write),
        (ProviderNativeAccess.FULL, NetworkAccess.ALLOW, Sandbox.full_access),
    ),
)
async def test_codex_start_uses_ephemeral_overlay_and_returns_before_output(
    provider_native_access: ProviderNativeAccess,
    network_access: NetworkAccess,
    expected_sandbox: Sandbox,
) -> None:
    fake = _FakeCodex()
    adapter = CodexAdapter(
        codex_factory=cast(Callable[[], AsyncCodex], lambda: fake),
    )
    request = _request().model_copy(
        update={
            "provider_native_access": provider_native_access,
            "network_access": network_access,
        }
    )

    async with adapter.lifespan():
        await adapter.start(request)

        assert fake.thread_kwargs["developer_instructions"] == "exact instructions"
        assert fake.thread_kwargs["cwd"] == "/tmp/workspace"
        assert fake.thread_kwargs["ephemeral"] is True
        assert fake.thread_kwargs["sandbox"] is expected_sandbox
        assert fake.thread.input == "exact input"
        config = cast(dict[str, Any], fake.thread_kwargs["config"])
        node_config = config["mcp_servers"]["autoclaw_node"]
        assert node_config["http_headers"] == {"Authorization": "Bearer binding-secret"}
        assert node_config["enabled_tools"] == ["record_checkpoint", "return_boundary"]
        if expected_sandbox is Sandbox.workspace_write:
            assert config["sandbox_workspace_write"]["network_access"] is False
        else:
            assert "sandbox_workspace_write" not in config

        assert await adapter.stop("dispatch-1") is ProviderStopOutcome.STOPPED
        assert fake.turn.was_interrupted is True

    assert fake.was_closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_native_access", "network_access"),
    (
        (ProviderNativeAccess.DENIED, NetworkAccess.ALLOW),
        (ProviderNativeAccess.FULL, NetworkAccess.DENY),
    ),
)
async def test_codex_start_fails_closed_for_unsupported_policy_combinations(
    provider_native_access: ProviderNativeAccess,
    network_access: NetworkAccess,
) -> None:
    fake = _FakeCodex()
    adapter = CodexAdapter(
        codex_factory=cast(Callable[[], AsyncCodex], lambda: fake),
    )
    request = _request().model_copy(
        update={
            "provider_native_access": provider_native_access,
            "network_access": network_access,
        }
    )

    async with adapter.lifespan():
        with pytest.raises(ProviderStartError) as raised:
            await adapter.start(request)

    assert raised.value.code is ProviderStartErrorCode.UNSUPPORTED
    assert fake.thread_kwargs == {}
