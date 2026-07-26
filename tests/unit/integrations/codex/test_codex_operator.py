from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NotRequired, TypedDict, Unpack, cast

import pytest
from openai_codex import InvalidRequestError
from openai_codex.client import CodexClient
from openai_codex.generated.v2_all import (
    AgentMessageThreadItem,
    ConfigReadResponse,
    ItemCompletedNotification,
    MessagePhase,
    ThreadItem,
    Turn,
    TurnCompletedNotification,
    TurnStatus,
)
from openai_codex.models import JsonObject, Notification
from pydantic import BaseModel, ConfigDict

from banksia.integrations.codex import operator as codex_operator
from banksia.integrations.codex.operator import (
    PINNED_CODEX_VERSION,
    CodexOperatorTurnRunner,
    resolve_codex_operator_effort,
)
from banksia.operator.contracts import (
    MAX_OPERATOR_TEXT_BYTES,
    OperatorAvailability,
)
from banksia.operator.provider import (
    OperatorAcceptedCustomAnswer,
    OperatorAcceptedOptionAnswer,
    OperatorAnsweredQuestion,
    OperatorMessageTurnInput,
    OperatorProviderThreadUnavailableError,
    OperatorProviderUnavailableError,
    OperatorQuestionAnswersTurnInput,
    OperatorRunnerStatus,
    OperatorTurnRequest,
)
from banksia.operator.tools import OperatorTool, OperatorToolName
from banksia.operator.tools.contracts import MAX_OPERATOR_TOOL_RESULT_UTF16_CODE_UNITS


class _ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: str


class _ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    echo: str


class _FakeClientOptions(TypedDict):
    output: NotRequired[object]
    thread_id: NotRequired[str]
    resumed_thread_id: NotRequired[str | None]
    configured_mcp: NotRequired[tuple[str, ...]]
    active_mcp: NotRequired[tuple[object, ...]]
    server_requests: NotRequired[tuple[tuple[str, JsonObject | None], ...]]
    resume_error: NotRequired[Exception | None]
    should_block: NotRequired[bool]
    should_block_start: NotRequired[bool]
    should_block_close: NotRequired[bool]


