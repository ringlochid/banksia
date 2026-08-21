from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import oh_my_subagents.integrations.operator as operator_module
from oh_my_subagents.config import (
    ClaudeSettings,
    CodexSettings,
    OperatorProvider,
    OperatorSettings,
    Settings,
)
from oh_my_subagents.integrations.claude.native_identity import (
    ClaudeInvocationReadiness,
    ClaudeIsolationMode,
)
from oh_my_subagents.operator import OperatorTurnOutcome, OperatorTurnRequest
from oh_my_subagents.operator.provider import OperatorMessageTurnInput, OperatorRunnerStatus
from oh_my_subagents.runtime.providers import ProviderAuthenticationMethod


def _request(provider: str) -> OperatorTurnRequest:
    return OperatorTurnRequest(
        provider=provider,
        model=None,
        effort=None,
        provider_thread_id=None,
        input=OperatorMessageTurnInput(text="Draft a Workflow."),
    )


async def test_lifespan_cancels_and_drains_an_active_provider_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turn_started = asyncio.Event()
    cancellation_started = asyncio.Event()
    cleanup_release = asyncio.Event()
    leave_lifespan = asyncio.Event()
    turn: asyncio.Task[OperatorTurnOutcome] | None = None

    class BlockingProviderRunner:
        status = OperatorRunnerStatus(
            availability="available",
            configured_provider="codex",
            explanation="ready",
        )

        def __init__(self, **arguments: object) -> None:
            del arguments

        async def execute_turn(self, request: OperatorTurnRequest) -> OperatorTurnOutcome:
            del request
            turn_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancellation_started.set()
                await cleanup_release.wait()
                raise
            raise AssertionError("blocking provider turn unexpectedly returned")

    async def accept_codex_check() -> object:
        return SimpleNamespace(is_authenticated=True, code="codex_available")

    monkeypatch.setattr(operator_module, "_read_codex_authentication", accept_codex_check)
    monkeypatch.setattr(operator_module, "CodexOperatorTurnRunner", BlockingProviderRunner)
    runner = operator_module.ConfiguredOperatorTurnRunner(
        settings=Settings(
            codex=CodexSettings(enabled=True),
            operator=OperatorSettings(provider=OperatorProvider.CODEX),
        ),
        system_prompt="prompt",
        tools=(),
    )

    async def serve() -> None:
        nonlocal turn
        async with runner.lifespan():
            turn = asyncio.create_task(runner.execute_turn(_request("codex")))
            await turn_started.wait()
            await leave_lifespan.wait()

    owner = asyncio.create_task(serve())
    try:
        await turn_started.wait()
        leave_lifespan.set()
        for _ in range(3):
            await asyncio.sleep(0)

        assert cancellation_started.is_set()
        assert not owner.done()

        cleanup_release.set()
        await owner
        assert turn is not None
        with pytest.raises(asyncio.CancelledError):
            await turn
    finally:
        cleanup_release.set()
        if turn is not None and not turn.done():
            turn.cancel()
        if not owner.done():
            owner.cancel()
        await asyncio.gather(
            *(task for task in (turn, owner) if task is not None),
            return_exceptions=True,
        )


async def test_cancelled_claude_readiness_does_not_outlive_lifespan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    readiness_started = threading.Event()
    readiness_release = threading.Event()
    readiness_finished = threading.Event()

    def blocking_claude_check() -> ClaudeInvocationReadiness:
        readiness_started.set()
        readiness_release.wait(timeout=5)
        readiness_finished.set()
        return ClaudeInvocationReadiness(
            method=ProviderAuthenticationMethod.SUBSCRIPTION,
            isolation_mode=ClaudeIsolationMode.STANDARD,
            code="claude_available",
        )

    monkeypatch.setattr(
        operator_module,
        "read_claude_invocation_readiness",
        blocking_claude_check,
    )
    runner = operator_module.ConfiguredOperatorTurnRunner(
        settings=Settings(
            data_dir=tmp_path / "data",
            claude=ClaudeSettings(enabled=True),
            operator=OperatorSettings(provider=OperatorProvider.CLAUDE),
        ),
        system_prompt="prompt",
        tools=(),
    )

    async def serve() -> None:
        async with runner.lifespan():
            raise AssertionError("cancelled readiness must not enter the active lifespan")

    owner = asyncio.create_task(serve())
    try:
        assert await asyncio.to_thread(readiness_started.wait, 1)
        owner.cancel()
        await asyncio.sleep(0)
        assert not owner.done()
    finally:
        readiness_release.set()

    with pytest.raises(asyncio.CancelledError):
        await owner
    assert readiness_finished.is_set()
    assert runner.status.availability == "unavailable"


async def test_cancelled_codex_readiness_waits_for_native_client_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_started = asyncio.Event()
    close_release = asyncio.Event()
    close_finished = asyncio.Event()

    class NativeClient:
        def __init__(self, config: object) -> None:
            del config

        async def account(self) -> object:
            return SimpleNamespace(account=None, requires_openai_auth=False)

        async def close(self) -> None:
            close_started.set()
            await close_release.wait()
            close_finished.set()

    monkeypatch.setattr(operator_module, "AsyncCodex", NativeClient)
    runner = operator_module.ConfiguredOperatorTurnRunner(
        settings=Settings(
            codex=CodexSettings(enabled=True),
            operator=OperatorSettings(provider=OperatorProvider.CODEX),
        ),
        system_prompt="prompt",
        tools=(),
    )

    async def serve() -> None:
        async with runner.lifespan():
            raise AssertionError("cancelled readiness must not enter the active lifespan")

    owner = asyncio.create_task(serve())
    try:
        await close_started.wait()
        owner.cancel()
        await asyncio.sleep(0)
        assert not owner.done()
    finally:
        close_release.set()

    with pytest.raises(asyncio.CancelledError):
        await owner
    assert close_finished.is_set()
    assert runner.status.availability == "unavailable"
