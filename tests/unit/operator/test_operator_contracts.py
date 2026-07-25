from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from banksia.operator.contracts import (
    OPERATOR_LEGAL_ACTION_ADAPTER,
    OperatorProviderAskUserResult,
    OperatorProviderQuestion,
)
from banksia.operator.operations import (
    OPERATOR_OPERATION_NAMES,
    OPERATOR_OPERATION_SPECS,
)
from banksia.operator.operations.descriptions import describe_task_control
from banksia.operator.operations.executor import OPERATOR_TOOL_RESULT_ADAPTER
from banksia.operator.prompt import read_operator_system_prompt
from banksia.runtime.contracts.task import (
    ProductAction,
    ProductActionConfirmation,
    TaskMemberView,
    TaskView,
    TaskWorkflowView,
)


def test_operator_catalog_is_the_exact_closed_seventeen_operation_ceiling() -> None:
    assert OPERATOR_OPERATION_NAMES == (
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
    assert {spec.name for spec in OPERATOR_OPERATION_SPECS if spec.effect_policy == "proposal"} == {
        "workflow_draft_undo",
        "workflow_draft_discard",
        "workflow_draft_publish",
        "task_start",
        "task_control",
        "human_request_respond",
        "command_run_cancel",
    }


def test_operator_catalog_has_bounded_provider_neutral_tool_teaching() -> None:
    assert len({spec.title for spec in OPERATOR_OPERATION_SPECS}) == 17
    assert all(
        spec.title.strip() == spec.title
        and "_" not in spec.title
        and 3 <= len(spec.title) <= 80
        and 20 <= len(spec.description) <= 240
        and 20 <= len(spec.teaching) <= 500
        for spec in OPERATOR_OPERATION_SPECS
    )
    teaching_by_name = {
        spec.name: f"{spec.description} {spec.teaching}".casefold()
        for spec in OPERATOR_OPERATION_SPECS
    }
    assert "published" in teaching_by_name["task_start"]
    assert "controller-issued" in teaching_by_name["workflow_draft_undo"]
    assert "current action" in teaching_by_name["task_control"]
    assert "all current items" in teaching_by_name["human_request_respond"]
    assert "does not prove" in teaching_by_name["command_run_cancel"]
    assert not any(
        forbidden in teaching
        for teaching in teaching_by_name.values()
        for forbidden in ("artifact_get", "file_get", "support api", "external mcp")
    )


@pytest.mark.parametrize(
    ("kind", "label", "consequence"),
    (
        (
            "pause",
            "Pause run",
            "Banksia will stop opening new work until the run is resumed.",
        ),
        (
            "resume",
            "Resume run",
            "Banksia will reopen currently runnable work.",
        ),
        (
            "cancel",
            "Cancel run",
            "Banksia will cancel unfinished work and close open waits.",
        ),
    ),
)
def test_task_control_copy_names_each_exact_current_action(
    kind: str,
    label: str,
    consequence: str,
) -> None:
    now = datetime(2026, 7, 25, tzinfo=UTC)
    task = TaskView(
        id="opaque-task-id",
        prompt_excerpt="Prepare the nontechnical review",
        workflow=TaskWorkflowView(
            id="opaque-workflow-id",
            description="Reviewed delivery",
        ),
        status="working",
        status_message="The run is working.",
        started_at=now,
        updated_at=now,
        team=TaskMemberView(
            id="opaque-member-id",
            name="Lead",
            state="working",
        ),
        activities_href="/not-used",
    )
    action = ProductAction(
        id=f"opaque-{kind}-action-id",
        kind=kind,
        label=label,
        href="/not-used",
        confirmation=ProductActionConfirmation(
            is_required=True,
            title=f"{label}?",
            consequence=consequence,
        ),
    )

    copy = describe_task_control(task, action)

    assert copy == (
        label,
        "Run “Prepare the nontechnical review” using Workflow “Reviewed delivery”",
        consequence,
    )
    assert "opaque-" not in " ".join(copy)


def test_guarded_operation_schemas_do_not_expose_model_confirmation() -> None:
    proposal_schemas = (
        spec.request_model.model_json_schema()
        for spec in OPERATOR_OPERATION_SPECS
        if spec.effect_policy == "proposal"
    )
    assert all("confirmed" not in json.dumps(schema).casefold() for schema in proposal_schemas)


def test_operation_catalog_closes_every_request_and_result_contract() -> None:
    expected_models = {
        "workflow_search": ("WorkflowSearchOperationRequest", "WorkflowSearchResponse"),
        "workflow_get": ("WorkflowGetOperationRequest", "WorkflowGetResponse"),
        "workflow_authoring_options": (
            "WorkflowAuthoringOptionsOperationRequest",
            "WorkflowAuthoringOptions",
        ),
        "workflow_draft_create": (
            "WorkflowDraftCreateOperationRequest",
            "WorkflowDraftOpenResult",
        ),
        "workflow_draft_edit": (
            "WorkflowDraftEditOperationRequest",
            "WorkflowDraftMutationResult",
        ),
        "workflow_draft_validate": (
            "WorkflowDraftValidateOperationRequest",
            "WorkflowDraftValidationResult",
        ),
        "workflow_draft_undo": (
            "WorkflowDraftUndoOperationRequest",
            "WorkflowDraftReadback",
        ),
        "workflow_draft_discard": (
            "WorkflowDraftDiscardOperationRequest",
            "WorkflowDraftDiscardResult",
        ),
        "workflow_draft_publish": (
            "WorkflowDraftPublishOperationRequest",
            "WorkflowPublishedReadback",
        ),
        "task_search": ("TaskSearchOperationRequest", "TaskSearchResponse"),
        "task_get": ("TaskGetOperationRequest", "TaskView"),
        "task_start": ("TaskStartOperationRequest", "TaskStartReceipt"),
        "task_control": ("TaskControlOperationRequest", "TaskControlReceipt"),
        "human_request_respond": (
            "HumanRequestRespondOperationRequest",
            "HumanRequestResponseReceipt",
        ),
        "command_run_get": ("CommandRunGetOperationRequest", "CommandRunView"),
        "command_run_output_read": (
            "CommandRunOutputReadOperationRequest",
            "CommandRunOutputPage",
        ),
        "command_run_cancel": (
            "CommandRunCancelOperationRequest",
            "CommandRunCancelReceipt",
        ),
    }

    assert {
        spec.name: (spec.request_model.__name__, spec.result_model.__name__)
        for spec in OPERATOR_OPERATION_SPECS
    } == expected_models
    assert all(
        spec.request_model.model_config.get("extra") == "forbid"
        and spec.result_model.model_config.get("extra") == "forbid"
        for spec in OPERATOR_OPERATION_SPECS
    )


def test_legal_actions_and_tool_results_reject_cross_variant_field_bags() -> None:
    with pytest.raises(ValidationError):
        OPERATOR_LEGAL_ACTION_ADAPTER.validate_python(
            {
                "kind": "send_message",
                "label": "Send",
                "href": "/messages",
                "requires_confirmation": False,
                "input": {"kind": "message_text"},
                "confirmation_id": "not-legal-for-send",
            }
        )
    with pytest.raises(ValidationError):
        OPERATOR_TOOL_RESULT_ADAPTER.validate_python(
            {
                "kind": "result",
                "result": {},
                "problem": "cannot-mix-success-and-failure",
            }
        )
    with pytest.raises(ValidationError):
        OPERATOR_TOOL_RESULT_ADAPTER.validate_python(
            {
                "kind": "proposal",
                "confirmation_id": "confirm",
                "label": "Apply",
                "scope": "resource",
            }
        )


def test_operator_prompt_is_the_frozen_controller_owned_asset() -> None:
    prompt = read_operator_system_prompt()

    assert prompt.startswith(
        "You are Banksia Operator, the control-plane teammate who helps a person design,\n"
    )
    assert "Use only the Banksia product operations you are given." in prompt
    assert "do not\nattempt to confirm your own request." in prompt
    assert prompt.endswith("result.\n")


def test_provider_question_contract_is_closed_bounded_and_browser_safe() -> None:
    question = OperatorProviderQuestion.model_validate(
        {
            "header": "Direction",
            "question": "Which direction should the draft take?",
            "options": [
                {"label": "Concise", "consequence": "Keep the draft short."},
                {"label": "Detailed", "consequence": "Add implementation detail."},
            ],
        }
    )

    assert question.model_dump()["allow_skip"] is False
    assert "is_skip_allowed" not in question.model_dump()

    with pytest.raises(ValidationError):
        OperatorProviderQuestion.model_validate(
            {
                "header": "Direction",
                "question": "Which direction should the draft take?",
                "options": [
                    {"label": "Concise", "consequence": "Keep the draft short."},
                    {
                        "label": "Something else",
                        "consequence": "The browser owns this choice.",
                    },
                ],
            }
        )
    with pytest.raises(ValidationError):
        OperatorProviderQuestion.model_validate(
            {
                "header": "Direction",
                "question": "Which direction should the draft take?",
                "options": [{"label": "Only", "consequence": "There is no real choice."}],
                "provider_question_id": "provider-must-not-allocate-ids",
            }
        )


def test_provider_result_accepts_one_to_three_questions_only() -> None:
    question = {
        "header": "Direction",
        "question": "Which direction should the draft take?",
        "options": [
            {"label": "Concise", "consequence": "Keep the draft short."},
            {"label": "Detailed", "consequence": "Add implementation detail."},
        ],
    }

    for count in (1, 2, 3):
        result = OperatorProviderAskUserResult.model_validate(
            {"kind": "ask_user", "questions": [question] * count}
        )
        assert len(result.questions) == count
    for count in (0, 4):
        with pytest.raises(ValidationError):
            OperatorProviderAskUserResult.model_validate(
                {"kind": "ask_user", "questions": [question] * count}
            )
