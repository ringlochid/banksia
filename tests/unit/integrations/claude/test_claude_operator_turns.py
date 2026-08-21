from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, ProcessError
from claude_agent_sdk.types import ResultMessage
from mcp.types import CallToolRequest, CallToolRequestParams

from oh_my_subagents.integrations.claude.native_identity import (
    ClaudeAuthenticationState,
    ClaudeEndpointPolicyState,
    ClaudeSubscriptionClass,
)
from oh_my_subagents.integrations.claude.operator import (
    CLAUDE_OPERATOR_MCP_SERVER_NAME,
    ClaudeOperatorTurnRunner,
)
from oh_my_subagents.operator.contracts import (
    MAX_OPERATOR_TEXT_BYTES,
    OPERATOR_PROVIDER_RESULT_ADAPTER,
)
from oh_my_subagents.operator.provider import (
    OperatorAcceptedCustomAnswer,
    OperatorAcceptedOptionAnswer,
    OperatorAnsweredQuestion,
    OperatorProviderThreadUnavailableError,
    OperatorProviderUnavailableError,
    OperatorQuestionAnswersTurnInput,
)
from oh_my_subagents.operator.tools import OperatorToolName
from oh_my_subagents.runtime.providers import ProviderAuthenticationMethod
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


def _result(
    *,
    session_id: str = "claude-thread-1",
    structured_output: object = None,
    is_error: bool = False,
    errors: list[str] | None = None,
) -> ResultMessage:
    return ResultMessage(
        subtype="error_during_execution" if is_error else "success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=is_error,
        num_turns=1,
        session_id=session_id,
        structured_output=structured_output,
        errors=errors,
    )


def _schema_keywords(value: object) -> set[str]:
    if isinstance(value, dict):
        keywords = set(value)
        for key, child in value.items():
            if key == "properties" and isinstance(child, dict):
                for property_schema in child.values():
                    keywords.update(_schema_keywords(property_schema))
            else:
                keywords.update(_schema_keywords(child))
        return keywords
    if isinstance(value, list):
        return {nested_keyword for child in value for nested_keyword in _schema_keywords(child)}
    return set()


def _structured_output(result: object) -> dict[str, object]:
    return {"result": result}


def _message_output(text: str) -> dict[str, object]:
    return _structured_output({"kind": "message", "text": text})


def _assert_native_output_schema(output_format_value: object) -> None:
    output_format = cast(dict[str, Any], output_format_value)
    assert output_format["type"] == "json_schema"
    output_schema = cast(dict[str, Any], output_format["schema"])
    controller_schema = OPERATOR_PROVIDER_RESULT_ADAPTER.json_schema()
    output_properties = cast(dict[str, Any], output_schema["properties"])
    output_result_schema = cast(dict[str, Any], output_properties["result"])
    assert output_schema["type"] == "object"
    assert output_schema["required"] == ["result"]
    assert output_schema["additionalProperties"] is False
    variants = cast(list[dict[str, Any]], output_result_schema["anyOf"])
    assert len(variants) == len(cast(list[object], controller_schema["oneOf"])) == 2
    variants_by_kind = {variant["properties"]["kind"]["const"]: variant for variant in variants}
    assert set(variants_by_kind) == {"message", "ask_user"}

    message_schema = variants_by_kind["message"]
    assert message_schema["type"] == "object"
    assert message_schema["additionalProperties"] is False
    assert message_schema["required"] == ["kind", "text"]
    assert message_schema["properties"]["kind"] == {
        "const": "message",
        "title": "Kind",
        "type": "string",
    }
    assert message_schema["properties"]["text"]["type"] == "string"

    ask_user_schema = variants_by_kind["ask_user"]
    assert ask_user_schema["type"] == "object"
    assert ask_user_schema["additionalProperties"] is False
    assert ask_user_schema["required"] == ["kind", "questions"]
    question_schema = ask_user_schema["properties"]["questions"]["items"]
    assert question_schema["type"] == "object"
    assert question_schema["additionalProperties"] is False
    assert question_schema["required"] == ["header", "question", "options"]
    assert question_schema["properties"]["allow_skip"]["type"] == "boolean"
    option_schema = question_schema["properties"]["options"]["items"]
    assert option_schema["type"] == "object"
    assert option_schema["additionalProperties"] is False
    assert option_schema["required"] == ["label", "description"]

    assert _schema_keywords(output_schema) <= {
        "additionalProperties",
        "anyOf",
        "const",
        "items",
        "properties",
        "required",
        "title",
        "type",
    }


