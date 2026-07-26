from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.operator.prompt import read_operator_system_prompt
from banksia.operator.tools import OperatorToolName, build_operator_tools
from banksia.operator.tools.contracts import (
    MAX_OPERATOR_TOOL_RESULT_UTF16_CODE_UNITS,
    EmptyOperatorToolInput,
    OperatorToolResultTooLargeError,
    TaskGetInput,
    WorkflowDraftCreateInput,
    WorkflowGetInput,
    bind_operator_tool,
)
from banksia.operator.tools.workflow_projection import (
    OperatorPublishedWorkflowSource,
    OperatorWorkflowCatalogResult,
    OperatorWorkflowMemberResult,
    build_operator_workflow_member_result,
    map_operator_workflow_draft_validation_receipt,
)
from banksia.runtime.contracts.primitives import (
    CommandRunTerminalSource,
    HumanRequestResolutionSurface,
    TaskEventSource,
)
from banksia.runtime.contracts.prompt import PromptCommandTerminalSource
from banksia.runtime.contracts.start import TaskStartRequest
from banksia.workflows.authoring_contracts import (
    WorkflowDraftReadback,
    WorkflowDraftValidationResult,
    WorkflowLibraryAction,
    WorkflowLibraryState,
)
from banksia.workflows.contracts import WorkflowProvenance
from banksia.workflows.errors import WorkflowInputError, WorkflowValidationIssue
from banksia.workflows.ingest import normalize_workflow_object
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
            additional_properties = value.get("additionalProperties")
            if "properties" in value:
                assert additional_properties is False
            else:
                assert isinstance(additional_properties, dict)
        for child in value.values():
            _assert_object_schemas_are_closed(child)
    elif isinstance(value, list):
        for child in value:
            _assert_object_schemas_are_closed(child)


class _TextResult(BaseModel):
    text: str


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
        _assert_object_schemas_are_closed(schema)
        serialized = json.dumps(schema).casefold()
        for forbidden_field in ("confirmed", "proposal", "effect", "replay"):
            assert f'"{forbidden_field}"' not in serialized

    with pytest.raises(ValidationError):
        await tools[0].call({"unexpected": True})


def test_workflow_get_requires_one_closed_source_pinned_selection(tmp_path: Path) -> None:
    dependencies = product_dispatch_dependencies(tmp_path)
    tools = build_operator_tools(
        settings=dependencies.settings,
        session_factory=_unexpected_session,
        dispatch_dependencies=dependencies,
    )
    input_model = next(
        tool.input_model for tool in tools if tool.name is OperatorToolName.WORKFLOW_GET
    )
    assert input_model is WorkflowGetInput

    catalog = WorkflowGetInput.model_validate(
        {
            "workflow_id": "reviewed-delivery",
            "selection": {
                "kind": "catalog",
                "revision_limit": 10,
            },
        }
    )
    published = WorkflowGetInput.model_validate(
        {
            "workflow_id": "reviewed-delivery",
            "selection": {
                "kind": "published",
                "revision_no": 1,
                "member_id": "lead",
            },
        }
    )
    draft = WorkflowGetInput.model_validate(
        {
            "workflow_id": "reviewed-delivery",
            "selection": {
                "kind": "draft",
                "draft_id": "workflow-draft.one",
                "etag": '"wd-current"',
                "member_id": "lead",
            },
        }
    )

    assert catalog.selection.kind == "catalog"
    assert published.selection.kind == "published"
    assert draft.selection.kind == "draft"
    for invalid in (
        {"workflow_id": "reviewed-delivery"},
        {
            "workflow_id": "reviewed-delivery",
            "revision_no": 1,
        },
        {
            "workflow_id": "reviewed-delivery",
            "selection": {"kind": "published"},
        },
        {
            "workflow_id": "reviewed-delivery",
            "selection": {
                "kind": "draft",
                "draft_id": "workflow-draft.one",
            },
        },
        {
            "workflow_id": "reviewed-delivery",
            "selection": {
                "kind": "catalog",
                "should_include_revisions": False,
                "revision_cursor": "workflow-revisions.cursor",
            },
        },
    ):
        with pytest.raises(ValidationError):
            WorkflowGetInput.model_validate(invalid)


