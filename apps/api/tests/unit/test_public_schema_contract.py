from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from autoclaw.definitions.contracts import (
    DefinitionKind,
    DefinitionListQuery,
    DefinitionRevisionDetailResponse,
    DefinitionRevisionHistoryQuery,
    DefinitionSummaryListResponse,
    DefinitionUploadRequest,
    PolicyCapabilitiesInput,
    RoleDefinitionInput,
    WorkflowDefinitionInput,
)
from autoclaw.runtime import FlowStatus
from autoclaw.runtime.contracts import (
    RuntimeFlowSummary,
    RuntimeLifecycleStatus,
    RuntimeTaskListQuery,
    TaskStartRequest,
    TaskStartResponse,
    WorkflowManifestRef,
)
from pydantic import ValidationError

from tests.unit.definition_schemas.support import bounded_workflow_payload


def test_definition_upload_request_requires_kind_to_match_content() -> None:
    request = DefinitionUploadRequest.model_validate(
        {
            "kind": "role",
            "content": {
                "id": "reviewer",
                "title": "Reviewer",
                "description": "Ordinary review worker.",
                "allowed_node_kinds": ["worker"],
                "instruction": "Review the bounded patch and report evidence only.",
            },
        }
    )

    assert request.kind == DefinitionKind.ROLE
    assert isinstance(request.content, RoleDefinitionInput)

    with pytest.raises(ValidationError, match="does not match content type 'workflow'"):
        DefinitionUploadRequest.model_validate(
            {
                "kind": "policy",
                "content": bounded_workflow_payload(),
            }
        )


def test_definition_upload_request_enforces_target_workflow_node_contract() -> None:
    payload = bounded_workflow_payload()
    request = DefinitionUploadRequest.model_validate({"kind": "workflow", "content": payload})

    assert isinstance(request.content, WorkflowDefinitionInput)
    assert request.content.root.node_key == "root"

    legacy_payload = deepcopy(payload)
    legacy_child = legacy_payload["root"]["children"][0]
    legacy_child["id"] = legacy_child.pop("node_key")
    with pytest.raises(ValidationError, match="id"):
        DefinitionUploadRequest.model_validate({"kind": "workflow", "content": legacy_payload})

    missing_policy_payload = deepcopy(payload)
    missing_policy_payload["root"]["children"][0].pop("policy_id")
    with pytest.raises(ValidationError, match="policy_id"):
        DefinitionUploadRequest.model_validate(
            {"kind": "workflow", "content": missing_policy_payload}
        )

    scalar_provider_payload = deepcopy(payload)
    scalar_provider_payload["root"]["children"][0]["provider"] = "codex"
    with pytest.raises(ValidationError, match="provider"):
        DefinitionUploadRequest.model_validate(
            {"kind": "workflow", "content": scalar_provider_payload}
        )

    invalid_provider_payload = deepcopy(payload)
    invalid_provider_payload["root"]["children"][0]["provider"] = {
        "kind": "codex",
        "model": "gpt-5",
    }
    with pytest.raises(ValidationError, match=r"provider|model"):
        DefinitionUploadRequest.model_validate(
            {"kind": "workflow", "content": invalid_provider_payload}
        )


def test_definition_list_query_rejects_both_route_specific_filters() -> None:
    query = DefinitionListQuery.model_validate({})

    assert query.limit == 50
    assert query.sort.value == "updated_at_desc"

    with pytest.raises(ValidationError, match="cannot be combined"):
        DefinitionListQuery.model_validate(
            {
                "allowed_node_kind": "worker",
                "applies_to": "worker",
            }
        )


def test_definition_summary_list_response_enforces_kind_specific_fields() -> None:
    timestamp = datetime.now(UTC)

    response = DefinitionSummaryListResponse.model_validate(
        {
            "kind": "role",
            "items": [
                {
                    "key": "reviewer",
                    "title": "Reviewer",
                    "description": "Ordinary review worker.",
                    "current_revision_no": 3,
                    "allowed_node_kinds": ["worker"],
                    "labels": ["review"],
                    "updated_at": timestamp,
                }
            ],
        }
    )

    assert response.kind == DefinitionKind.ROLE
    assert response.items[0].title == "Reviewer"
    assert response.items[0].allowed_node_kinds == ("worker",)
    assert response.items[0].labels == ("review",)

    with pytest.raises(ValidationError, match="workflow summaries must not expose"):
        DefinitionSummaryListResponse.model_validate(
            {
                "kind": "workflow",
                "items": [
                    {
                        "key": "reviewed-change-release",
                        "description": "Normal launch workflow.",
                        "current_revision_no": 2,
                        "allowed_node_kinds": ["root"],
                        "updated_at": timestamp,
                    }
                ],
            }
        )

    existing_response = DefinitionSummaryListResponse.model_validate(
        {
            "kind": "role",
            "items": [
                {
                    "key": "reviewer",
                    "description": "Existing review worker.",
                    "current_revision_no": 3,
                    "allowed_node_kinds": ["worker"],
                    "updated_at": timestamp,
                }
            ],
        }
    )
    assert existing_response.items[0].title is None