@pytest.mark.asyncio
async def test_claude_operator_turn_uses_only_exact_private_tools_and_native_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = FakeClaudeOperatorClientFactory(
        (_result(structured_output=_message_output("The workflow draft is ready for review.")),)
    )
    runner = build_claude_operator_runner(factory, working_directory=tmp_path)

    outcome = await runner.execute_turn(build_claude_operator_request())

    client = factory.clients[0]
    options = client.options
    expected_tools = [
        f"mcp__{CLAUDE_OPERATOR_MCP_SERVER_NAME}__{name.value}" for name in OperatorToolName
    ]
    assert outcome.provider_thread_id == "claude-thread-1"
    assert outcome.result.kind == "message"
    assert client.query_input == "Build an accountable research team."
    assert client.was_connected is True
    assert client.was_disconnected is True
    assert options.tools == []
    assert options.allowed_tools == expected_tools
    assert options.system_prompt == "Exact prompt.\nPreserve this whitespace.\n"
    assert tuple(cast(dict[str, object], options.mcp_servers)) == (CLAUDE_OPERATOR_MCP_SERVER_NAME,)
    assert options.strict_mcp_config is True
    assert options.permission_mode == "dontAsk"
    assert options.resume is None
    assert options.continue_conversation is False
    assert options.fork_session is False
    assert options.model == "claude-sonnet-4-5"
    assert options.fallback_model is None
    assert options.effort == "high"
    assert options.cwd == tmp_path
    assert options.add_dirs == []
    assert options.setting_sources == []
    assert options.skills == []
    assert options.plugins == []
    assert options.agents == {}
    assert options.hooks is None
    assert options.sandbox is None
    assert {"Agent", "Artifact", "Skill", "SlashCommand"} <= set(options.disallowed_tools)
    assert options.extra_args == {
        "safe-mode": None,
        "disable-slash-commands": None,
        "no-chrome": None,
    }
    assert options.env["CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS"] == "1"
    assert options.env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert options.env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] == "1"
    assert options.env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
    assert options.env["CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS"] == "1"
    assert "CLAUDE_CODE_SKIP_PROMPT_HISTORY" not in options.env
    assert "no-session-persistence" not in options.extra_args
    _assert_native_output_schema(options.output_format)


@pytest.mark.asyncio
async def test_claude_operator_uses_bare_for_api_key_and_rejects_managed_subscription() -> None:
    api_factory = FakeClaudeOperatorClientFactory(
        (_result(structured_output=_message_output("Done.")),)
    )
    api_runner = ClaudeOperatorTurnRunner(
        system_prompt="Exact prompt.",
        tools=build_claude_operator_tools(),
        status=build_claude_operator_status(),
        client_factory=api_factory,
        authentication_reader=lambda: ClaudeAuthenticationState(
            is_authenticated=True,
            method=ProviderAuthenticationMethod.API_KEY,
            code="claude_available",
        ),
        endpoint_policy_reader=lambda: ClaudeEndpointPolicyState(
            is_installed=True,
            code="claude_endpoint_policy_unsupported",
        ),
    )

    await api_runner.execute_turn(build_claude_operator_request())

    assert "bare" in api_factory.clients[0].options.extra_args
    assert "safe-mode" not in api_factory.clients[0].options.extra_args

    managed_factory = FakeClaudeOperatorClientFactory(())
    managed_runner = ClaudeOperatorTurnRunner(
        system_prompt="Exact prompt.",
        tools=build_claude_operator_tools(),
        status=build_claude_operator_status(),
        client_factory=managed_factory,
        authentication_reader=lambda: ClaudeAuthenticationState(
            is_authenticated=True,
            method=ProviderAuthenticationMethod.SUBSCRIPTION,
            code="claude_available",
            subscription_class=ClaudeSubscriptionClass.MANAGED,
        ),
        endpoint_policy_reader=read_clear_claude_endpoint_policy,
    )

    with pytest.raises(OperatorProviderUnavailableError, match="isolated"):
        await managed_runner.execute_turn(build_claude_operator_request())

    assert managed_factory.clients == []


