from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.operator.prompt import read_operator_system_prompt
from banksia.operator.tools import OperatorToolName, build_operator_tools
from banksia.runtime.contracts.primitives import (
    CommandRunTerminalSource,
    HumanRequestResolutionSurface,
    TaskEventSource,
)
from banksia.runtime.contracts.prompt import PromptCommandTerminalSource
from banksia.runtime.contracts.start import TaskStartRequest
from tests.helpers.product_surface import product_dispatch_dependencies

EXPECTED_OPERATOR_TOOL_NAMES = (
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
REPO_ROOT = Path(__file__).resolve().parents[3]


@asynccontextmanager
async def _unexpected_session() -> AsyncIterator[AsyncSession]:
    raise AssertionError("schema proof must not open a database session")
    yield  # pragma: no cover


def _assert_object_schemas_are_closed(value: object) -> None:
    if isinstance(value, dict):
        if value.get("type") == "object":
            assert value.get("additionalProperties") is False
        for child in value.values():
            _assert_object_schemas_are_closed(child)
    elif isinstance(value, list):
        for child in value:
            _assert_object_schemas_are_closed(child)


async def test_catalog_is_exact_ordered_direct_and_strict(tmp_path: Path) -> None:
    dependencies = product_dispatch_dependencies(tmp_path)
    tools = build_operator_tools(
        settings=dependencies.settings,
        session_factory=_unexpected_session,
        dispatch_dependencies=dependencies,
    )

    assert tuple(tool.name for tool in tools) == EXPECTED_OPERATOR_TOOL_NAMES
    assert tuple(OperatorToolName) == EXPECTED_OPERATOR_TOOL_NAMES
    assert len({tool.handler for tool in tools}) == len(tools)
    assert next(tool for tool in tools if tool.name == "task_start").input_model is TaskStartRequest

    forbidden_names = {
        "artifact_get",
        "file_get",
        "ask_user",
        "operator_return",
        "import_workflow",
        "upload_workflow",
        "execute",
        "support",
        "setup",
    }
    assert forbidden_names.isdisjoint(EXPECTED_OPERATOR_TOOL_NAMES)

    for tool in tools:
        schema = tool.input_schema
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        serialized = json.dumps(schema).casefold()
        for forbidden_field in ("confirmed", "proposal", "effect", "replay"):
            assert f'"{forbidden_field}"' not in serialized

    with pytest.raises(ValidationError):
        await tools[0].call({"unexpected": True})


def test_full_json_workflow_schema_is_definition_usable(tmp_path: Path) -> None:
    dependencies = product_dispatch_dependencies(tmp_path)
    tools = build_operator_tools(
        settings=dependencies.settings,
        session_factory=_unexpected_session,
        dispatch_dependencies=dependencies,
    )
    schema = next(
        tool.input_schema for tool in tools if tool.name == OperatorToolName.WORKFLOW_DRAFT_CREATE
    )

    Draft202012Validator.check_schema(schema)
    _assert_object_schemas_are_closed(schema)
    Draft202012Validator(schema).validate(
        {
            "workflow": {
                "kind": "workflow",
                "id": "reviewed-delivery",
                "description": "Deliver and independently review a bounded change.",
                "lead": {
                    "id": "lead",
                    "children": [
                        {
                            "id": "reviewer",
                            "provider": {
                                "kind": "codex",
                                "sandbox": {
                                    "mode": "workspace_write",
                                    "network": "deny",
                                },
                            },
                            "capabilities": {
                                "human_request": ["review"],
                                "command_run": "allow",
                            },
                        }
                    ],
                },
            }
        }
    )

    workflow = schema["$defs"]["NormalizedWorkflow"]["properties"]
    member = schema["$defs"]["NormalizedMember"]["properties"]
    assert tuple(workflow) == ("kind", "id", "description", "note", "lead")
    assert {
        "id",
        "title",
        "description",
        "instruction",
        "provider",
        "capabilities",
        "children",
    } == set(member)
    assert {"workflow", "etag"} == set(schema["properties"])


def test_operator_prompt_is_byte_identical_to_its_canonical_appendix() -> None:
    appendix = (
        REPO_ROOT / "docs-internal/design/appendices/operator-conversation-contract.md"
    ).read_text(encoding="utf-8")
    source = appendix.split("The source body is:\n\n```text\n", 1)[1].split("\n```", 1)[0]

    assert read_operator_system_prompt() == f"{source}\n"


def test_operator_provenance_is_semantic_not_transport_named() -> None:
    for provenance in (
        HumanRequestResolutionSurface,
        CommandRunTerminalSource,
        TaskEventSource,
        PromptCommandTerminalSource,
    ):
        assert provenance.OPERATOR.value == "operator"
        assert "OPERATOR_MCP" not in provenance.__members__