class _FakeCodexClient:
    def __init__(
        self,
        handler: Callable[[str, JsonObject | None], JsonObject],
        *,
        output: object = None,
        thread_id: str = "codex-thread-1",
        resumed_thread_id: str | None = None,
        configured_mcp: tuple[str, ...] = ("external_docs",),
        active_mcp: tuple[object, ...] = (),
        server_requests: tuple[tuple[str, JsonObject | None], ...] = (),
        resume_error: Exception | None = None,
        should_block: bool = False,
        should_block_start: bool = False,
        should_block_close: bool = False,
    ) -> None:
        self.handler = handler
        self.output = output if output is not None else {"kind": "message", "text": "Done."}
        self.thread_id = thread_id
        self.resumed_thread_id = resumed_thread_id or thread_id
        self.configured_mcp = configured_mcp
        self.active_mcp = active_mcp
        self.server_requests = server_requests
        self.resume_error = resume_error
        self.should_block = should_block
        self.should_block_start = should_block_start
        self.should_block_close = should_block_close
        self.server_results: list[JsonObject] = []
        self.thread_start_params: list[JsonObject] = []
        self.thread_resume_params: list[tuple[str, JsonObject]] = []
        self.turn_start_calls: list[tuple[str, str, JsonObject]] = []
        self.interrupt_calls: list[tuple[str, str]] = []
        self.unregistered_turns: list[str] = []
        self.was_started = False
        self.was_initialized = False
        self.was_closed = False
        self.close_during_start = False
        self.cwd_existed_at_start = False
        self.start_waiting = threading.Event()
        self.start_release = threading.Event()
        self.start_finished = threading.Event()
        self.close_waiting = threading.Event()
        self.close_release = threading.Event()
        self.waiting = threading.Event()
        self.release = threading.Event()
        self.notification_wait_finished = threading.Event()
        self.turn_start_finished = threading.Event()
        self.notifications: list[Notification] = []

    def start(self) -> None:
        self.start_waiting.set()
        try:
            if self.should_block_start:
                self.start_release.wait(timeout=5)
            self.was_started = True
        finally:
            self.start_finished.set()

    def initialize(self) -> object:
        self.was_initialized = True
        return object()

    def request(
        self,
        method: str,
        params: JsonObject | None,
        *,
        response_model: type[BaseModel],
    ) -> Any:
        del response_model
        if method == "config/read":
            return ConfigReadResponse.model_validate(
                {
                    "config": {
                        "mcp_servers": {name: {"enabled": True} for name in self.configured_mcp}
                    },
                    "origins": {},
                }
            )
        if method == "mcpServerStatus/list":
            return SimpleNamespace(data=list(self.active_mcp), next_cursor=None)
        raise AssertionError(f"unexpected request method: {method}")

    def thread_start(self, params: JsonObject) -> object:
        self.thread_start_params.append(params)
        cwd = params.get("cwd")
        self.cwd_existed_at_start = isinstance(cwd, str) and Path(cwd).is_dir()
        return SimpleNamespace(thread=SimpleNamespace(id=self.thread_id), instruction_sources=[])

    def thread_resume(self, thread_id: str, params: JsonObject) -> object:
        self.thread_resume_params.append((thread_id, params))
        if self.resume_error is not None:
            raise self.resume_error
        return SimpleNamespace(
            thread=SimpleNamespace(id=self.resumed_thread_id), instruction_sources=[]
        )

    def turn_start(
        self,
        thread_id: str,
        input_items: str,
        params: JsonObject,
    ) -> object:
        try:
            self.turn_start_calls.append((thread_id, input_items, params))
            for method, request_params in self.server_requests:
                self.server_results.append(self.handler(method, request_params))
            turn_id = "codex-turn-1"
            self.notifications = _terminal_notifications(
                thread_id=thread_id,
                turn_id=turn_id,
                output=self.output,
            )
            return SimpleNamespace(turn=SimpleNamespace(id=turn_id))
        finally:
            self.turn_start_finished.set()

    def next_turn_notification(self, turn_id: str) -> Notification:
        if self.should_block:
            self.waiting.set()
            try:
                self.release.wait(timeout=5)
                raise RuntimeError("provider turn interrupted")
            finally:
                self.notification_wait_finished.set()
        if not self.notifications:
            raise AssertionError(f"no notification available for {turn_id}")
        return self.notifications.pop(0)

    def unregister_turn_notifications(self, turn_id: str) -> None:
        self.unregistered_turns.append(turn_id)

    def turn_interrupt(self, thread_id: str, turn_id: str) -> object:
        self.interrupt_calls.append((thread_id, turn_id))
        self.release.set()
        return object()

    def close(self) -> None:
        self.close_during_start = self.close_during_start or not self.start_finished.is_set()
        self.was_closed = True
        self.release.set()
        self.close_waiting.set()
        if self.should_block_close:
            self.close_release.wait(timeout=5)


class _ClientFactory:
    def __init__(self, **client_options: Unpack[_FakeClientOptions]) -> None:
        self.client_options = client_options
        self.clients: list[_FakeCodexClient] = []

    def __call__(
        self,
        handler: Callable[[str, JsonObject | None], JsonObject],
    ) -> CodexClient:
        client = _FakeCodexClient(handler, **self.client_options)
        self.clients.append(client)
        return cast(CodexClient, client)


def _terminal_notifications(
    *,
    thread_id: str,
    turn_id: str,
    output: object,
) -> list[Notification]:
    rendered = (
        output if isinstance(output, str) else json.dumps({"result": output}, separators=(",", ":"))
    )
    item = ThreadItem(
        root=AgentMessageThreadItem(
            id="agent-message-1",
            type="agentMessage",
            phase=MessagePhase.final_answer,
            text=rendered,
        )
    )
    return [
        Notification(
            method="item/completed",
            payload=ItemCompletedNotification(
                completed_at_ms=1,
                item=item,
                thread_id=thread_id,
                turn_id=turn_id,
            ),
        ),
        Notification(
            method="turn/completed",
            payload=TurnCompletedNotification(
                thread_id=thread_id,
                turn=Turn(id=turn_id, items=[], status=TurnStatus.completed),
            ),
        ),
    ]


def _status(*, availability: OperatorAvailability = "available") -> OperatorRunnerStatus:
    return OperatorRunnerStatus(
        availability=availability,
        configured_provider="codex",
        explanation="Operator is available through Codex.",
        model="gpt-5.3-codex",
        effort="high",
    )


