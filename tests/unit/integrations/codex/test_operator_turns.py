from __future__ import annotations

import json
from typing import Any, cast

import pytest
from openai_codex import InvalidRequestError

from oh_my_subagents.integrations.codex import operator as codex_operator
from oh_my_subagents.integrations.codex.operator import (
    PINNED_CODEX_VERSION,
    CodexOperatorTurnRunner,
    resolve_codex_operator_effort,
)
from oh_my_subagents.operator.contracts import MAX_OPERATOR_TEXT_BYTES
from oh_my_subagents.operator.provider import (
    OperatorAcceptedCustomAnswer,
    OperatorAcceptedOptionAnswer,
    OperatorAnsweredQuestion,
    OperatorProviderThreadUnavailableError,
    OperatorProviderUnavailableError,
    OperatorQuestionAnswersTurnInput,
)
from oh_my_subagents.operator.tools import OperatorToolName
from tests.unit.integrations.codex.codex_test_support import TEST_AMBIENT_SKILL_PATH
from tests.unit.integrations.codex.codex_test_support import (
    ClientFactory as _ClientFactory,
)
from tests.unit.integrations.codex.codex_test_support import (
    request as _request,
)
from tests.unit.integrations.codex.codex_test_support import (
    runner as _runner,
)
from tests.unit.integrations.codex.codex_test_support import (
    status as _status,
)
from tests.unit.integrations.codex.codex_test_support import (
    tools as _tools,
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
    assert isolation["features"]["remote_plugin"] is False
    assert isolation["features"]["shell_tool"] is False
    assert isolation["features"]["unified_exec"] is False
    assert isolation["project_doc_max_bytes"] == 0
    assert isolation["projects"] == {cast(str, start["cwd"]): {"trust_level": "untrusted"}}
    assert isolation["skills"] == {
        "bundled": {"enabled": False},
        "config": [{"enabled": False, "path": TEST_AMBIENT_SKILL_PATH}],
        "include_instructions": False,
    }
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
    assert resume["runtimeWorkspaceRoots"] == []
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

    await _runner(factory, operator_tools=_tools(calls)).execute_turn(_request())

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
    factory = _ClientFactory(server_requests=(("future/authority/request", {}),))

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


def test_codex_operator_accepts_pinned_ultra_effort() -> None:
    assert resolve_codex_operator_effort("ultra") == "ultra"


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