def test_task_get_defaults_to_overview_and_requires_detail_identity() -> None:
    overview = TaskGetInput.model_validate({"task_id": "task.one"})
    member = TaskGetInput.model_validate(
        {
            "task_id": "task.one",
            "selection": {"kind": "member", "member_id": "member.one"},
        }
    )

    assert overview.selection.kind == "overview"
    assert member.selection.kind == "member"
    for invalid in (
        {"task_id": "task.one", "selection": {"kind": "member"}},
        {"task_id": "task.one", "selection": {"kind": "activity"}},
        {"task_id": "task.one", "selection": {"kind": "human_request"}},
        {
            "task_id": "task.one",
            "selection": {"kind": "result", "request_id": "request.one"},
        },
    ):
        with pytest.raises(ValidationError):
            TaskGetInput.model_validate(invalid)


async def test_result_guard_counts_compact_json_utf16_and_never_replays() -> None:
    compact_envelope_units = len('{"text":""}'.encode("utf-16-le")) // 2
    returned_text = "a" * (MAX_OPERATOR_TOOL_RESULT_UTF16_CODE_UNITS - compact_envelope_units)
    call_count = 0

    async def return_text(request: EmptyOperatorToolInput) -> _TextResult:
        nonlocal call_count
        del request
        call_count += 1
        return _TextResult(text=returned_text)

    tool = bind_operator_tool(
        name=OperatorToolName.WORKFLOW_SEARCH,
        description="Return a controlled result for the size boundary.",
        input_model=EmptyOperatorToolInput,
        handler=return_text,
    )

    assert await tool.call({}) == {"text": returned_text}
    returned_text = (
        "a" * (MAX_OPERATOR_TOOL_RESULT_UTF16_CODE_UNITS - compact_envelope_units - 1) + "😀"
    )
    with pytest.raises(OperatorToolResultTooLargeError) as caught:
        await tool.call({})

    assert call_count == 2
    assert returned_text not in str(caught.value)


