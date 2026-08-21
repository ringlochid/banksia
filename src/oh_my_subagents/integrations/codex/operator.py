from __future__ import annotations

import asyncio
import json
import tempfile
import threading
from collections.abc import Callable, Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, cast

from openai_codex import InvalidRequestError
from openai_codex.client import CodexClient
from openai_codex.generated.v2_all import (
    AgentMessageThreadItem,
    ItemCompletedNotification,
    MessagePhase,
    ThreadItem,
    TurnCompletedNotification,
    TurnStatus,
)
from openai_codex.models import JsonObject
from pydantic import ValidationError

from oh_my_subagents.integrations.codex.dynamic_tools import CodexDynamicToolBridge
from oh_my_subagents.integrations.codex.isolation import (
    CodexIsolationError,
    CodexOperatorThreadResponse,
    CodexServerRequestHandler,
    build_codex_client,
    build_codex_operator_isolation_config,
    read_codex_ambient_state,
    require_codex_inert_mcp_isolation,
    require_codex_operator_thread_isolation,
)
from oh_my_subagents.operator.contracts import OPERATOR_PROVIDER_RESULT_ADAPTER
from oh_my_subagents.operator.provider import (
    OperatorMessageTurnInput,
    OperatorProviderThreadUnavailableError,
    OperatorProviderUnavailableError,
    OperatorQuestionAnswersTurnInput,
    OperatorRunnerStatus,
    OperatorTurnOutcome,
    OperatorTurnRequest,
)
from oh_my_subagents.operator.tools import OperatorTool, OperatorToolName

PINNED_CODEX_VERSION = "0.144.4"
_THREAD_UNAVAILABLE_MARKERS = (
    "invalid thread id:",
    "no rollout found for thread id",
    "thread not found:",
)
# Named values in the pinned Rust protocol; its generated Python enum is open-ended.
_CODEX_OPERATOR_EFFORTS = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
)

type _CodexClientFactory = Callable[[CodexServerRequestHandler], CodexClient]


class _CodexTurnIdentity:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread_id: str | None = None
        self._turn_id: str | None = None

    def set_thread_id(self, thread_id: str) -> None:
        with self._lock:
            self._thread_id = thread_id

    def set_turn_id(self, turn_id: str) -> None:
        with self._lock:
            self._turn_id = turn_id

    def snapshot(self) -> tuple[str | None, str | None]:
        with self._lock:
            return self._thread_id, self._turn_id


