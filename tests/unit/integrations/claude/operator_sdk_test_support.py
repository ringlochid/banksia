from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, cast

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from pydantic import BaseModel, ConfigDict

from banksia.integrations.claude.native_identity import (
    ClaudeAuthenticationState,
    ClaudeEndpointPolicyState,
    ClaudeSubscriptionClass,
)
from banksia.integrations.claude.operator import ClaudeOperatorTurnRunner
from banksia.operator.contracts import OperatorAvailability
from banksia.operator.provider import (
    OperatorMessageTurnInput,
    OperatorQuestionAnswersTurnInput,
    OperatorRunnerStatus,
    OperatorTurnRequest,
)
from banksia.operator.tools import OperatorTool, OperatorToolName
from banksia.operator.tools.contracts import MAX_OPERATOR_TOOL_RESULT_UTF16_CODE_UNITS
from banksia.runtime.providers import ProviderAuthenticationMethod


class ClaudeOperatorToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: str


class ClaudeOperatorToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    echo: str


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

    async def get_server_info(self) -> dict[str, object]:
        return {"commands": []}

    async def get_context_usage(self) -> dict[str, object]:
        return {
            "memoryFiles": [],
            "agents": [],
            "mcpTools": [],
        }

    async def get_mcp_status(self) -> dict[str, object]:
        return {"mcpServers": []}

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


def build_claude_operator_status(
    *,
    availability: OperatorAvailability = "available",
) -> OperatorRunnerStatus:
    return OperatorRunnerStatus(
        availability=availability,
        configured_provider="claude",
        explanation="Operator is available through Claude.",
        model="claude-sonnet-4-5",
        effort="high",
    )


def read_personal_claude_authentication() -> ClaudeAuthenticationState:
    return ClaudeAuthenticationState(
        is_authenticated=True,
        method=ProviderAuthenticationMethod.SUBSCRIPTION,
        code="claude_available",
        subscription_class=ClaudeSubscriptionClass.PERSONAL,
    )


def read_clear_claude_endpoint_policy() -> ClaudeEndpointPolicyState:
    return ClaudeEndpointPolicyState(
        is_installed=False,
        code="claude_endpoint_policy_clear",
    )


def build_claude_operator_tools(
    calls: list[tuple[OperatorToolName, str]] | None = None,
) -> tuple[OperatorTool, ...]:
    def build_handler(
        tool_name: OperatorToolName,
    ) -> Callable[[BaseModel], Any]:
        async def handle(request: BaseModel) -> BaseModel:
            typed_request = ClaudeOperatorToolInput.model_validate(request)
            if calls is not None:
                calls.append((tool_name, typed_request.value))
            if typed_request.value == "raise-secret":
                raise RuntimeError("private provider detail")
            if typed_request.value == "oversize-after-commit":
                return ClaudeOperatorToolResult(
                    echo="x" * (MAX_OPERATOR_TOOL_RESULT_UTF16_CODE_UNITS + 1)
                )
            return ClaudeOperatorToolResult(echo=typed_request.value)

        return handle

    return tuple(
        OperatorTool(
            name=tool_name,
            description=f"Use the Banksia {tool_name.value} operation.",
            input_model=ClaudeOperatorToolInput,
            handler=build_handler(tool_name),
        )
        for tool_name in OperatorToolName
    )


def build_claude_operator_request(
    *,
    provider_thread_id: str | None = None,
    turn_input: OperatorMessageTurnInput | OperatorQuestionAnswersTurnInput | None = None,
) -> OperatorTurnRequest:
    return OperatorTurnRequest(
        provider="claude",
        model="claude-sonnet-4-5",
        effort="high",
        provider_thread_id=provider_thread_id,
        input=turn_input or OperatorMessageTurnInput(text="Build an accountable research team."),
    )


def build_claude_operator_runner(
    factory: FakeClaudeOperatorClientFactory,
    *,
    working_directory: Path | None = None,
) -> ClaudeOperatorTurnRunner:
    return ClaudeOperatorTurnRunner(
        system_prompt="Exact prompt.\nPreserve this whitespace.\n",
        tools=build_claude_operator_tools(),
        status=build_claude_operator_status(),
        working_directory=working_directory,
        client_factory=factory,
        authentication_reader=read_personal_claude_authentication,
        endpoint_policy_reader=read_clear_claude_endpoint_policy,
    )


__all__ = [
    "ClaudeOperatorToolInput",
    "ClaudeOperatorToolResult",
    "FakeClaudeOperatorClient",
    "FakeClaudeOperatorClientFactory",
    "build_claude_operator_request",
    "build_claude_operator_runner",
    "build_claude_operator_status",
    "build_claude_operator_tools",
    "read_clear_claude_endpoint_policy",
    "read_personal_claude_authentication",
]