def _tools(
    calls: list[tuple[OperatorToolName, str]] | None = None,
) -> tuple[OperatorTool, ...]:
    def build_handler(tool_name: OperatorToolName) -> Callable[[BaseModel], Any]:
        async def handle(request: BaseModel) -> BaseModel:
            typed_request = _ToolInput.model_validate(request)
            if calls is not None:
                calls.append((tool_name, typed_request.value))
            if typed_request.value == "raise-secret":
                raise RuntimeError("private tool failure")
            if typed_request.value == "oversize":
                return _ToolResult(echo="x" * (MAX_OPERATOR_TOOL_RESULT_UTF16_CODE_UNITS + 1))
            return _ToolResult(echo=typed_request.value)

        return handle

    return tuple(
        OperatorTool(
            name=tool_name,
            description=f"Use the Banksia {tool_name.value} operation.",
            input_model=_ToolInput,
            handler=build_handler(tool_name),
        )
        for tool_name in OperatorToolName
    )


def _request(
    *,
    provider_thread_id: str | None = None,
    turn_input: OperatorMessageTurnInput | OperatorQuestionAnswersTurnInput | None = None,
    effort: str | None = "high",
) -> OperatorTurnRequest:
    return OperatorTurnRequest(
        provider="codex",
        model="gpt-5.3-codex",
        effort=effort,
        provider_thread_id=provider_thread_id,
        input=turn_input or OperatorMessageTurnInput(text="Create a research workflow."),
    )


def _runner(
    factory: _ClientFactory,
    *,
    tools: tuple[OperatorTool, ...] | None = None,
) -> CodexOperatorTurnRunner:
    return CodexOperatorTurnRunner(
        system_prompt="Exact prompt.\nPreserve this whitespace.\n",
        tools=tools or _tools(),
        status=_status(),
        client_factory=factory,
    )


@pytest.mark.asyncio
async def test_codex_operator_uses_pinned_native_envelope_and_isolated_exact_tools() -> None:
    factory = _ClientFactory()

    outcome = await _runner(factory).execute_turn(_request())

    client = factory.clients[0]
    start = client.thread_start_params[0]
    turn_thread_id, turn_input, turn = client.turn_start_calls[0]
    dynamic_tools = cast(list[dict[str, object]], start["dynamicTools"])
    isolation = cast(dict[str, Any], start["config"])
    assert outcome.provider_thread_id == "codex-thread-1"
    assert outcome.result.kind == "message"
    assert client.was_started and client.was_initialized
    assert client.was_closed is True
    assert client.cwd_existed_at_start is True
    assert start["baseInstructions"] == "Exact prompt.\nPreserve this whitespace.\n"
    assert start["developerInstructions"] == ""
    assert start["approvalPolicy"] == "never"
    assert start["allowProviderModelFallback"] is False
    assert start["sandbox"] == "read-only"
    assert start["environments"] == []
    assert start["runtimeWorkspaceRoots"] == []
    assert start["selectedCapabilityRoots"] == []
    assert start["ephemeral"] is False
    assert [tool["name"] for tool in dynamic_tools] == [name.value for name in OperatorToolName]
    assert all(tool["type"] == "function" for tool in dynamic_tools)
    assert all(
        cast(dict[str, object], tool["inputSchema"])["additionalProperties"] is False
        for tool in dynamic_tools
    )
    assert isolation["mcp_servers"] == {"external_docs": {"enabled": False}}
    assert isolation["web_search"] == "disabled"
    assert all(enabled is False for enabled in isolation["features"].values())
    assert isolation["features"]["code_mode_only"] is False
    assert isolation["features"]["deferred_executor"] is False
    assert isolation["skills"] == {"include_instructions": False}
    assert isolation["orchestrator"] == {
        "mcp": {"enabled": False},
        "skills": {"enabled": False},
    }
    assert turn_thread_id == "codex-thread-1"
    assert turn_input == "Create a research workflow."
    assert turn["approvalPolicy"] == "never"
    assert turn["environments"] == []
    output_schema = cast(dict[str, Any], turn["outputSchema"])
    assert output_schema["type"] == "object"
    assert output_schema["required"] == ["result"]
    assert output_schema["additionalProperties"] is False
    assert "anyOf" in output_schema["properties"]["result"]
    assert all(
        node.get("required") == list(cast(dict[str, object], node["properties"]))
        and node.get("additionalProperties") is False
        for node in _schema_nodes(output_schema)
        if node.get("type") == "object"
    )
    assert not {
        "const",
        "default",
        "discriminator",
        "oneOf",
        "title",
    }.intersection(key for node in _schema_nodes(output_schema) for key in node)
    assert client.unregistered_turns == ["codex-turn-1"]