@pytest.mark.asyncio
async def test_claude_operator_rejects_ambient_startup_readback_before_query() -> None:
    clients: list[FakeClaudeOperatorClient] = []

    class AmbientClient(FakeClaudeOperatorClient):
        async def get_context_usage(self) -> dict[str, object]:
            return {
                "memoryFiles": [{"path": "CLAUDE.md"}],
                "agents": [],
                "mcpTools": [],
            }

    def build_client(options: ClaudeAgentOptions) -> ClaudeSDKClient:
        client = AmbientClient(options, messages=())
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

    with pytest.raises(OperatorProviderUnavailableError):
        await runner.execute_turn(build_claude_operator_request())

    assert clients[0].query_input is None
    assert clients[0].was_disconnected is True


@pytest.mark.asyncio
async def test_claude_operator_continues_exact_thread_with_typed_answers() -> None:
    thread_id = "opaque-Claude-thread"
    factory = FakeClaudeOperatorClientFactory(
        (
            _result(
                session_id=thread_id,
                structured_output=_structured_output(
                    {
                        "kind": "ask_user",
                        "explanation": "Choose the review depth.",
                        "questions": [
                            {
                                "header": "Review",
                                "question": "How deep should the review be?",
                                "allow_skip": False,
                                "options": [
                                    {
                                        "label": "Focused",
                                        "description": "Review only changed behavior.",
                                    },
                                    {
                                        "label": "Comprehensive",
                                        "description": "Review every connected boundary.",
                                    },
                                ],
                            }
                        ],
                    }
                ),
            ),
        )
    )
    answers = OperatorQuestionAnswersTurnInput(
        answers=(
            OperatorAnsweredQuestion(
                question="Which team should own the review?",
                answer=OperatorAcceptedOptionAnswer(label="Équipe recherche"),
            ),
            OperatorAnsweredQuestion(
                question="What should the team emphasize?",
                answer=OperatorAcceptedCustomAnswer(text="Race safety + auditability"),
            ),
        )
    )

    outcome = await build_claude_operator_runner(factory).execute_turn(
        build_claude_operator_request(provider_thread_id=thread_id, turn_input=answers)
    )

    client = factory.clients[0]
    assert client.options.resume == thread_id
    assert json.loads(cast(str, client.query_input)) == answers.model_dump(mode="json")
    assert outcome.provider_thread_id == thread_id
    assert outcome.result.kind == "ask_user"


