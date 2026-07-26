from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar, cast

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    SdkMcpTool,
    create_sdk_mcp_server,
    tool,
)
from claude_agent_sdk.types import EffortLevel, ResultMessage
from pydantic import ValidationError

from banksia.operator.contracts import OPERATOR_PROVIDER_RESULT_ADAPTER
from banksia.operator.provider import (
    OperatorMessageTurnInput,
    OperatorProviderThreadUnavailableError,
    OperatorProviderUnavailableError,
    OperatorQuestionAnswersTurnInput,
    OperatorRunnerStatus,
    OperatorTurnOutcome,
    OperatorTurnRequest,
)
from banksia.operator.tools import OperatorTool, OperatorToolName
from banksia.platform.provider_environment import (
    ANTHROPIC_API_KEY,
    provider_subprocess_environment_overrides,
)

CLAUDE_OPERATOR_MCP_SERVER_NAME = "banksia_operator"
_CLAUDE_OPERATOR_MCP_SERVER_VERSION = "1.0.0"
_CLAUDE_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
_THREAD_UNAVAILABLE_MARKERS = (
    "no conversation found with session id:",
    "no conversation found to continue",
    "session not found:",
)
_CLAUDE_OUTPUT_SCHEMA_OMITTED_KEYS = frozenset(
    {
        "default",
        "discriminator",
        "maxItems",
        "maxLength",
        "minItems",
        "minLength",
    }
)
_CLAUDE_LOCAL_DEFINITION_PREFIX = "#/$defs/"
_TOOL_FAILURE_RESULT = json.dumps(
    {
        "error": "operator_operation_outcome_uncertain",
        "message": (
            "Banksia could not establish an accepted result. Do not repeat the operation "
            "automatically; inspect authoritative product truth first."
        ),
    },
    separators=(",", ":"),
)
_ClaudeClientFactory = Callable[[ClaudeAgentOptions], ClaudeSDKClient]
_OperationResult = TypeVar("_OperationResult")


@dataclass(frozen=True, slots=True)
class _OperationOutcome[ResultT]:
    result: ResultT | None = None
    error: BaseException | None = None


