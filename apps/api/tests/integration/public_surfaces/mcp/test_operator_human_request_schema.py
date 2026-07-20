from __future__ import annotations

from typing import cast

from autoclaw.interfaces.mcp.operator.server import (
    OPERATOR_TOOL_NAMES,
    create_operator_mcp_server,
)
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]


async def test_operator_human_resolution_schema_uses_typed_response_map() -> None:
    tools = await create_operator_mcp_server().list_tools()
    tool = next(tool for tool in tools if tool.name == "resolve_human_request")
    schema = cast(dict[str, object], tool.inputSchema)
    properties = cast(dict[str, object], schema["properties"])
    item_responses_schema = cast(dict[str, object], properties["item_responses"])

    assert item_responses_schema["type"] == "object"
    assert "additionalProperties" in item_responses_schema
    assert "items" not in item_responses_schema

    validator = Draft202012Validator(schema)
    validator.validate(
        {
            "task_id": "task.operator-schema",
            "request_id": "human-request.operator-schema.01",
            "item_responses": {"review_choice": "approve"},
        }
    )
    legacy_response_errors = tuple(
        validator.iter_errors(
            {
                "task_id": "task.operator-schema",
                "request_id": "human-request.operator-schema.01",
                "item_responses": [
                    {
                        "item_id": "review_choice",
                        "selected_option": "approve",
                    }
                ],
            }
        )
    )
    assert legacy_response_errors


async def test_operator_inventory_teaches_current_truth_and_chronology_without_stale_refs() -> None:
    tools = await create_operator_mcp_server().list_tools()
    tools_by_name = {tool.name: tool for tool in tools}

    assert tuple(tools_by_name) == OPERATOR_TOOL_NAMES
    assert "get_task_events" in tools_by_name
    assert "chronology" in (tools_by_name["get_task_events"].description or "").casefold()
    assert (
        not {
            "get_delivery_state_ref",
            "get_continuity_state_ref",
            "get_watchdog_state_ref",
            "get_provider_events_ref",
        }
        & tools_by_name.keys()
    )

    expected_teaching = {
        "upload_definition": ("future resolution", "pinned tasks", "starts no task"),
        "start_task": ("bootstrap", "asynchronously", "does not mean an assignment"),
        "pause_task": ("closure committed", "does not wait for provider stop"),
        "continue_task": ("successor dispatch", "provider start is asynchronous"),
        "cancel_task": ("controller cancellation", "does not wait for process exit"),
        "resolve_human_request": ("resolution committed", "successor opening"),
        "cancel_command_run": ("cancellation_requested", "does not mean the process exited"),
    }
    for tool_name, required_phrases in expected_teaching.items():
        tool = tools_by_name[tool_name]
        description = (tool.description or "").casefold()
        assert all(phrase in description for phrase in required_phrases)
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is False

    for tool_name in (
        "search_definitions",
        "get_definition",
        "list_definition_versions",
        "get_runtime_task",
        "get_operator_snapshot",
        "get_operator_trace",
        "get_task_events",
        "get_human_requests",
        "get_command_runs",
        "get_command_run",
        "get_command_run_log",
    ):
        tool = tools_by_name[tool_name]
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
