from __future__ import annotations

from typing import cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from mcp.types import CallToolResult

from banksia.interfaces.mcp.operator.server import (
    OPERATOR_TOOL_NAMES,
    create_operator_mcp_server,
)
from banksia.interfaces.mcp.operator.workflow_tools import WORKFLOW_OPERATOR_TOOL_NAMES


async def test_operator_human_resolution_schema_uses_typed_response_map() -> None:
    tools = await create_operator_mcp_server().list_tools()
    tool = next(tool for tool in tools if tool.name == "human_request_respond")
    schema = cast(dict[str, object], tool.inputSchema)
    properties = cast(dict[str, object], schema["properties"])
    input_schema = cast(dict[str, object], properties["input"])
    assert input_schema == {"$ref": "#/$defs/HumanRequestResponseInput"}
    definitions = cast(dict[str, object], schema["$defs"])
    answer_input = cast(dict[str, object], definitions["HumanRequestAnswerInput"])
    answer_properties = cast(dict[str, object], answer_input["properties"])
    item_responses_schema = cast(dict[str, object], answer_properties["item_responses"])

    assert item_responses_schema["type"] == "object"
    assert "additionalProperties" in item_responses_schema
    assert "items" not in item_responses_schema
    answer_schema = definitions["HumanRequestItemAnswer"]
    assert cast(dict[str, object], answer_schema)["discriminator"] == {
        "mapping": {
            "option": "#/$defs/HumanRequestOptionAnswer",
            "other": "#/$defs/HumanRequestOtherAnswer",
            "skipped": "#/$defs/HumanRequestSkippedAnswer",
            "value": "#/$defs/HumanRequestValueAnswer",
        },
        "propertyName": "kind",
    }

    validator = Draft202012Validator(schema)
    validator.validate(
        {
            "task_id": "task.operator-schema",
            "request_id": "human-request.operator-schema.01",
            "action_id": "action.opaque",
            "input": {
                "kind": "answer",
                "item_responses": {
                    "review_choice": {
                        "kind": "option",
                        "option_id": "approve",
                    }
                },
            },
        }
    )
    removed_response_shapes = (
        {
            "task_id": "task.operator-schema",
            "request_id": "human-request.operator-schema.01",
            "action_id": "action.opaque",
            "input": {
                "kind": "answer",
                "item_responses": {"review_choice": "approve"},
            },
        },
        {
            "task_id": "task.operator-schema",
            "request_id": "human-request.operator-schema.01",
            "action_id": "action.opaque",
            "input": {
                "kind": "answer",
                "item_responses": [
                    {
                        "item_id": "review_choice",
                        "selected_option": "approve",
                    }
                ],
            },
        },
    )
    for payload in removed_response_shapes:
        assert tuple(validator.iter_errors(payload))


async def test_operator_inventory_is_exact_product_catalog_without_support_tools() -> None:
    tools = await create_operator_mcp_server().list_tools()
    tools_by_name = {tool.name: tool for tool in tools}

    assert tuple(tools_by_name) == OPERATOR_TOOL_NAMES
    assert tuple(name for name in tools_by_name if name.startswith("workflow_")) == (
        WORKFLOW_OPERATOR_TOOL_NAMES
    )
    assert "task_start" in tools_by_name
    task_start = tools_by_name["task_start"]
    assert tuple(task_start.inputSchema["properties"]) == (
        "workflow",
        "prompt",
        "workspace",
        "files",
    )
    assert task_start.inputSchema["additionalProperties"] is False
    assert task_start.annotations is not None
    assert task_start.annotations.readOnlyHint is False
    assert tuple(tools_by_name) == (
        "workflow_search",
        "workflow_get",
        "workflow_authoring_options",
        "workflow_draft_create",
        "workflow_draft_edit",
        "workflow_draft_validate",
        "workflow_draft_undo",
        "workflow_draft_discard",
        "workflow_draft_publish",
        "task_search",
        "task_get",
        "task_start",
        "task_control",
        "human_request_respond",
        "command_run_get",
        "command_run_output_read",
        "command_run_cancel",
    )
    assert (
        not {
            "get_task_events",
            "get_operator_snapshot",
            "get_operator_trace",
            "artifact_get",
            "file_get",
            "provider_setup",
            "execute",
        }
        & tools_by_name.keys()
    )

    expected_teaching = {
        "task_control": ("opaque action id",),
        "human_request_respond": ("saved response", "does not claim"),
        "command_run_cancel": ("acceptance", "does not claim"),
    }
    for tool_name, required_phrases in expected_teaching.items():
        tool = tools_by_name[tool_name]
        description = (tool.description or "").casefold()
        assert all(phrase in description for phrase in required_phrases)
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is False

    for tool_name in (
        "workflow_search",
        "workflow_get",
        "workflow_authoring_options",
        "workflow_draft_validate",
        "task_search",
        "task_get",
        "command_run_get",
        "command_run_output_read",
    ):
        tool = tools_by_name[tool_name]
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True


