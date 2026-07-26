from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import cast

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient


class FakeClaudeOperatorClient:
    """Record one Claude Operator SDK lifecycle without launching a provider."""

    def __init__(
        self,
        options: ClaudeAgentOptions,
        *,
        messages: tuple[object, ...],
        should_block_response: bool = False,
        response_error: Exception | None = None,
    ) -> None:
        self.options = options
        self.messages = messages
        self.should_block_response = should_block_response
        self.response_error = response_error
        self.query_input: str | None = None
        self.was_connected = False
        self.was_interrupted = False
        self.was_disconnected = False
        self.response_started = asyncio.Event()
        self.response_release = asyncio.Event()

    async def connect(self) -> None:
        self.was_connected = True

    async def query(self, prompt: str) -> None:
        self.query_input = prompt

    async def receive_response(self) -> AsyncIterator[object]:
        self.response_started.set()
        if self.should_block_response:
            await self.response_release.wait()
        if self.response_error is not None:
            raise self.response_error
        for message in self.messages:
            yield message

    async def interrupt(self) -> None:
        self.was_interrupted = True
        self.response_release.set()

    async def disconnect(self) -> None:
        self.was_disconnected = True


class FakeClaudeOperatorClientFactory:
    """Build and retain fake clients for exact option and cleanup assertions."""

    def __init__(
        self,
        messages: tuple[object, ...],
        *,
        should_block_response: bool = False,
        response_error: Exception | None = None,
    ) -> None:
        self.messages = messages
        self.should_block_response = should_block_response
        self.response_error = response_error
        self.clients: list[FakeClaudeOperatorClient] = []
        self.client_created = asyncio.Event()

    def __call__(self, options: ClaudeAgentOptions) -> ClaudeSDKClient:
        client = FakeClaudeOperatorClient(
            options,
            messages=self.messages,
            should_block_response=self.should_block_response,
            response_error=self.response_error,
        )
        self.clients.append(client)
        self.client_created.set()
        return cast(ClaudeSDKClient, client)