class CodexOperatorTurnRunner:
    def __init__(
        self,
        *,
        system_prompt: str,
        tools: Sequence[OperatorTool],
        status: OperatorRunnerStatus,
        client_factory: _CodexClientFactory | None = None,
    ) -> None:
        if not system_prompt.strip():
            raise ValueError("Codex Operator system prompt must not be blank")
        if status.configured_provider != "codex":
            raise ValueError("Codex Operator status must select the Codex provider")
        operator_tools = tuple(tools)
        if tuple(tool.name for tool in operator_tools) != tuple(OperatorToolName):
            raise ValueError("Codex Operator requires the exact ordered product-tool catalog")

        self._system_prompt = system_prompt
        self._tools = operator_tools
        self._configured_status = status
        self._client_factory = client_factory or build_codex_client
        self._installed_versions = _installed_codex_versions()

    @property
    def status(self) -> OperatorRunnerStatus:
        if self._configured_status.availability != "available":
            return self._configured_status
        if self._installed_versions == (PINNED_CODEX_VERSION, PINNED_CODEX_VERSION):
            return self._configured_status
        return OperatorRunnerStatus(
            availability="unavailable",
            configured_provider="codex",
            explanation=(
                f"Operator requires the pinned Codex SDK and runtime {PINNED_CODEX_VERSION}."
            ),
            setup_action=(
                f"Install openai-codex=={PINNED_CODEX_VERSION} and restart Oh My Subagents."
            ),
            model=self._configured_status.model,
            effort=self._configured_status.effort,
        )

    async def execute_turn(self, request: OperatorTurnRequest) -> OperatorTurnOutcome:
        status = self.status
        if status.availability != "available":
            raise OperatorProviderUnavailableError(status.explanation)
        if request.provider != "codex":
            raise OperatorProviderUnavailableError("Codex cannot run this Operator conversation")

        effort = resolve_codex_operator_effort(request.effort)
        loop = asyncio.get_running_loop()
        bridge = CodexDynamicToolBridge(loop=loop, tools=self._tools)
        client = self._client_factory(bridge)
        client_start_finished = threading.Event()
        turn_identity = _CodexTurnIdentity()
        worker = asyncio.create_task(
            asyncio.to_thread(
                self._execute_blocking_turn,
                client,
                request,
                effort,
                client_start_finished,
                turn_identity,
            )
        )

        try:
            thread_id, provider_result = await asyncio.shield(worker)
        except asyncio.CancelledError:
            await _cancel_codex_turn(
                client,
                bridge=bridge,
                client_start_finished=client_start_finished,
                turn_identity=turn_identity,
                worker=worker,
            )
            raise
        except (OperatorProviderThreadUnavailableError, OperatorProviderUnavailableError):
            raise
        except CodexIsolationError as exc:
            raise OperatorProviderUnavailableError(str(exc)) from exc
        except Exception as exc:
            raise OperatorProviderUnavailableError(
                "Codex could not complete the Operator turn"
            ) from exc
        finally:
            bridge_cleanup = asyncio.create_task(bridge.deactivate())
            cancellation = await _drain_background_task(bridge_cleanup)
            try:
                await _close_client(client)
            except asyncio.CancelledError as exc:
                cancellation = cancellation or exc
            if cancellation is not None:
                raise cancellation

        return OperatorTurnOutcome(
            provider_thread_id=thread_id,
            result=provider_result,
        )

    def _execute_blocking_turn(
        self,
        client: CodexClient,
        request: OperatorTurnRequest,
        effort: str | None,
        client_start_finished: threading.Event,
        turn_identity: _CodexTurnIdentity,
    ) -> tuple[str, Any]:
        try:
            client.start()
        finally:
            client_start_finished.set()
        client.initialize()

        with tempfile.TemporaryDirectory(prefix="banksia-operator-codex-") as directory:
            working_directory = Path(directory).resolve(strict=False)
            ambient = read_codex_ambient_state(client, working_directory)
            isolation_config = build_codex_operator_isolation_config(
                ambient,
                workspace=working_directory,
            )
            thread_id, thread_response = self._start_or_resume_thread(
                client,
                request=request,
                working_directory=working_directory,
                isolation_config=isolation_config,
            )
            turn_identity.set_thread_id(thread_id)
            require_codex_operator_thread_isolation(
                thread_response,
                expected_model=request.model,
                expected_thread_cwd=(
                    working_directory if request.provider_thread_id is None else None
                ),
                workspace=working_directory,
            )
            require_codex_inert_mcp_isolation(client, thread_id=thread_id)

            turn_params: JsonObject = {
                "approvalPolicy": "never",
                "environments": [],
                "outputSchema": cast(Any, _build_codex_output_schema()),
            }
            if request.model is not None:
                turn_params["model"] = request.model
            if effort is not None:
                turn_params["effort"] = effort
            turn_response = client.turn_start(
                thread_id,
                _render_codex_operator_input(request),
                turn_params,
            )
            turn_id = turn_response.turn.id
            turn_identity.set_turn_id(turn_id)
            provider_result = _read_terminal_result(client, turn_id)

        return thread_id, provider_result

    def _start_or_resume_thread(
        self,
        client: CodexClient,
        *,
        request: OperatorTurnRequest,
        working_directory: Path,
        isolation_config: JsonObject,
    ) -> tuple[str, CodexOperatorThreadResponse]:
        common: JsonObject = {
            "approvalPolicy": "never",
            "approvalsReviewer": "user",
            "baseInstructions": self._system_prompt,
            "config": isolation_config,
            "cwd": str(working_directory),
            "developerInstructions": "",
            "model": request.model,
            "personality": "none",
            "runtimeWorkspaceRoots": [],
            "sandbox": "read-only",
        }
        if request.provider_thread_id is None:
            start_params: JsonObject = {
                **common,
                "allowProviderModelFallback": False,
                "dynamicTools": cast(Any, _dynamic_tool_specs(self._tools)),
                "environments": [],
                "ephemeral": False,
                "selectedCapabilityRoots": [],
            }
            start_response = client.request(
                "thread/start",
                start_params,
                response_model=CodexOperatorThreadResponse,
            )
            thread_id = start_response.thread.id
            if not isinstance(thread_id, str) or not thread_id.strip():
                raise OperatorProviderUnavailableError("Codex returned no Operator thread identity")
            return thread_id, start_response

        resume_params: JsonObject = {
            **common,
            "excludeTurns": True,
            "threadId": request.provider_thread_id,
        }
        try:
            resume_response = client.request(
                "thread/resume",
                resume_params,
                response_model=CodexOperatorThreadResponse,
            )
        except InvalidRequestError as exc:
            if _reports_thread_unavailable(exc):
                raise OperatorProviderThreadUnavailableError() from exc
            raise
        thread_id = resume_response.thread.id
        if thread_id != request.provider_thread_id:
            raise OperatorProviderThreadUnavailableError()
        return thread_id, resume_response