async def test_workflow_operator_tools_are_closed_structured_contracts() -> None:
    server = create_operator_mcp_server()
    tools = await server.list_tools()
    tools_by_name = {tool.name: tool for tool in tools}

    for tool_name in WORKFLOW_OPERATOR_TOOL_NAMES:
        tool = tools_by_name[tool_name]
        assert tool.inputSchema.get("additionalProperties") is False
        assert tool.annotations is not None
        assert tool.annotations.openWorldHint is False

    for tool_name in (
        "workflow_search",
        "workflow_get",
        "workflow_authoring_options",
        "workflow_draft_validate",
    ):
        annotations = tools_by_name[tool_name].annotations
        assert annotations is not None
        assert annotations.readOnlyHint is True

    create_schema = cast(dict[str, object], tools_by_name["workflow_draft_create"].inputSchema)
    create_properties = cast(dict[str, object], create_schema["properties"])
    assert tuple(create_properties) == ("request",)
    request_schema = cast(dict[str, object], create_properties["request"])
    assert request_schema["discriminator"] == {
        "mapping": {
            "create": "#/$defs/CreateWorkflowDraftRequest",
            "open": "#/$defs/OpenWorkflowDraftRequest",
        },
        "propertyName": "kind",
    }
    assert request_schema["oneOf"] == [
        {"$ref": "#/$defs/CreateWorkflowDraftRequest"},
        {"$ref": "#/$defs/OpenWorkflowDraftRequest"},
    ]
    assert "path" not in str(create_schema).casefold()
    assert "yaml" not in str(create_schema).casefold()
    assert "NormalizedWorkflow" not in str(create_schema)

    edit_schema = cast(dict[str, object], tools_by_name["workflow_draft_edit"].inputSchema)
    edit_defs = cast(dict[str, object], edit_schema["$defs"])
    new_member = cast(dict[str, object], edit_defs["NewMember"])
    new_member_properties = cast(dict[str, object], new_member["properties"])
    assert "id" not in new_member_properties

    undo_schema = cast(dict[str, object], tools_by_name["workflow_draft_undo"].inputSchema)
    undo_properties = cast(dict[str, object], undo_schema["properties"])
    assert tuple(undo_properties) == ("draft_id", "etag", "receipt_id")

    rejected = cast(
        CallToolResult,
        await server.call_tool(
            "workflow_authoring_options",
            {"unknown": True},
        ),
    )
    assert rejected.isError is True


async def test_workflow_operator_teaching_describes_one_library_and_create_open_entry() -> None:
    tools = await create_operator_mcp_server().list_tools()
    tools_by_name = {tool.name: tool for tool in tools}
    search_description = (tools_by_name["workflow_search"].description or "").casefold()
    create_description = (tools_by_name["workflow_draft_create"].description or "").casefold()

    assert "published workflow catalog" not in search_description
    assert "library" in search_description
    assert "draft" in search_description
    assert "create or open" in create_description