@pytest.mark.asyncio
async def test_claude_private_mcp_tool_calls_one_leaf_and_redacts_failures() -> None:
    calls: list[tuple[OperatorToolName, str]] = []
    factory = FakeClaudeOperatorClientFactory(
        (_result(structured_output=_message_output("Done.")),)
    )
    runner = ClaudeOperatorTurnRunner(
        system_prompt="Exact prompt.",
        tools=build_claude_operator_tools(calls),
        status=build_claude_operator_status(),
        client_factory=factory,
        authentication_reader=read_personal_claude_authentication,
        endpoint_policy_reader=read_clear_claude_endpoint_policy,
    )
    await runner.execute_turn(build_claude_operator_request())
    server_config = cast(
        dict[str, Any],
        cast(dict[str, object], factory.clients[0].options.mcp_servers)[
            CLAUDE_OPERATOR_MCP_SERVER_NAME
        ],
    )
    server = server_config["instance"]
    call_handler = server.request_handlers[CallToolRequest]

    accepted = await call_handler(
        CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name=OperatorToolName.WORKFLOW_SEARCH.value,
                arguments={"value": "current truth"},
            ),
        )
    )
    rejected = await call_handler(
        CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name=OperatorToolName.WORKFLOW_SEARCH.value,
                arguments={"value": "raise-secret"},
            ),
        )
    )
    uncertain_after_commit = await call_handler(
        CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name=OperatorToolName.WORKFLOW_SEARCH.value,
                arguments={"value": "oversize-after-commit"},
            ),
        )
    )

    assert calls == [
        (OperatorToolName.WORKFLOW_SEARCH, "current truth"),
        (OperatorToolName.WORKFLOW_SEARCH, "raise-secret"),
        (OperatorToolName.WORKFLOW_SEARCH, "oversize-after-commit"),
    ]
    assert json.loads(accepted.root.content[0].text) == {"echo": "current truth"}
    assert rejected.root.isError is True
    assert "private provider detail" not in rejected.root.content[0].text
    failure = json.loads(rejected.root.content[0].text)
    assert failure["error"] == "operator_operation_outcome_uncertain"
    assert "Do not repeat" in failure["message"]
    assert "inspect authoritative product truth" in failure["message"]
    assert uncertain_after_commit.root.isError is True
    assert json.loads(uncertain_after_commit.root.content[0].text) == failure


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "structured_output",
    (
        None,
        {"kind": "message", "text": "bare controller result"},
        {},
        {**_message_output("wrapped"), "unexpected": True},
        _structured_output(
            {
                "kind": "ask_user",
                "questions": [],
            }
        ),
        _message_output("x" * (MAX_OPERATOR_TEXT_BYTES + 1)),
    ),
)
async def test_claude_operator_rejects_missing_invalid_or_unwrapped_structured_output(
    structured_output: object,
) -> None:
    factory = FakeClaudeOperatorClientFactory((_result(structured_output=structured_output),))

    with pytest.raises(OperatorProviderUnavailableError):
        await build_claude_operator_runner(factory).execute_turn(build_claude_operator_request())

    assert factory.clients[0].was_disconnected is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    (
        _result(
            session_id="thread-1",
            is_error=True,
            errors=["No conversation found with session ID: thread-1"],
        ),
        _result(
            session_id="different-thread",
            structured_output=_message_output("Wrong thread."),
        ),
    ),
)
async def test_claude_operator_maps_lost_or_changed_resume_to_thread_unavailable(
    result: ResultMessage,
) -> None:
    factory = FakeClaudeOperatorClientFactory((result,))

    with pytest.raises(OperatorProviderThreadUnavailableError):
        await build_claude_operator_runner(factory).execute_turn(
            build_claude_operator_request(provider_thread_id="thread-1")
        )

    assert factory.clients[0].was_disconnected is True


@pytest.mark.asyncio
async def test_claude_operator_maps_sdk_resume_failure_to_thread_unavailable() -> None:
    factory = FakeClaudeOperatorClientFactory(
        (),
        response_error=ProcessError(
            "Claude process failed",
            exit_code=1,
            stderr="No conversation found with session ID: thread-1",
        ),
    )

    with pytest.raises(OperatorProviderThreadUnavailableError):
        await build_claude_operator_runner(factory).execute_turn(
            build_claude_operator_request(provider_thread_id="thread-1")
        )

    assert factory.clients[0].was_disconnected is True


def test_claude_operator_requires_the_exact_ordered_tool_catalog() -> None:
    factory = FakeClaudeOperatorClientFactory(())

    with pytest.raises(ValueError, match="exact ordered"):
        ClaudeOperatorTurnRunner(
            system_prompt="Exact prompt.",
            tools=build_claude_operator_tools()[:-1],
            status=build_claude_operator_status(),
            client_factory=factory,
            authentication_reader=read_personal_claude_authentication,
            endpoint_policy_reader=read_clear_claude_endpoint_policy,
        )
