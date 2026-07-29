from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NotRequired, TypedDict, Unpack, cast

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

from banksia.integrations.codex.operator import CodexOperatorTurnRunner
from banksia.operator.contracts import OperatorAvailability
from banksia.operator.provider import (
    OperatorMessageTurnInput,
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


class FakeClientOptions(TypedDict):
    output: NotRequired[object]
    thread_id: NotRequired[str]
    resumed_thread_id: NotRequired[str | None]
    ambient_config: NotRequired[dict[str, object]]
    configured_mcp: NotRequired[tuple[str, ...]]
    instruction_sources: NotRequired[tuple[str, ...]]
    runtime_workspace_roots: NotRequired[tuple[str, ...]]
    skill_errors: NotRequired[tuple[object, ...]]
    skill_paths: NotRequired[tuple[str, ...]]
    thread_cwd: NotRequired[str | None]
    active_mcp: NotRequired[tuple[object, ...]]
    server_requests: NotRequired[tuple[tuple[str, JsonObject | None], ...]]
    resume_error: NotRequired[Exception | None]


class FakeCodexClient:
    def __init__(
        self,
        handler: Callable[[str, JsonObject | None], JsonObject],
        *,
        output: object = None,
        thread_id: str = "codex-thread-1",
        resumed_thread_id: str | None = None,
        ambient_config: dict[str, object] | None = None,
        configured_mcp: tuple[str, ...] = ("external_docs",),
        instruction_sources: tuple[str, ...] = (),
        runtime_workspace_roots: tuple[str, ...] = (),
        skill_errors: tuple[object, ...] = (),
        skill_paths: tuple[str, ...] = ("/opt/codex/skills/ambient/SKILL.md",),
        thread_cwd: str | None = None,
        active_mcp: tuple[object, ...] = (),
        server_requests: tuple[tuple[str, JsonObject | None], ...] = (),
        resume_error: Exception | None = None,
    ) -> None:
        self.handler = handler
        self.output = output if output is not None else {"kind": "message", "text": "Done."}
        self.thread_id = thread_id
        self.resumed_thread_id = resumed_thread_id or thread_id
        self.ambient_config = ambient_config
        self.configured_mcp = configured_mcp
        self.instruction_sources = instruction_sources
        self.runtime_workspace_roots = runtime_workspace_roots
        self.skill_errors = skill_errors
        self.skill_paths = skill_paths
        self.thread_cwd = thread_cwd
        self.active_mcp = active_mcp
        self.server_requests = server_requests
        self.resume_error = resume_error
        self.server_results: list[JsonObject] = []
        self.thread_start_params: list[JsonObject] = []
        self.thread_resume_params: list[tuple[str, JsonObject]] = []
        self.turn_start_calls: list[tuple[str, str, JsonObject]] = []
        self.unregistered_turns: list[str] = []
        self.was_started = False
        self.was_initialized = False
        self.was_closed = False
        self.cwd_existed_at_start = False
        self.notifications: list[Notification] = []

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
        response_model: type[BaseModel],
    ) -> Any:
        del response_model
        if method == "config/read":
            config = self.ambient_config or {
                "mcp_servers": {name: {"enabled": True} for name in self.configured_mcp}
            }
            return ConfigReadResponse.model_validate({"config": config, "origins": {}})
        if method == "skills/list":
            assert params is not None
            cwd = cast(list[str], params["cwds"])[0]
            return SimpleNamespace(
                data=[
                    SimpleNamespace(
                        cwd=SimpleNamespace(root=cwd),
                        errors=list(self.skill_errors),
                        skills=[
                            SimpleNamespace(
                                enabled=True,
                                name=Path(path).parent.name,
                                path=SimpleNamespace(root=path),
                                scope=SimpleNamespace(value="user"),
                            )
                            for path in self.skill_paths
                        ],
                    )
                ]
            )
        if method in {"thread/start", "thread/resume"}:
            assert params is not None
            return self._open_thread(method, params)
        if method == "mcpServerStatus/list":
            return SimpleNamespace(data=list(self.active_mcp), next_cursor=None)
        raise AssertionError(f"unexpected request method: {method}")

    def _open_thread(self, method: str, params: JsonObject) -> object:
        cwd = params.get("cwd")
        self.cwd_existed_at_start = isinstance(cwd, str) and Path(cwd).is_dir()
        thread_id = self.thread_id
        if method == "thread/start":
            self.thread_start_params.append(params)
        else:
            requested_thread_id = cast(str, params["threadId"])
            self.thread_resume_params.append((requested_thread_id, params))
            if self.resume_error is not None:
                raise self.resume_error
            thread_id = self.resumed_thread_id
        return SimpleNamespace(
            approval_policy=SimpleNamespace(root="never"),
            cwd=SimpleNamespace(root=cwd),
            instruction_sources=list(self.instruction_sources),
            model=params.get("model"),
            runtime_workspace_roots=[
                SimpleNamespace(root=path) for path in self.runtime_workspace_roots
            ],
            sandbox=SimpleNamespace(root=SimpleNamespace(type="readOnly")),
            thread=SimpleNamespace(
                cwd=SimpleNamespace(root=self.thread_cwd or cwd),
                ephemeral=False,
                id=thread_id,
            ),
        )

    def turn_start(
        self,
        thread_id: str,
        input_items: str,
        params: JsonObject,
    ) -> object:
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

    def next_turn_notification(self, turn_id: str) -> Notification:
        if not self.notifications:
            raise AssertionError(f"no notification available for {turn_id}")
        return self.notifications.pop(0)

    def unregister_turn_notifications(self, turn_id: str) -> None:
        self.unregistered_turns.append(turn_id)

    def close(self) -> None:
        self.was_closed = True


class ClientFactory:
    def __init__(self, **client_options: Unpack[FakeClientOptions]) -> None:
        self.client_options = client_options
        self.clients: list[FakeCodexClient] = []

    def __call__(
        self,
        handler: Callable[[str, JsonObject | None], JsonObject],
    ) -> CodexClient:
        client = FakeCodexClient(handler, **self.client_options)
        self.clients.append(client)
        return cast(CodexClient, client)


def status(*, availability: OperatorAvailability = "available") -> OperatorRunnerStatus:
    return OperatorRunnerStatus(
        availability=availability,
        configured_provider="codex",
        explanation="Operator is available through Codex.",
        model="gpt-5.3-codex",
        effort="high",
    )


def tools(
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


def request(
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


def runner(
    factory: ClientFactory,
    *,
    operator_tools: tuple[OperatorTool, ...] | None = None,
) -> CodexOperatorTurnRunner:
    return CodexOperatorTurnRunner(
        system_prompt="Exact prompt.\nPreserve this whitespace.\n",
        tools=operator_tools or tools(),
        status=status(),
        client_factory=factory,
    )


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
