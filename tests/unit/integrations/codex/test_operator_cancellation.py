from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest
from openai_codex.client import CodexClient
from openai_codex.generated.v2_all import ConfigReadResponse
from openai_codex.models import JsonObject
from pydantic import BaseModel, ConfigDict

from banksia.integrations.codex.operator import CodexOperatorTurnRunner
from banksia.operator.provider import (
    OperatorMessageTurnInput,
    OperatorRunnerStatus,
    OperatorTurnRequest,
)
from banksia.operator.tools import OperatorTool, OperatorToolName


class _ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: str


class _ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    echo: str


class _CancellationCodexClient:
    def __init__(
        self,
        handler: Callable[[str, JsonObject | None], JsonObject],
        *,
        server_requests: tuple[tuple[str, JsonObject | None], ...] = (),
        should_block_notification: bool = False,
        should_block_start: bool = False,
        should_block_close: bool = False,
    ) -> None:
        self.handler = handler
        self.server_requests = server_requests
        self.should_block_notification = should_block_notification
        self.should_block_start = should_block_start
        self.should_block_close = should_block_close
        self.interrupt_calls: list[tuple[str, str]] = []
        self.unregistered_turns: list[str] = []
        self.was_closed = False
        self.close_during_start = False
        self.start_waiting = threading.Event()
        self.start_release = threading.Event()
        self.start_finished = threading.Event()
        self.close_waiting = threading.Event()
        self.close_release = threading.Event()
        self.notification_waiting = threading.Event()
        self.notification_release = threading.Event()
        self.notification_wait_finished = threading.Event()
        self.turn_start_finished = threading.Event()

    def start(self) -> None:
        self.start_waiting.set()
        try:
            if self.should_block_start:
                self.start_release.wait(timeout=5)
        finally:
            self.start_finished.set()

    def initialize(self) -> object:
        return object()

    def request(
        self,
        method: str,
        params: JsonObject | None,
        *,
        response_model: type[BaseModel],
    ) -> Any:
        del params, response_model
        if method == "config/read":
            return ConfigReadResponse.model_validate({"config": {"mcp_servers": {}}, "origins": {}})
        if method == "mcpServerStatus/list":
            return SimpleNamespace(data=[], next_cursor=None)
        raise AssertionError(f"unexpected request method: {method}")

    def thread_start(self, params: JsonObject) -> object:
        del params
        return SimpleNamespace(
            thread=SimpleNamespace(id="codex-thread-1"),
            instruction_sources=[],
        )

    def turn_start(
        self,
        thread_id: str,
        input_items: str,
        params: JsonObject,
    ) -> object:
        del thread_id, input_items, params
        try:
            for method, request_params in self.server_requests:
                self.handler(method, request_params)
            return SimpleNamespace(turn=SimpleNamespace(id="codex-turn-1"))
        finally:
            self.turn_start_finished.set()

    def next_turn_notification(self, turn_id: str) -> object:
        del turn_id
        if self.should_block_notification:
            self.notification_waiting.set()
            try:
                self.notification_release.wait(timeout=5)
                raise RuntimeError("provider turn interrupted")
            finally:
                self.notification_wait_finished.set()
        raise AssertionError("no notification available")

    def unregister_turn_notifications(self, turn_id: str) -> None:
        self.unregistered_turns.append(turn_id)

    def turn_interrupt(self, thread_id: str, turn_id: str) -> object:
        self.interrupt_calls.append((thread_id, turn_id))
        self.notification_release.set()
        return object()

    def close(self) -> None:
        self.close_during_start = self.close_during_start or not self.start_finished.is_set()
        self.was_closed = True
        self.notification_release.set()
        self.close_waiting.set()
        if self.should_block_close:
            self.close_release.wait(timeout=5)


class _CancellationClientFactory:
    def __init__(
        self,
        *,
        server_requests: tuple[tuple[str, JsonObject | None], ...] = (),
        should_block_notification: bool = False,
        should_block_start: bool = False,
        should_block_close: bool = False,
    ) -> None:
        self.server_requests = server_requests
        self.should_block_notification = should_block_notification
        self.should_block_start = should_block_start
        self.should_block_close = should_block_close
        self.clients: list[_CancellationCodexClient] = []

    def __call__(
        self,
        handler: Callable[[str, JsonObject | None], JsonObject],
    ) -> CodexClient:
        client = _CancellationCodexClient(
            handler,
            server_requests=self.server_requests,
            should_block_notification=self.should_block_notification,
            should_block_start=self.should_block_start,
            should_block_close=self.should_block_close,
        )
        self.clients.append(client)
        return cast(CodexClient, client)