@pytest.mark.asyncio
async def test_codex_operator_resumes_exact_thread_with_typed_answer_and_ask_result() -> None:
    thread_id = "opaque-codex-thread"
    factory = _ClientFactory(
        thread_id=thread_id,
        resumed_thread_id=thread_id,
        output={
            "kind": "ask_user",
            "explanation": None,
            "questions": [
                {
                    "header": "Review",
                    "question": "How deep?",
                    "allow_skip": False,
                    "options": [
                        {"label": "Focused", "description": "Review changed behavior."},
                        {"label": "Full", "description": "Review connected boundaries."},
                    ],
                }
            ],
        },
    )
    answers = OperatorQuestionAnswersTurnInput(
        answers=(
            OperatorAnsweredQuestion(
                question="Team?",
                answer=OperatorAcceptedOptionAnswer(label="Research"),
            ),
            OperatorAnsweredQuestion(
                question="Emphasis?",
                answer=OperatorAcceptedCustomAnswer(text="Auditability"),
            ),
        )
    )

    outcome = await _runner(factory).execute_turn(
        _request(provider_thread_id=thread_id, turn_input=answers)
    )

    client = factory.clients[0]
    resumed_id, resume = client.thread_resume_params[0]
    assert resumed_id == thread_id
    assert resume["baseInstructions"] == "Exact prompt.\nPreserve this whitespace.\n"
    assert resume["developerInstructions"] == ""
    assert resume["excludeTurns"] is True
    assert "dynamicTools" not in resume
    assert client.turn_start_calls[0][2]["environments"] == []
    assert json.loads(client.turn_start_calls[0][1]) == answers.model_dump(mode="json")
    assert outcome.provider_thread_id == thread_id
    assert outcome.result.kind == "ask_user"


@pytest.mark.asyncio
async def test_codex_dynamic_tools_call_one_leaf_once_and_redact_every_failure() -> None:
    calls: list[tuple[OperatorToolName, str]] = []
    tool_name = OperatorToolName.WORKFLOW_SEARCH.value
    factory = _ClientFactory(
        server_requests=(
            (
                "item/tool/call",
                {"tool": tool_name, "namespace": None, "arguments": {"value": "truth"}},
            ),
            (
                "item/tool/call",
                {"tool": tool_name, "namespace": None, "arguments": {"wrong": "shape"}},
            ),
            (
                "item/tool/call",
                {"tool": "unknown_tool", "namespace": None, "arguments": {}},
            ),
            (
                "item/tool/call",
                {"tool": tool_name, "namespace": None, "arguments": {"value": "oversize"}},
            ),
            (
                "item/tool/call",
                {"tool": tool_name, "namespace": None, "arguments": {"value": "raise-secret"}},
            ),
            ("item/commandExecution/requestApproval", {}),
        )
    )

    await _runner(factory, tools=_tools(calls)).execute_turn(_request())

    accepted, invalid, unknown, oversized, failed, approval = factory.clients[0].server_results
    assert calls == [
        (OperatorToolName.WORKFLOW_SEARCH, "truth"),
        (OperatorToolName.WORKFLOW_SEARCH, "oversize"),
        (OperatorToolName.WORKFLOW_SEARCH, "raise-secret"),
    ]
    assert accepted["success"] is True
    assert json.loads(cast(list[dict[str, str]], accepted["contentItems"])[0]["text"]) == {
        "echo": "truth"
    }
    for rejected in (invalid, unknown, oversized, failed):
        assert rejected["success"] is False
        text = cast(list[dict[str, str]], rejected["contentItems"])[0]["text"]
        payload = json.loads(text)
        assert payload["error"] == "operator_operation_outcome_uncertain"
        assert "Do not repeat it automatically" in payload["message"]
        assert "private tool failure" not in text
    assert approval == {"decision": "cancel"}