def resolve_codex_operator_effort(value: str | None) -> str | None:
    if value is None:
        return None
    if value not in _CODEX_OPERATOR_EFFORTS:
        raise OperatorProviderUnavailableError("Codex Operator effort is not supported")
    return value


def _read_terminal_result(
    client: CodexClient,
    turn_id: str,
) -> Any:
    items: dict[str, ThreadItem] = {}
    try:
        while True:
            notification = client.next_turn_notification(turn_id)
            payload = notification.payload
            if isinstance(payload, ItemCompletedNotification) and payload.turn_id == turn_id:
                items[_thread_item_id(payload.item)] = payload.item
                continue
            if not isinstance(payload, TurnCompletedNotification) or payload.turn.id != turn_id:
                continue
            for item in payload.turn.items:
                items[_thread_item_id(item)] = item
            if payload.turn.status is not TurnStatus.completed:
                raise OperatorProviderUnavailableError("Codex did not complete the Operator turn")
            break
    finally:
        client.unregister_turn_notifications(turn_id)

    final_response = _final_agent_response(tuple(items.values()))
    if final_response is None:
        raise OperatorProviderUnavailableError("Codex returned no structured Operator result")
    try:
        payload = json.loads(final_response)
        return OPERATOR_PROVIDER_RESULT_ADAPTER.validate_python(_unwrap_codex_output(payload))
    except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
        raise OperatorProviderUnavailableError(
            "Codex returned an invalid structured Operator result"
        ) from exc


def _thread_item_id(item: ThreadItem) -> str:
    value = item.root
    return getattr(value, "id", f"anonymous-{id(value)}")


def _final_agent_response(items: Sequence[ThreadItem]) -> str | None:
    final_answers: list[str] = []
    unphased_answers: list[str] = []
    for item in items:
        value = item.root
        if not isinstance(value, AgentMessageThreadItem):
            continue
        if value.phase is MessagePhase.final_answer:
            final_answers.append(value.text)
        elif value.phase is None:
            unphased_answers.append(value.text)
    candidates = final_answers or unphased_answers
    return candidates[0] if len(candidates) == 1 else None


def _dynamic_tool_specs(tools: Sequence[OperatorTool]) -> list[JsonObject]:
    return [
        {
            "type": "function",
            "name": tool.name.value,
            "description": tool.description,
            "inputSchema": cast(Any, tool.input_schema),
        }
        for tool in tools
    ]


