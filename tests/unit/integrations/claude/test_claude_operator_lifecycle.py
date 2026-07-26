from __future__ import annotations

import asyncio
from typing import cast

import pytest
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

from banksia.integrations.claude.operator import ClaudeOperatorTurnRunner
from tests.unit.integrations.claude.operator_sdk_test_support import (
    FakeClaudeOperatorClient,
    FakeClaudeOperatorClientFactory,
    build_claude_operator_request,
    build_claude_operator_runner,
    build_claude_operator_status,
    build_claude_operator_tools,
    read_clear_claude_endpoint_policy,
    read_personal_claude_authentication,
)


@pytest.mark.asyncio
async def test_claude_operator_cancellation_interrupts_and_disconnects_provider() -> None:
    factory = FakeClaudeOperatorClientFactory((), should_block_response=True)
    turn = asyncio.create_task(
        build_claude_operator_runner(factory).execute_turn(build_claude_operator_request())
    )
    await factory.client_created.wait()
    client = factory.clients[0]
    await client.response_started.wait()

    turn.cancel()
    with pytest.raises(asyncio.CancelledError):
        await turn

    assert client.was_interrupted is True
    assert client.was_disconnected is True


@pytest.mark.asyncio
async def test_repeated_cancellation_cannot_interrupt_claude_disconnect() -> None:
    disconnect_started = asyncio.Event()
    disconnect_release = asyncio.Event()
    client_created = asyncio.Event()
    clients: list[FakeClaudeOperatorClient] = []

    class BlockingDisconnectClient(FakeClaudeOperatorClient):
        async def disconnect(self) -> None:
            disconnect_started.set()
            await disconnect_release.wait()
            self.was_disconnected = True

    def build_client(options: ClaudeAgentOptions) -> ClaudeSDKClient:
        client = BlockingDisconnectClient(
            options,
            messages=(),
            should_block_response=True,
        )
        clients.append(client)
        client_created.set()
        return cast(ClaudeSDKClient, client)

    runner = ClaudeOperatorTurnRunner(
        system_prompt="Exact prompt.",
        tools=build_claude_operator_tools(),
        status=build_claude_operator_status(),
        client_factory=build_client,
        authentication_reader=read_personal_claude_authentication,
        endpoint_policy_reader=read_clear_claude_endpoint_policy,
    )
    turn = asyncio.create_task(runner.execute_turn(build_claude_operator_request()))
    try:
        await client_created.wait()
        client = clients[0]
        await client.response_started.wait()
        turn.cancel()
        await disconnect_started.wait()
        turn.cancel()
        await asyncio.sleep(0)

        assert not turn.done()

        disconnect_release.set()
        with pytest.raises(asyncio.CancelledError):
            await turn
        assert client.was_interrupted is True
        assert client.was_disconnected is True
    finally:
        disconnect_release.set()
        if not turn.done():
            turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)


@pytest.mark.asyncio
async def test_repeated_cancellation_waits_for_claude_connect_cleanup() -> None:
    connect_started = asyncio.Event()
    connect_cleanup_started = asyncio.Event()
    connect_cleanup_release = asyncio.Event()
    clients: list[FakeClaudeOperatorClient] = []

    class BlockingConnectClient(FakeClaudeOperatorClient):
        async def connect(self) -> None:
            connect_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                connect_cleanup_started.set()
                await connect_cleanup_release.wait()
                raise

    def build_client(options: ClaudeAgentOptions) -> ClaudeSDKClient:
        client = BlockingConnectClient(options, messages=())
        clients.append(client)
        return cast(ClaudeSDKClient, client)

    runner = ClaudeOperatorTurnRunner(
        system_prompt="Exact prompt.",
        tools=build_claude_operator_tools(),
        status=build_claude_operator_status(),
        client_factory=build_client,
        authentication_reader=read_personal_claude_authentication,
        endpoint_policy_reader=read_clear_claude_endpoint_policy,
    )
    turn = asyncio.create_task(runner.execute_turn(build_claude_operator_request()))
    try:
        await connect_started.wait()
        turn.cancel()
        await connect_cleanup_started.wait()
        turn.cancel()
        await asyncio.sleep(0)

        assert not turn.done()

        connect_cleanup_release.set()
        with pytest.raises(asyncio.CancelledError):
            await turn
        assert clients[0].was_disconnected is True
    finally:
        connect_cleanup_release.set()
        if not turn.done():
            turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)