def _tools() -> tuple[OperatorTool, ...]:
    async def handle(request: BaseModel) -> BaseModel:
        typed_request = _ToolInput.model_validate(request)
        return _ToolResult(echo=typed_request.value)

    return tuple(
        OperatorTool(
            name=tool_name,
            description=f"Use the Banksia {tool_name.value} operation.",
            input_model=_ToolInput,
            handler=handle,
        )
        for tool_name in OperatorToolName
    )


def _request() -> OperatorTurnRequest:
    return OperatorTurnRequest(
        provider="codex",
        model="gpt-5.3-codex",
        effort="high",
        provider_thread_id=None,
        input=OperatorMessageTurnInput(text="Create a research workflow."),
    )


def _runner(
    factory: _CancellationClientFactory,
    *,
    tools: tuple[OperatorTool, ...] | None = None,
) -> CodexOperatorTurnRunner:
    return CodexOperatorTurnRunner(
        system_prompt="Exact prompt.",
        tools=tools or _tools(),
        status=OperatorRunnerStatus(
            availability="available",
            configured_provider="codex",
            explanation="Operator is available through Codex.",
            model="gpt-5.3-codex",
            effort="high",
        ),
        client_factory=factory,
    )


@pytest.mark.asyncio
async def test_codex_operator_cancellation_interrupts_turn_and_closes_client() -> None:
    factory = _CancellationClientFactory(
        should_block_notification=True,
        should_block_close=True,
    )
    turn = asyncio.create_task(_runner(factory).execute_turn(_request()))
    await asyncio.sleep(0)
    client = factory.clients[0]
    assert await asyncio.to_thread(client.notification_waiting.wait, 2)

    turn.cancel()
    assert await asyncio.to_thread(client.close_waiting.wait, 2)
    turn.cancel()
    await asyncio.sleep(0)
    assert turn.done() is False
    client.close_release.set()
    with pytest.raises(asyncio.CancelledError):
        await turn

    assert client.interrupt_calls == [("codex-thread-1", "codex-turn-1")]
    assert client.was_closed is True
    assert client.notification_wait_finished.is_set()
    assert client.unregistered_turns == ["codex-turn-1"]


@pytest.mark.asyncio
async def test_codex_operator_cancellation_waits_for_start_before_close() -> None:
    factory = _CancellationClientFactory(should_block_start=True)
    turn = asyncio.create_task(_runner(factory).execute_turn(_request()))
    await asyncio.sleep(0)
    client = factory.clients[0]
    assert await asyncio.to_thread(client.start_waiting.wait, 2)

    turn.cancel()
    client.start_release.set()
    with pytest.raises(asyncio.CancelledError):
        await turn

    assert client.start_finished.is_set()
    assert client.close_during_start is False
    assert client.was_closed is True


@pytest.mark.asyncio
async def test_codex_operator_cancellation_deactivates_blocked_dynamic_tool() -> None:
    tool_started = asyncio.Event()
    cleanup_started = asyncio.Event()
    cleanup_release = asyncio.Event()
    cleanup_finished = asyncio.Event()
    release_tool = asyncio.Event()

    async def block_tool(request: BaseModel) -> BaseModel:
        _ToolInput.model_validate(request)
        tool_started.set()
        try:
            await release_tool.wait()
        finally:
            cleanup_started.set()
            await cleanup_release.wait()
            cleanup_finished.set()
        return _ToolResult(echo="released")

    tools = list(_tools())
    tools[0] = OperatorTool(
        name=OperatorToolName.WORKFLOW_SEARCH,
        description="Use the Banksia workflow_search operation.",
        input_model=_ToolInput,
        handler=block_tool,
    )
    factory = _CancellationClientFactory(
        server_requests=(
            (
                "item/tool/call",
                {
                    "tool": OperatorToolName.WORKFLOW_SEARCH.value,
                    "namespace": None,
                    "arguments": {"value": "blocked"},
                },
            ),
        )
    )
    turn = asyncio.create_task(_runner(factory, tools=tuple(tools)).execute_turn(_request()))
    await asyncio.wait_for(tool_started.wait(), timeout=2)

    turn.cancel()
    try:
        await asyncio.wait_for(cleanup_started.wait(), timeout=2)
        await asyncio.sleep(0)
        assert turn.done() is False
        assert factory.clients[0].was_closed is False
        turn.cancel()
        await asyncio.sleep(0)
        assert turn.done() is False
    finally:
        cleanup_release.set()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(turn, timeout=2)

    client = factory.clients[0]
    assert cleanup_finished.is_set()
    assert client.turn_start_finished.is_set()
    assert client.was_closed is True