def _build_codex_output_schema() -> dict[str, Any]:
    """Wrap Oh My Subagents's union in the strict root object required by Responses."""

    controller_schema = OPERATOR_PROVIDER_RESULT_ADAPTER.json_schema()
    definitions = controller_schema.get("$defs")
    variants = controller_schema.get("oneOf")
    if not isinstance(definitions, dict) or not isinstance(variants, list):
        raise RuntimeError("Operator result schema no longer has the expected union shape")

    return {
        "$defs": _strict_codex_schema_value(definitions),
        "type": "object",
        "properties": {
            "result": {
                "anyOf": _strict_codex_schema_value(variants),
            }
        },
        "required": ["result"],
        "additionalProperties": False,
    }


def _strict_codex_schema_value(value: object) -> object:
    if isinstance(value, list):
        return [_strict_codex_schema_value(item) for item in value]
    if not isinstance(value, dict):
        return value

    transformed: dict[str, object] = {}
    for key, child in value.items():
        if key in {"default", "discriminator", "title"}:
            continue
        if key == "oneOf":
            transformed["anyOf"] = _strict_codex_schema_value(child)
            continue
        if key == "const":
            transformed["enum"] = [_strict_codex_schema_value(child)]
            continue
        transformed[key] = _strict_codex_schema_value(child)

    properties = transformed.get("properties")
    if transformed.get("type") == "object" and isinstance(properties, dict):
        transformed["additionalProperties"] = False
        transformed["required"] = list(properties)
    return transformed


def _unwrap_codex_output(payload: object) -> object:
    if not isinstance(payload, dict) or set(payload) != {"result"}:
        raise ValueError("Codex structured output has an invalid root")
    return payload["result"]


def _render_codex_operator_input(request: OperatorTurnRequest) -> str:
    match request.input:
        case OperatorMessageTurnInput(text=text):
            return text
        case OperatorQuestionAnswersTurnInput() as answers:
            return json.dumps(
                answers.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
            )


def _reports_thread_unavailable(exc: InvalidRequestError) -> bool:
    normalized = exc.message.casefold()
    return any(marker in normalized for marker in _THREAD_UNAVAILABLE_MARKERS)


async def _cancel_codex_turn(
    client: CodexClient,
    *,
    bridge: CodexDynamicToolBridge,
    client_start_finished: threading.Event,
    turn_identity: _CodexTurnIdentity,
    worker: asyncio.Task[tuple[str, Any]],
) -> None:
    bridge_cleanup = asyncio.create_task(bridge.deactivate())
    await _drain_background_task(bridge_cleanup)
    start_waiter = asyncio.create_task(asyncio.to_thread(client_start_finished.wait))
    await _drain_background_task(start_waiter)

    thread_id, turn_id = turn_identity.snapshot()
    cleanup_tasks: list[asyncio.Task[Any]] = []
    if thread_id is not None and turn_id is not None:
        cleanup_tasks.append(
            asyncio.create_task(asyncio.to_thread(client.turn_interrupt, thread_id, turn_id))
        )
    cleanup_tasks.append(asyncio.create_task(asyncio.to_thread(client.close)))
    for cleanup_task in cleanup_tasks:
        await _drain_background_task(cleanup_task)
    await _drain_background_task(worker)


async def _close_client(client: CodexClient) -> None:
    close_task = asyncio.create_task(asyncio.to_thread(client.close))
    cancellation = await _drain_background_task(close_task)
    if cancellation is not None:
        raise cancellation


async def _drain_background_task(
    task: asyncio.Task[Any],
) -> asyncio.CancelledError | None:
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            cancellation = cancellation or exc
        except BaseException:
            pass
    try:
        task.result()
    except BaseException:
        pass
    return cancellation


def _installed_codex_versions() -> tuple[str | None, str | None]:
    return (
        _package_version("openai-codex"),
        _package_version("openai-codex-cli-bin"),
    )


def _package_version(distribution: str) -> str | None:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return None


__all__ = [
    "PINNED_CODEX_VERSION",
    "CodexOperatorTurnRunner",
    "resolve_codex_operator_effort",
]
