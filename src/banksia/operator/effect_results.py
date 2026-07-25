from __future__ import annotations

from banksia.operator.operations.executor import (
    OperatorToolFailureResult,
    OperatorToolProposalResult,
    OperatorToolResult,
    OperatorToolSuccessResult,
)
from banksia.operator.storage import (
    allocate_operator_id,
    digest_operator_request,
    model_payload,
)
from banksia.persistence.models import OperatorEffectModel


def build_immediate_effect_outcome(
    *,
    effect: OperatorEffectModel,
    result: dict[str, object] | None,
    failure_problem: str | None,
) -> tuple[OperatorToolResult, dict[str, object]]:
    if failure_problem is not None or result is None:
        return (
            OperatorToolFailureResult(problem=failure_problem or "operator_operation_failed"),
            {"summary": ("Banksia could not apply the requested reversible draft change.")},
        )
    return (
        OperatorToolSuccessResult(result=result),
        {
            "summary": effect_success_summary(effect.operation),
            **effect_resource(effect.operation, result),
        },
    )


def create_edit_undo_effect(
    *,
    effect: OperatorEffectModel,
    result: dict[str, object] | None,
    receipt_body: dict[str, object],
) -> OperatorEffectModel | None:
    if effect.operation != "workflow_draft_edit" or result is None:
        return None
    draft = result.get("draft")
    receipt_id = result.get("undo_receipt")
    if not isinstance(draft, dict) or not isinstance(receipt_id, str):
        return None
    draft_id = draft.get("draft_id")
    etag = draft.get("etag")
    if not isinstance(draft_id, str) or not isinstance(etag, str):
        return None
    confirmation_id = allocate_operator_id("confirm")
    request = {
        "draft_id": draft_id,
        "etag": etag,
        "receipt_id": receipt_id,
    }
    label = "Undo the Workflow draft edit"
    resource_scope = f"Workflow draft {draft_id} at ETag {etag}"
    consequence = "The exact reversible draft edit will be undone."
    receipt_body["undo"] = {
        "confirmation_id": confirmation_id,
        "label": label,
        "scope": resource_scope,
        "consequence": consequence,
    }
    proposal = OperatorToolProposalResult(
        confirmation_id=confirmation_id,
        label=label,
        scope=resource_scope,
        consequence=consequence,
    )
    return OperatorEffectModel(
        effect_id=allocate_operator_id("effect"),
        conversation_id=effect.conversation_id,
        invocation_id=effect.invocation_id,
        provider_call_id=f"controller_undo:{effect.provider_call_id}",
        operation="workflow_draft_undo",
        request_json=request,
        request_digest=digest_operator_request(
            "workflow_draft_undo",
            f"controller_undo:{effect.provider_call_id}",
            request,
        ),
        action_guard=etag,
        state="proposed",
        confirmation_id=confirmation_id,
        confirmation_state="available",
        result_json=model_payload(proposal),
    )


def effect_success_summary(operation: str) -> str:
    summaries = {
        "workflow_draft_create": "The Workflow draft is ready.",
        "workflow_draft_edit": "The Workflow draft change was saved.",
        "workflow_draft_undo": "The Workflow draft edit was undone.",
        "workflow_draft_discard": "The Workflow draft was discarded.",
        "workflow_draft_publish": "The Workflow revision was published.",
        "task_start": "The run was accepted and will start asynchronously.",
        "task_control": "The run control was accepted.",
        "human_request_respond": "The response was saved and continuation is pending.",
        "command_run_cancel": "Cancellation was requested for the managed action.",
    }
    return summaries.get(operation, "The requested action completed.")


def effect_resource(
    operation: str,
    result: dict[str, object],
) -> dict[str, object]:
    if operation.startswith("workflow_draft_"):
        draft = result.get("draft")
        if isinstance(draft, dict) and isinstance(draft.get("draft_id"), str):
            return {
                "resource": {
                    "label": "Open Workflow draft",
                    "href": f"/api/workflow-drafts/{draft['draft_id']}",
                }
            }
        workflow_id = result.get("workflow_id")
        if isinstance(workflow_id, str):
            return {
                "resource": {
                    "label": "Open Workflow",
                    "href": f"/api/workflows/{workflow_id}",
                }
            }
    task_id = result.get("task_id")
    if isinstance(task_id, str):
        return {
            "resource": {
                "label": "Open run",
                "href": f"/api/tasks/{task_id}",
            }
        }
    return {}


__all__ = [
    "build_immediate_effect_outcome",
    "create_edit_undo_effect",
    "effect_resource",
    "effect_success_summary",
]