async def test_largest_authored_member_projection_stays_below_result_guard() -> None:
    workflow_id = f"w{'a' * 127}"
    lead_id = "a" * 128
    child_ids = tuple(f"b{index:02d}{'a' * 125}" for index in range(32))
    workflow = normalize_workflow_object(
        {
            "kind": "workflow",
            "id": workflow_id,
            "description": "😀" * 1_024,
            "note": "😀" * 8_192,
            "lead": {
                "id": lead_id,
                "title": "😀" * 16_384,
                "description": "😀" * 16_384,
                "instruction": "😀" * 16_384,
                "provider": {
                    "kind": "codex",
                    "model": "😀" * 255,
                    "effort": "xhigh",
                    "sandbox": {
                        "mode": "full_access",
                        "network": "allow",
                    },
                },
                "capabilities": {
                    "human_request": ["input", "direction", "approval", "review"],
                    "command_run": "allow",
                },
                "children": [{"id": child_id} for child_id in child_ids],
            },
        }
    )
    projection = build_operator_workflow_member_result(
        workflow,
        source=OperatorPublishedWorkflowSource(
            workflow_id=workflow.id,
            revision_no=1,
        ),
        member_id=None,
    )

    async def return_projection(
        request: EmptyOperatorToolInput,
    ) -> OperatorWorkflowMemberResult:
        del request
        return projection

    tool = bind_operator_tool(
        name=OperatorToolName.WORKFLOW_GET,
        description="Return the maximum authored one-Member projection.",
        input_model=EmptyOperatorToolInput,
        handler=return_projection,
    )
    result = await tool.call({})
    serialized = json.dumps(
        result,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    assert result["member"]["child_ids"] == list(child_ids)
    assert set(result) == {"kind", "source", "workflow", "member"}
    assert set(result["workflow"]) == {
        "kind",
        "id",
        "description",
        "note",
        "lead_member_id",
    }
    assert "children" not in result["member"]
    assert len(serialized.encode("utf-16-le")) // 2 < (MAX_OPERATOR_TOOL_RESULT_UTF16_CODE_UNITS)


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


def test_full_json_workflow_enforces_raw_input_bound() -> None:
    maximum_prose = "x" * 16_384
    payload = {
        "kind": "workflow",
        "id": "oversize",
        "description": "Reject before draft creation.",
        "lead": {
            "id": "lead",
            "children": [
                {
                    "id": f"member-{index}",
                    "title": maximum_prose,
                    "description": maximum_prose,
                    "instruction": maximum_prose,
                }
                for index in range(32)
            ],
        },
    }

    with pytest.raises(ValidationError) as raised:
        WorkflowDraftCreateInput.model_validate({"workflow": payload})

    context = raised.value.errors()[0].get("ctx")
    assert context is not None
    cause = context["error"]
    assert isinstance(cause, WorkflowInputError)
    assert cause.issues[0].source == "input.size"


def test_workflow_projections_fail_closed_on_cross_source_identity() -> None:
    workflow = normalize_workflow_object(
        {
            "kind": "workflow",
            "id": "authored-id",
            "description": "Keep source identity exact.",
            "lead": {"id": "lead"},
        }
    )
    with pytest.raises(ValidationError, match="identities disagree"):
        build_operator_workflow_member_result(
            workflow,
            source=OperatorPublishedWorkflowSource(
                workflow_id="row-id",
                revision_no=1,
            ),
            member_id=None,
        )

    with pytest.raises(ValidationError, match="catalog source has the wrong identity"):
        OperatorWorkflowCatalogResult(
            workflow_id="catalog-id",
            description="Keep source identity exact.",
            state=WorkflowLibraryState.PUBLISHED,
            updated_at=datetime(2026, 7, 25, tzinfo=UTC),
            provenance=WorkflowProvenance.USER,
            available_actions=(
                WorkflowLibraryAction.EDIT,
                WorkflowLibraryAction.START_RUN,
            ),
            published=OperatorPublishedWorkflowSource(
                workflow_id="row-id",
                revision_no=1,
            ),
        )


def test_invalid_workflow_validation_receipt_preserves_issues_without_tree() -> None:
    workflow = normalize_workflow_object(
        {
            "kind": "workflow",
            "id": "validation-receipt",
            "description": "Project validation issues compactly.",
            "lead": {"id": "lead"},
        }
    )
    receipt = map_operator_workflow_draft_validation_receipt(
        WorkflowDraftValidationResult(
            draft=WorkflowDraftReadback(
                draft_id="workflow-draft.validation",
                workflow_id=workflow.id,
                etag='"wd-validation"',
                workflow=workflow,
            ),
            is_valid=False,
            issues=(
                WorkflowValidationIssue(
                    source="semantic.member_id",
                    path="$.lead.id",
                    message="Member ID is duplicated",
                ),
            ),
        )
    )
    payload = receipt.model_dump(mode="json")

    assert payload["is_valid"] is False
    assert payload["issues"] == [
        {
            "source": "semantic.member_id",
            "path": "$.lead.id",
            "message": "Member ID is duplicated",
        }
    ]
    assert "workflow" not in payload["draft"]


def test_member_projection_traverses_wide_deep_and_source_scoped_trees() -> None:
    next_member_number = 1
    wide_children: list[dict[str, object]] = []
    for group_index in range(31):
        group_id = f"member-{next_member_number}"
        next_member_number += 1
        leaf_count = 8 if group_index < 7 else 7
        leaves = [
            {"id": f"member-{member_number}"}
            for member_number in range(
                next_member_number,
                next_member_number + leaf_count,
            )
        ]
        next_member_number += leaf_count
        wide_children.append({"id": group_id, "children": leaves})

    wide = normalize_workflow_object(
        {
            "kind": "workflow",
            "id": "wide",
            "description": "Exercise the maximum Member count.",
            "lead": {
                "id": "member-0",
                "children": wide_children,
            },
        }
    )
    source = OperatorPublishedWorkflowSource(workflow_id="wide", revision_no=1)
    projected_ids = {
        build_operator_workflow_member_result(
            wide,
            source=source,
            member_id=f"member-{index}",
        ).member.id
        for index in range(256)
    }

    deep_member: dict[str, object] = {"id": "member-11"}
    for index in reversed(range(11)):
        deep_member = {"id": f"member-{index}", "children": [deep_member]}
    deep = normalize_workflow_object(
        {
            "kind": "workflow",
            "id": "deep",
            "description": "Exercise the maximum Member depth.",
            "lead": deep_member,
        }
    )
    deepest = build_operator_workflow_member_result(
        deep,
        source=OperatorPublishedWorkflowSource(workflow_id="deep", revision_no=1),
        member_id="member-11",
    )

    assert projected_ids == {f"member-{index}" for index in range(256)}
    assert deepest.member.id == "member-11"
    for workflow_id in ("first", "second"):
        scoped = normalize_workflow_object(
            {
                "kind": "workflow",
                "id": workflow_id,
                "description": f"{workflow_id} source",
                "lead": {"id": "shared-member", "title": workflow_id},
            }
        )
        selected = build_operator_workflow_member_result(
            scoped,
            source=OperatorPublishedWorkflowSource(
                workflow_id=workflow_id,
                revision_no=1,
            ),
            member_id="shared-member",
        )
        assert selected.member.title == workflow_id


def test_operator_prompt_is_byte_identical_to_its_canonical_appendix() -> None:
    appendix = (REPO_ROOT / "docs-internal/interfaces/operator-conversation-contract.md").read_text(
        encoding="utf-8"
    )
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
