from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import banksia.integrations.operator as operator_module
from banksia.config import (
    ClaudeSettings,
    CodexSettings,
    OperatorProvider,
    OperatorSettings,
    RuntimeSettings,
    Settings,
)
from banksia.integrations.claude.native_identity import (
    ClaudeInvocationReadiness,
    ClaudeIsolationMode,
)
from banksia.operator import (
    OperatorProviderMessageResult,
    OperatorTurnOutcome,
    OperatorTurnRequest,
)
from banksia.operator.provider import (
    OperatorMessageTurnInput,
    OperatorProviderUnavailableError,
)
from banksia.providers import ProviderKind
from banksia.runtime.providers import ProviderAuthenticationMethod


class RecordingProviderRunner:
    def __init__(self, **arguments: Any) -> None:
        self.arguments = arguments
        self.status = arguments["status"]
        self.requests: list[OperatorTurnRequest] = []

    async def execute_turn(self, request: OperatorTurnRequest) -> OperatorTurnOutcome:
        self.requests.append(request)
        return OperatorTurnOutcome(
            provider_thread_id="operator-thread",
            result=OperatorProviderMessageResult(kind="message", text="done"),
        )


def _recording_provider_factory(
    adapters: list[RecordingProviderRunner],
) -> Callable[..., RecordingProviderRunner]:
    def build(**arguments: Any) -> RecordingProviderRunner:
        adapter = RecordingProviderRunner(**arguments)
        adapters.append(adapter)
        return adapter

    return build


def _request(provider: str) -> OperatorTurnRequest:
    return OperatorTurnRequest(
        provider=provider,
        model=None,
        effort=None,
        provider_thread_id=None,
        input=OperatorMessageTurnInput(text="Draft a Workflow."),
    )


async def test_claude_selection_resolves_options_and_uses_stable_working_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adapters: list[RecordingProviderRunner] = []
    settings = Settings(
        data_dir=tmp_path / "data",
        claude=ClaudeSettings(enabled=True, model="claude-default", effort="medium"),
        operator=OperatorSettings(
            provider=OperatorProvider.CLAUDE,
            model="claude-operator",
        ),
    )
    monkeypatch.setattr(
        operator_module,
        "read_claude_invocation_readiness",
        lambda: ClaudeInvocationReadiness(
            method=ProviderAuthenticationMethod.SUBSCRIPTION,
            isolation_mode=ClaudeIsolationMode.STANDARD,
            code="claude_available",
        ),
    )

    async def reject_codex_check() -> object:
        raise AssertionError("unselected Codex readiness was inspected")

    monkeypatch.setattr(operator_module, "_read_codex_authentication", reject_codex_check)
    monkeypatch.setattr(
        operator_module,
        "ClaudeOperatorTurnRunner",
        _recording_provider_factory(adapters),
    )

    runner = operator_module.ConfiguredOperatorTurnRunner(
        settings=settings,
        system_prompt="exact prompt",
        tools=(),
    )
    assert runner.status.availability == "unavailable"

    async with runner.lifespan():
        outcome = await runner.execute_turn(
            OperatorTurnRequest(
                provider="claude",
                model="claude-operator",
                effort="medium",
                provider_thread_id=None,
                input=OperatorMessageTurnInput(text="Draft a Workflow."),
            )
        )

    assert outcome.provider_thread_id == "operator-thread"
    assert len(adapters) == 1
    adapter_status = adapters[0].status
    assert adapters[0].arguments == {
        "system_prompt": "exact prompt",
        "tools": (),
        "status": adapter_status,
        "working_directory": tmp_path / "data" / "operator" / "claude",
    }
    assert adapter_status.model == "claude-operator"
    assert adapter_status.effort == "medium"
    assert runner.status.availability == "unavailable"
    assert (tmp_path / "data" / "operator" / "claude").is_dir()


async def test_claude_activation_rejects_unisolatable_identity_before_workspace_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        claude=ClaudeSettings(enabled=True),
        operator=OperatorSettings(provider=OperatorProvider.CLAUDE),
    )
    monkeypatch.setattr(
        operator_module,
        "read_claude_invocation_readiness",
        lambda: ClaudeInvocationReadiness(
            method=ProviderAuthenticationMethod.SUBSCRIPTION,
            isolation_mode=None,
            code="claude_managed_subscription_unsupported",
        ),
    )

    def reject_runner(**arguments: object) -> object:
        raise AssertionError(f"unsupported Claude identity created a runner: {arguments}")

    monkeypatch.setattr(operator_module, "ClaudeOperatorTurnRunner", reject_runner)
    runner = operator_module.ConfiguredOperatorTurnRunner(
        settings=settings,
        system_prompt="prompt",
        tools=(),
    )

    async with runner.lifespan():
        assert runner.status.availability == "unavailable"

    assert not (tmp_path / "data" / "operator" / "claude").exists()