@pytest.mark.asyncio
async def test_codex_operator_fails_closed_on_unknown_server_request() -> None:
    factory = _ClientFactory(
        server_requests=(("future/authority/request", {}),),
    )

    with pytest.raises(
        OperatorProviderUnavailableError,
        match="unsupported Operator capability",
    ):
        await _runner(factory).execute_turn(_request())

    assert factory.clients[0].was_closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output",
    (
        "not JSON",
        {"kind": "operator_return", "text": "not part of the contract"},
        {"kind": "message", "text": "x" * (MAX_OPERATOR_TEXT_BYTES + 1)},
    ),
)
async def test_codex_operator_rejects_invalid_structured_output(output: object) -> None:
    factory = _ClientFactory(output=output)

    with pytest.raises(OperatorProviderUnavailableError):
        await _runner(factory).execute_turn(_request())

    assert factory.clients[0].was_closed is True


@pytest.mark.asyncio
async def test_codex_operator_maps_missing_resume_to_thread_unavailable() -> None:
    thread_id = "missing-codex-thread"
    factory = _ClientFactory(
        resume_error=InvalidRequestError(
            -32600,
            f"no rollout found for thread id {thread_id}",
        )
    )

    with pytest.raises(OperatorProviderThreadUnavailableError):
        await _runner(factory).execute_turn(_request(provider_thread_id=thread_id))

    assert factory.clients[0].turn_start_calls == []
    assert factory.clients[0].was_closed is True


@pytest.mark.asyncio
async def test_codex_operator_fails_before_model_turn_on_external_mcp_surface() -> None:
    factory = _ClientFactory(
        active_mcp=(
            SimpleNamespace(
                tools={"external": object()},
                resources=[],
                resource_templates=[],
                server_info=object(),
            ),
        )
    )

    with pytest.raises(
        OperatorProviderUnavailableError,
        match="external MCP surface",
    ):
        await _runner(factory).execute_turn(_request())

    assert factory.clients[0].turn_start_calls == []
    assert factory.clients[0].was_closed is True


@pytest.mark.asyncio
async def test_codex_operator_cancellation_interrupts_turn_and_closes_client() -> None:
    factory = _ClientFactory(should_block=True, should_block_close=True)
    turn = asyncio.create_task(_runner(factory).execute_turn(_request()))
    await asyncio.sleep(0)
    client = factory.clients[0]
    assert await asyncio.to_thread(client.waiting.wait, 2)

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
    factory = _ClientFactory(should_block_start=True)
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
    factory = _ClientFactory(
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


def test_codex_operator_status_fails_closed_on_unpinned_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        codex_operator,
        "_installed_codex_versions",
        lambda: ("0.144.5", PINNED_CODEX_VERSION),
    )
    factory = _ClientFactory()

    runner = _runner(factory)

    assert runner.status.availability == "unavailable"
    assert PINNED_CODEX_VERSION in runner.status.explanation
    assert factory.clients == []


def test_codex_operator_requires_the_exact_ordered_tool_catalog() -> None:
    factory = _ClientFactory()

    with pytest.raises(ValueError, match="exact ordered"):
        CodexOperatorTurnRunner(
            system_prompt="Prompt.",
            tools=tuple(reversed(_tools())),
            status=_status(),
            client_factory=factory,
        )


@pytest.mark.parametrize(
    "effort",
    ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"),
)
def test_codex_operator_accepts_the_pinned_closed_effort_set(effort: str) -> None:
    assert resolve_codex_operator_effort(effort) == effort


@pytest.mark.asyncio
async def test_codex_operator_rejects_unknown_effort_before_start() -> None:
    factory = _ClientFactory()

    with pytest.raises(
        OperatorProviderUnavailableError,
        match="effort is not supported",
    ):
        await _runner(factory).execute_turn(_request(effort="impossible"))

    assert factory.clients == []


def _schema_nodes(value: object) -> list[dict[str, object]]:
    if isinstance(value, list):
        return [node for item in value for node in _schema_nodes(item)]
    if not isinstance(value, dict):
        return []
    return [
        cast(dict[str, object], value),
        *(node for child in value.values() for node in _schema_nodes(child)),
    ]