class ClaudeOperatorTurnRunner:
    """Run isolated Operator turns through the pinned Claude Agent SDK."""

    def __init__(
        self,
        *,
        system_prompt: str,
        tools: Sequence[OperatorTool],
        status: OperatorRunnerStatus,
        working_directory: Path | None = None,
        client_factory: _ClaudeClientFactory = ClaudeSDKClient,
    ) -> None:
        if not system_prompt.strip():
            raise ValueError("Claude Operator system prompt must not be blank")
        if status.configured_provider != "claude":
            raise ValueError("Claude Operator status must select the Claude provider")
        resolve_claude_operator_effort(status.effort)
        operator_tools = tuple(tools)
        if tuple(operator_tool.name for operator_tool in operator_tools) != tuple(OperatorToolName):
            raise ValueError("Claude Operator requires the exact ordered product-tool catalog")

        self._system_prompt = system_prompt
        self._tools = operator_tools
        self._status = status
        self._working_directory = working_directory
        self._client_factory = client_factory

    @property
    def status(self) -> OperatorRunnerStatus:
        return self._status

    async def execute_turn(self, request: OperatorTurnRequest) -> OperatorTurnOutcome:
        if self._status.availability != "available":
            raise OperatorProviderUnavailableError(self._status.explanation)
        if request.provider != "claude":
            raise OperatorProviderUnavailableError("Claude cannot run this Operator conversation")

        options = self._build_options(request)
        client = self._client_factory(options)
        try:
            await _connect_client(client)
            await client.query(_render_claude_operator_input(request))
            result = await _read_terminal_result(client)
        except asyncio.CancelledError:
            await _interrupt_client(client)
            raise
        except Exception as exc:
            if request.provider_thread_id is not None and _reports_thread_unavailable(exc):
                raise OperatorProviderThreadUnavailableError() from exc
            raise OperatorProviderUnavailableError(
                "Claude could not complete the Operator turn"
            ) from exc
        finally:
            await _disconnect_client(client)

        provider_thread_id = result.session_id
        if request.provider_thread_id is not None and (
            not isinstance(provider_thread_id, str)
            or not provider_thread_id.strip()
            or provider_thread_id != request.provider_thread_id
        ):
            raise OperatorProviderThreadUnavailableError()
        if result.is_error:
            if request.provider_thread_id is not None and _reports_thread_unavailable(result):
                raise OperatorProviderThreadUnavailableError()
            raise OperatorProviderUnavailableError("Claude could not complete the Operator turn")
        if not isinstance(provider_thread_id, str) or not provider_thread_id.strip():
            raise OperatorProviderUnavailableError("Claude returned no Operator thread identity")
        if result.structured_output is None:
            raise OperatorProviderUnavailableError("Claude returned no structured Operator result")

        try:
            provider_result = OPERATOR_PROVIDER_RESULT_ADAPTER.validate_python(
                _unwrap_claude_output(result.structured_output)
            )
        except (ValueError, ValidationError) as exc:
            raise OperatorProviderUnavailableError(
                "Claude returned an invalid structured Operator result"
            ) from exc
        return OperatorTurnOutcome(
            provider_thread_id=provider_thread_id,
            result=provider_result,
        )

    def _build_options(self, request: OperatorTurnRequest) -> ClaudeAgentOptions:
        projected_tools = [_project_operator_tool(operator_tool) for operator_tool in self._tools]
        allowed_tools = [
            f"mcp__{CLAUDE_OPERATOR_MCP_SERVER_NAME}__{operator_tool.name.value}"
            for operator_tool in self._tools
        ]
        return ClaudeAgentOptions(
            tools=[],
            allowed_tools=allowed_tools,
            system_prompt=self._system_prompt,
            mcp_servers={
                CLAUDE_OPERATOR_MCP_SERVER_NAME: create_sdk_mcp_server(
                    name=CLAUDE_OPERATOR_MCP_SERVER_NAME,
                    version=_CLAUDE_OPERATOR_MCP_SERVER_VERSION,
                    tools=projected_tools,
                )
            },
            strict_mcp_config=True,
            permission_mode="dontAsk",
            continue_conversation=False,
            resume=request.provider_thread_id,
            model=request.model,
            fallback_model=None,
            cwd=self._working_directory,
            add_dirs=[],
            env=provider_subprocess_environment_overrides(
                allowed_keys=frozenset({ANTHROPIC_API_KEY})
            ),
            hooks=None,
            include_partial_messages=False,
            fork_session=False,
            agents={},
            setting_sources=[],
            skills=[],
            sandbox=None,
            plugins=[],
            effort=resolve_claude_operator_effort(request.effort),
            output_format={
                "type": "json_schema",
                "schema": _build_claude_output_schema(),
            },
        )


def resolve_claude_operator_effort(value: str | None) -> EffortLevel | None:
    if value is None:
        return None
    if value not in _CLAUDE_EFFORTS:
        raise OperatorProviderUnavailableError("Claude Operator effort is not supported")
    return cast(EffortLevel, value)


def _render_claude_operator_input(request: OperatorTurnRequest) -> str:
    match request.input:
        case OperatorMessageTurnInput(text=text):
            return text
        case OperatorQuestionAnswersTurnInput() as answers:
            return json.dumps(
                answers.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
            )


def _project_operator_tool(operator_tool: OperatorTool) -> SdkMcpTool[Any]:
    @tool(
        operator_tool.name.value,
        operator_tool.description,
        operator_tool.input_schema,
    )
    async def call_operator_tool(arguments: object) -> dict[str, Any]:
        try:
            result = await operator_tool.call(arguments)
        except Exception:
            return {
                "content": [{"type": "text", "text": _TOOL_FAILURE_RESULT}],
                "is_error": True,
            }
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        result,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
            ]
        }

    return call_operator_tool


async def _read_terminal_result(client: ClaudeSDKClient) -> ResultMessage:
    terminal_result: ResultMessage | None = None
    async for message in client.receive_response():
        if not isinstance(message, ResultMessage):
            continue
        if terminal_result is not None:
            raise OperatorProviderUnavailableError(
                "Claude returned multiple terminal Operator results"
            )
        terminal_result = message
    if terminal_result is None:
        raise OperatorProviderUnavailableError("Claude returned no terminal Operator result")
    return terminal_result


def _reports_thread_unavailable(report: BaseException | ResultMessage) -> bool:
    fragments: list[str] = []
    if isinstance(report, ResultMessage):
        if report.result is not None:
            fragments.append(report.result)
        if report.errors:
            fragments.extend(report.errors)
    else:
        fragments.append(str(report))
        stderr = getattr(report, "stderr", None)
        if isinstance(stderr, str):
            fragments.append(stderr)
    normalized = "\n".join(fragments).casefold()
    return any(marker in normalized for marker in _THREAD_UNAVAILABLE_MARKERS)