def test_definition_revision_detail_response_requires_key_to_match_content_id() -> None:
    timestamp = datetime.now(UTC)

    detail = DefinitionRevisionDetailResponse.model_validate(
        {
            "key": "reviewer",
            "revision_no": 2,
            "content": {
                "id": "reviewer",
                "title": "Reviewer",
                "description": "Ordinary review worker.",
                "allowed_node_kinds": ["worker"],
            },
            "updated_at": timestamp,
        }
    )

    assert detail.content.id == "reviewer"

    with pytest.raises(ValidationError, match=r"key must match content\.id"):
        DefinitionRevisionDetailResponse.model_validate(
            {
                "key": "reviewer",
                "revision_no": 2,
                "content": {
                    "id": "planner",
                    "title": "Planner",
                    "description": "Planning lead.",
                    "allowed_node_kinds": ["root", "parent"],
                },
                "updated_at": timestamp,
            }
        )


def test_policy_capabilities_have_a_typed_serialization_schema() -> None:
    schema = PolicyCapabilitiesInput.model_json_schema(mode="serialization")
    output_schema = schema["$defs"]["PolicyCapabilitiesOutput"]

    assert output_schema.get("additionalProperties") is not True
    assert set(output_schema["properties"]) == {
        "provider_native_access",
        "network_access",
        "human_request",
        "command_run",
    }
    assert set(output_schema["required"]) == {"human_request", "command_run"}


def test_runtime_task_list_uses_v2_lifecycle_statuses() -> None:
    query = RuntimeTaskListQuery(status="completed")
    summary = RuntimeFlowSummary(
        task_id="task.completed",
        task_title="Completed task",
        task_summary="Use the V2 lifecycle status vocabulary.",
        status=RuntimeLifecycleStatus.COMPLETED,
        active_flow_revision_id="flow-revision.completed.1",
        workflow_manifest_ref=WorkflowManifestRef(
            path=Path("_runtime/workflow-manifest.md"),
            description="Whole-workflow visible contract for the current task.",
        ),
        active_assignment_id="assignment.completed",
        active_attempt_id="attempt.completed",
        updated_at=datetime.now(UTC),
    )

    assert query.status == "completed"
    assert summary.status == RuntimeLifecycleStatus.COMPLETED
    with pytest.raises(ValidationError):
        RuntimeTaskListQuery.model_validate({"status": "succeeded"})


def test_definition_revision_history_query_uses_canonical_defaults() -> None:
    query = DefinitionRevisionHistoryQuery.model_validate({})

    assert query.limit == 50
    assert query.sort.value == "revision_no_desc"
    assert query.cursor is None


def test_task_start_request_accepts_minimal_body_and_rejects_unsupported_fields() -> None:
    request = TaskStartRequest.model_validate(
        {
            "task": {
                "key": "auth-refresh-hardening",
                "title": "Harden auth refresh flow",
                "summary": "Investigate and fix the auth refresh regression.",
            },
            "workflow": {"key": "reviewed-change-release"},
        }
    )

    assert request.task.key == "auth-refresh-hardening"
    assert request.roots is None

    with pytest.raises(ValidationError):
        TaskStartRequest.model_validate(
            {
                "task": {
                    "key": "auth-refresh-hardening",
                    "title": "Harden auth refresh flow",
                    "summary": "Investigate and fix the auth refresh regression.",
                },
                "workflow": {"key": "reviewed-change-release"},
                "roots": {
                    "outputs": {
                        "mode": "ensure_task_default",
                    }
                },
            }
        )

    with pytest.raises(ValidationError):
        TaskStartRequest.model_validate(
            {
                "task": {
                    "key": "auth-refresh-hardening",
                    "title": "Harden auth refresh flow",
                    "summary": "Investigate and fix the auth refresh regression.",
                },
                "workflow": {"key": "reviewed-change-release"},
                "initial_assignment": {
                    "summary": "This field is not part of the public task-start contract.",
                },
            }
        )


def test_task_start_response_uses_the_canonical_public_fields() -> None:
    response = TaskStartResponse(
        task_id="task.auth-refresh-hardening",
        compiled_plan_id="compiled-plan.auth-refresh-hardening",
        active_flow_revision_id="flow-revision.auth-refresh-hardening.001",
        flow_status=FlowStatus.RUNNING,
        workflow_manifest_ref=WorkflowManifestRef(
            path=Path("/tmp/task/_runtime/workflow-manifest.json"),
            description="Whole-workflow visible contract for the current task.",
        ),
    )

    dumped = response.model_dump(mode="json")

    assert set(dumped) == {
        "task_id",
        "compiled_plan_id",
        "active_flow_revision_id",
        "flow_status",
        "workflow_manifest_ref",
    }
    assert "dispatch_id" not in dumped
    assert "flow_id" not in dumped