async def test_codex_selection_never_checks_or_falls_back_to_claude(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adapters: list[RecordingProviderRunner] = []
    settings = Settings(
        data_dir=tmp_path / "data",
        codex=CodexSettings(enabled=True, model="gpt-default"),
        operator=OperatorSettings(provider=OperatorProvider.CODEX, effort="high"),
        runtime=RuntimeSettings(default_provider=ProviderKind.CLAUDE),
    )

    def reject_claude_check() -> object:
        raise AssertionError("unselected Claude readiness was inspected")

    async def accept_codex_check() -> object:
        return SimpleNamespace(is_authenticated=True, code="codex_available")

    monkeypatch.setattr(
        operator_module,
        "read_claude_invocation_readiness",
        reject_claude_check,
    )
    monkeypatch.setattr(operator_module, "_read_codex_authentication", accept_codex_check)
    monkeypatch.setattr(
        operator_module,
        "CodexOperatorTurnRunner",
        _recording_provider_factory(adapters),
    )

    runner = operator_module.ConfiguredOperatorTurnRunner(
        settings=settings,
        system_prompt="exact prompt",
        tools=(),
    )
    async with runner.lifespan():
        assert runner.status.availability == "available"

    assert len(adapters) == 1
    adapter_status = adapters[0].status
    assert adapters[0].arguments == {
        "system_prompt": "exact prompt",
        "tools": (),
        "status": adapter_status,
    }
    assert adapter_status.configured_provider == "codex"
    assert adapter_status.model == "gpt-default"
    assert adapter_status.effort == "high"
    assert runner.status.availability == "unavailable"


async def test_unconfigured_disabled_and_failed_selection_stay_human_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def record_claude_check() -> object:
        calls.append("claude")
        raise AssertionError("disabled provider readiness was inspected")

    async def fail_codex_check() -> object:
        calls.append("codex")
        return SimpleNamespace(
            is_authenticated=False,
            code="codex_authentication_required",
        )

    monkeypatch.setattr(
        operator_module,
        "read_claude_invocation_readiness",
        record_claude_check,
    )
    monkeypatch.setattr(operator_module, "_read_codex_authentication", fail_codex_check)

    unconfigured = operator_module.ConfiguredOperatorTurnRunner(
        settings=Settings(),
        system_prompt="prompt",
        tools=(),
    )
    disabled = operator_module.ConfiguredOperatorTurnRunner(
        settings=Settings(operator=OperatorSettings(provider=OperatorProvider.CLAUDE)),
        system_prompt="prompt",
        tools=(),
    )
    failed = operator_module.ConfiguredOperatorTurnRunner(
        settings=Settings(
            codex=CodexSettings(enabled=True),
            operator=OperatorSettings(provider=OperatorProvider.CODEX),
        ),
        system_prompt="prompt",
        tools=(),
    )

    async with unconfigured.lifespan(), disabled.lifespan(), failed.lifespan():
        assert unconfigured.status.availability == "unconfigured"
        assert disabled.status.availability == "unavailable"
        assert "configure claude" in (disabled.status.setup_action or "")
        assert failed.status.availability == "unavailable"
        assert "login codex" in (failed.status.setup_action or "")

    assert calls == ["codex"]


async def test_codex_readiness_reads_account_once_and_closes_native_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients: list[object] = []

    class NativeClient:
        def __init__(self, config: Any) -> None:
            self.config = config
            self.account_reads = 0
            self.closes = 0

        async def account(self) -> object:
            self.account_reads += 1
            return SimpleNamespace(account=None, requires_openai_auth=False)

        async def close(self) -> None:
            self.closes += 1

    def build_client(config: object) -> NativeClient:
        client = NativeClient(config)
        clients.append(client)
        return client

    monkeypatch.setattr(operator_module, "AsyncCodex", build_client)
    monkeypatch.setattr(
        operator_module,
        "provider_subprocess_environment_overrides",
        lambda: {"ANTHROPIC_API_KEY": ""},
    )
    monkeypatch.setattr(
        operator_module,
        "CodexOperatorTurnRunner",
        RecordingProviderRunner,
    )

    runner = operator_module.ConfiguredOperatorTurnRunner(
        settings=Settings(
            codex=CodexSettings(enabled=True),
            operator=OperatorSettings(provider=OperatorProvider.CODEX),
        ),
        system_prompt="prompt",
        tools=(),
    )
    async with runner.lifespan():
        assert runner.status.availability == "available"

    assert len(clients) == 1
    client = clients[0]
    assert isinstance(client, NativeClient)
    assert client.account_reads == 1
    assert client.closes == 1
    assert client.config.env == {"ANTHROPIC_API_KEY": ""}
    assert client.config.cwd is None


async def test_runner_rejects_turns_outside_lifespan_and_rechecks_each_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readiness_checks = 0
    adapters: list[RecordingProviderRunner] = []

    async def accept_codex_check() -> object:
        nonlocal readiness_checks
        readiness_checks += 1
        return SimpleNamespace(is_authenticated=True, code="codex_available")

    monkeypatch.setattr(operator_module, "_read_codex_authentication", accept_codex_check)
    monkeypatch.setattr(
        operator_module,
        "CodexOperatorTurnRunner",
        _recording_provider_factory(adapters),
    )
    runner = operator_module.ConfiguredOperatorTurnRunner(
        settings=Settings(
            codex=CodexSettings(enabled=True),
            operator=OperatorSettings(provider=OperatorProvider.CODEX),
        ),
        system_prompt="prompt",
        tools=(),
    )

    with pytest.raises(OperatorProviderUnavailableError):
        await runner.execute_turn(_request("codex"))

    with pytest.raises(RuntimeError, match="application failure"):
        async with runner.lifespan():
            assert runner.status.availability == "available"
            await runner.execute_turn(_request("codex"))
            raise RuntimeError("application failure")

    assert runner.status.availability == "unavailable"
    with pytest.raises(OperatorProviderUnavailableError):
        await runner.execute_turn(_request("codex"))

    async with runner.lifespan():
        assert runner.status.availability == "available"

    assert readiness_checks == 2
    assert len(adapters) == 2
    assert runner.status.availability == "unavailable"


async def test_invalid_effective_claude_effort_fails_before_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readiness_checks: list[str] = []
    adapters: list[RecordingProviderRunner] = []

    def record_claude_check() -> ClaudeInvocationReadiness:
        readiness_checks.append("claude")
        return ClaudeInvocationReadiness(
            method=ProviderAuthenticationMethod.SUBSCRIPTION,
            isolation_mode=ClaudeIsolationMode.STANDARD,
            code="claude_available",
        )

    monkeypatch.setattr(
        operator_module,
        "read_claude_invocation_readiness",
        record_claude_check,
    )
    monkeypatch.setattr(
        operator_module,
        "ClaudeOperatorTurnRunner",
        _recording_provider_factory(adapters),
    )
    runner = operator_module.ConfiguredOperatorTurnRunner(
        settings=Settings(
            claude=ClaudeSettings(enabled=True),
            operator=OperatorSettings(
                provider=OperatorProvider.CLAUDE,
                effort="unsupported",
            ),
        ),
        system_prompt="prompt",
        tools=(),
    )

    async with runner.lifespan():
        assert runner.status.availability == "unavailable"
        assert "effort" in runner.status.explanation.casefold()
        assert "low" in (runner.status.setup_action or "")

    assert readiness_checks == []
    assert adapters == []


async def test_invalid_effective_codex_effort_fails_before_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readiness_checks: list[str] = []
    adapters: list[RecordingProviderRunner] = []

    async def record_codex_check() -> object:
        readiness_checks.append("codex")
        return SimpleNamespace(is_authenticated=True, code="codex_available")

    monkeypatch.setattr(operator_module, "_read_codex_authentication", record_codex_check)
    monkeypatch.setattr(
        operator_module,
        "CodexOperatorTurnRunner",
        _recording_provider_factory(adapters),
    )
    runner = operator_module.ConfiguredOperatorTurnRunner(
        settings=Settings(
            codex=CodexSettings(enabled=True),
            operator=OperatorSettings(
                provider=OperatorProvider.CODEX,
                effort="unsupported",
            ),
        ),
        system_prompt="prompt",
        tools=(),
    )

    async with runner.lifespan():
        assert runner.status.availability == "unavailable"
        assert "effort" in runner.status.explanation.casefold()
        assert "minimal" in (runner.status.setup_action or "")

    assert readiness_checks == []
    assert adapters == []


async def test_overlength_effective_provider_option_fails_before_readiness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    readiness_checks: list[str] = []

    async def record_codex_check() -> object:
        readiness_checks.append("codex")
        return SimpleNamespace(is_authenticated=True, code="codex_available")

    monkeypatch.setattr(operator_module, "_read_codex_authentication", record_codex_check)
    config_path = tmp_path / "config.toml"
    runner = operator_module.ConfiguredOperatorTurnRunner(
        settings=Settings(
            config_path=config_path,
            codex=CodexSettings(enabled=True, model="x" * 256),
            operator=OperatorSettings(provider=OperatorProvider.CODEX),
        ),
        system_prompt="prompt",
        tools=(),
    )

    async with runner.lifespan():
        assert runner.status.availability == "unavailable"
        assert "model" in runner.status.explanation.casefold()
        assert "255" in (runner.status.setup_action or "")
        assert str(config_path) in (runner.status.setup_action or "")

    assert readiness_checks == []


def test_unconfigured_setup_action_names_real_config_and_provider_commands(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    runner = operator_module.ConfiguredOperatorTurnRunner(
        settings=Settings(config_path=config_path),
        system_prompt="prompt",
        tools=(),
    )

    assert runner.status.availability == "unconfigured"
    assert runner.status.setup_action == ("Run `oms operator setup`, then restart Oh My Subagents.")