def _build_claude_output_schema() -> dict[str, Any]:
    """Wrap the union for Claude; controller validation stays authoritative."""

    controller_schema = OPERATOR_PROVIDER_RESULT_ADAPTER.json_schema()
    definitions = controller_schema.get("$defs")
    variants = controller_schema.get("oneOf")
    if not isinstance(definitions, dict) or not isinstance(variants, list):
        raise RuntimeError("Operator result schema no longer has the expected union shape")

    return {
        "type": "object",
        "properties": {
            "result": {
                "anyOf": _transform_claude_schema_value(
                    variants,
                    definitions=definitions,
                ),
            }
        },
        "required": ["result"],
        "additionalProperties": False,
    }


def _transform_claude_schema_value(
    value: object,
    *,
    definitions: dict[str, object],
    resolving: tuple[str, ...] = (),
) -> object:
    if isinstance(value, dict):
        if "$ref" in value:
            reference = value["$ref"]
            if not isinstance(reference, str) or not reference.startswith(
                _CLAUDE_LOCAL_DEFINITION_PREFIX
            ):
                raise RuntimeError("Operator result schema contains an invalid reference")
            definition_name = reference.removeprefix(_CLAUDE_LOCAL_DEFINITION_PREFIX)
            definition = definitions.get(definition_name)
            if not definition_name or not isinstance(definition, dict):
                raise RuntimeError("Operator result schema contains a missing definition")
            if definition_name in resolving:
                raise RuntimeError("Operator result schema contains a cyclic definition")
            return _transform_claude_schema_value(
                definition,
                definitions=definitions,
                resolving=(*resolving, definition_name),
            )
        return {
            ("anyOf" if key == "oneOf" else key): _transform_claude_schema_value(
                child,
                definitions=definitions,
                resolving=resolving,
            )
            for key, child in value.items()
            if key not in _CLAUDE_OUTPUT_SCHEMA_OMITTED_KEYS
        }
    if isinstance(value, list):
        return [
            _transform_claude_schema_value(
                child,
                definitions=definitions,
                resolving=resolving,
            )
            for child in value
        ]
    return value


def _unwrap_claude_output(payload: object) -> object:
    if not isinstance(payload, dict) or set(payload) != {"result"}:
        raise ValueError("Claude structured output has an invalid root")
    return payload["result"]


async def _connect_client(client: ClaudeSDKClient) -> None:
    operation_task = asyncio.create_task(_capture_operation(client.connect()))
    try:
        outcome = await asyncio.shield(operation_task)
    except asyncio.CancelledError as cancellation:
        operation_task.cancel()
        await _drain_operation_task(operation_task)
        raise cancellation
    _raise_operation_error(outcome)


async def _interrupt_client(client: ClaudeSDKClient) -> None:
    await _finish_client_cleanup(client.interrupt())


async def _disconnect_client(client: ClaudeSDKClient) -> None:
    await _finish_client_cleanup(client.disconnect())


async def _finish_client_cleanup(operation: Awaitable[object]) -> None:
    operation_task = asyncio.create_task(_capture_operation(operation))
    pending_cancellation: asyncio.CancelledError | None = None
    while not operation_task.done():
        try:
            await asyncio.shield(operation_task)
        except asyncio.CancelledError as exc:
            pending_cancellation = pending_cancellation or exc
    outcome = operation_task.result()
    if pending_cancellation is not None:
        raise pending_cancellation
    if outcome.error is not None and not isinstance(outcome.error, Exception):
        raise outcome.error


async def _capture_operation(
    operation: Awaitable[_OperationResult],
) -> _OperationOutcome[_OperationResult]:
    try:
        return _OperationOutcome(result=await operation)
    except BaseException as exc:
        return _OperationOutcome(error=exc)


async def _drain_operation_task(
    operation_task: asyncio.Task[_OperationOutcome[object]],
) -> None:
    while not operation_task.done():
        try:
            await asyncio.shield(operation_task)
        except asyncio.CancelledError:
            continue


def _raise_operation_error(outcome: _OperationOutcome[object]) -> None:
    if outcome.error is not None:
        raise outcome.error


__all__ = [
    "CLAUDE_OPERATOR_MCP_SERVER_NAME",
    "ClaudeOperatorTurnRunner",
    "resolve_claude_operator_effort",
]
