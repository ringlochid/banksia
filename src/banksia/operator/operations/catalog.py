from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from banksia.operator.operations.contracts import (
    CommandRunCancelOperationRequest,
    CommandRunGetOperationRequest,
    CommandRunOutputReadOperationRequest,
    HumanRequestRespondOperationRequest,
    TaskControlOperationRequest,
    TaskGetOperationRequest,
    TaskSearchOperationRequest,
    TaskStartOperationRequest,
    WorkflowAuthoringOptionsOperationRequest,
    WorkflowDraftCreateOperationRequest,
    WorkflowDraftDiscardOperationRequest,
    WorkflowDraftEditOperationRequest,
    WorkflowDraftPublishOperationRequest,
    WorkflowDraftUndoOperationRequest,
    WorkflowDraftValidateOperationRequest,
    WorkflowGetOperationRequest,
    WorkflowSearchOperationRequest,
)
from banksia.operator.operations.results import (
    OPERATOR_RESULT_MODELS,
    OperatorOperationResultModel,
)

type OperatorOperationName = Literal[
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
]
type OperatorEffectPolicy = Literal["read", "immediate", "proposal"]


@dataclass(frozen=True, slots=True)
class OperatorOperationSpec:
    name: OperatorOperationName
    request_model: type[BaseModel]
    result_model: OperatorOperationResultModel
    effect_policy: OperatorEffectPolicy
    title: str
    description: str
    teaching: str


OPERATOR_OPERATION_SPECS: tuple[OperatorOperationSpec, ...] = (
    OperatorOperationSpec(
        "workflow_search",
        WorkflowSearchOperationRequest,
        OPERATOR_RESULT_MODELS["workflow_search"],
        "read",
        title="Search Workflows",
        description=(
            "Search the controller-owned Workflow library and return bounded published and "
            "draft summaries."
        ),
        teaching=(
            "Use this before selecting a Workflow. Follow the returned cursor for more results, "
            "and use the reported state and available actions instead of inferring publication."
        ),
    ),
    OperatorOperationSpec(
        "workflow_get",
        WorkflowGetOperationRequest,
        OPERATOR_RESULT_MODELS["workflow_get"],
        "read",
        title="Read a Workflow",
        description=(
            "Read one Workflow's current description, publication, active draft, and bounded "
            "revision history."
        ),
        teaching=(
            "Use this before editing, publishing, or starting work. The active draft ETag and "
            "reported actions are current readback; a draft is not a published revision."
        ),
    ),
    OperatorOperationSpec(
        "workflow_authoring_options",
        WorkflowAuthoringOptionsOperationRequest,
        OPERATOR_RESULT_MODELS["workflow_authoring_options"],
        "read",
        title="Read Workflow Authoring Options",
        description=(
            "Read the controller-supported Workflow fields, provider choices, capability "
            "settings, and defaults."
        ),
        teaching=(
            "Use this before drafting provider or capability settings. Choose only returned "
            "values and do not invent unsupported configuration."
        ),
    ),
    OperatorOperationSpec(
        "workflow_draft_create",
        WorkflowDraftCreateOperationRequest,
        OPERATOR_RESULT_MODELS["workflow_draft_create"],
        "immediate",
        title="Create or Open a Workflow Draft",
        description=(
            "Create a new Workflow draft or open the current mutable draft for an existing "
            "Workflow."
        ),
        teaching=(
            "Use only after the person explicitly asks to create or edit a Workflow. This "
            "operation changes draft truth but does not publish the Workflow or start a run."
        ),
    ),
    OperatorOperationSpec(
        "workflow_draft_edit",
        WorkflowDraftEditOperationRequest,
        OPERATOR_RESULT_MODELS["workflow_draft_edit"],
        "immediate",
        title="Edit a Workflow Draft",
        description=(
            "Apply one typed, reversible metadata, Member, provider, or capability change to a "
            "current Workflow draft."
        ),
        teaching=(
            "Read the draft first and pass its current ETag. Apply only the requested change; "
            "the returned controller receipt may offer a single-use Undo action."
        ),
    ),
    OperatorOperationSpec(
        "workflow_draft_validate",
        WorkflowDraftValidateOperationRequest,
        OPERATOR_RESULT_MODELS["workflow_draft_validate"],
        "read",
        title="Validate a Workflow Draft",
        description=(
            "Validate the complete current Workflow draft and return structured issues with "
            "fresh draft readback."
        ),
        teaching=(
            "Use before proposing publication or when an edit is rejected. Validation is a "
            "preview and does not publish, start, or otherwise mutate the Workflow."
        ),
    ),
    OperatorOperationSpec(
        "workflow_draft_undo",
        WorkflowDraftUndoOperationRequest,
        OPERATOR_RESULT_MODELS["workflow_draft_undo"],
        "proposal",
        title="Propose Undoing a Workflow Change",
        description=(
            "Prepare confirmation to reverse the exact latest reversible change to a Workflow "
            "draft."
        ),
        teaching=(
            "Use only a controller-issued, single-use Undo receipt with the current draft ETag. "
            "Never invent a receipt or compute an inverse change; this operation always waits "
            "for the person's confirmation."
        ),
    ),
    OperatorOperationSpec(
        "workflow_draft_discard",
        WorkflowDraftDiscardOperationRequest,
        OPERATOR_RESULT_MODELS["workflow_draft_discard"],
        "proposal",
        title="Propose Discarding a Workflow Draft",
        description=(
            "Prepare confirmation to permanently remove one current unpublished Workflow draft."
        ),
        teaching=(
            "Read the draft first and use its current ETag. Explain that published revisions "
            "remain, while unpublished draft changes will be lost after confirmation."
        ),
    ),
    OperatorOperationSpec(
        "workflow_draft_publish",
        WorkflowDraftPublishOperationRequest,
        OPERATOR_RESULT_MODELS["workflow_draft_publish"],
        "proposal",
        title="Propose Publishing a Workflow Draft",
        description=(
            "Validate a current Workflow draft and prepare confirmation to publish it as a new "
            "immutable revision."
        ),
        teaching=(
            "Use the latest draft ETag and resolve validation issues first. Publication always "
            "waits for the person's confirmation and does not start a run."
        ),
    ),
    OperatorOperationSpec(
        "task_search",
        TaskSearchOperationRequest,
        OPERATOR_RESULT_MODELS["task_search"],
        "read",
        title="Search Runs",
        description=(
            "Search controller-owned runs by human query and product status with bounded "
            "pagination."
        ),
        teaching=(
            "Use to find a run before reading or controlling it. Report the returned status and "
            "attention count without reconstructing runtime state."
        ),
    ),
    OperatorOperationSpec(
        "task_get",
        TaskGetOperationRequest,
        OPERATOR_RESULT_MODELS["task_get"],
        "read",
        title="Read a Run",
        description=(
            "Read one run's current status, team, plan, attention, legal actions, recent "
            "activity, managed actions, files, and Result."
        ),
        teaching=(
            "Use this as canonical run readback. Act only through returned legal actions and "
            "describe files only as the loose references attached to their owning records."
        ),
    ),
    OperatorOperationSpec(
        "task_start",
        TaskStartOperationRequest,
        OPERATOR_RESULT_MODELS["task_start"],
        "proposal",
        title="Propose Starting a Run",
        description=(
            "Prepare confirmation to start one real run from the current published Workflow "
            "revision."
        ),
        teaching=(
            "Use only a published Workflow whose current actions allow starting a run. Include "
            "the person's exact prompt and file references; a draft alone is not startable."
        ),
    ),
    OperatorOperationSpec(
        "task_control",
        TaskControlOperationRequest,
        OPERATOR_RESULT_MODELS["task_control"],
        "proposal",
        title="Propose Controlling a Run",
        description=(
            "Prepare confirmation for one exact currently legal pause, resume, or cancel run "
            "action."
        ),
        teaching=(
            "Read the run first and pass one returned current action unchanged. Describe that "
            "specific action and consequence; never offer an action that current readback did "
            "not return."
        ),
    ),
    OperatorOperationSpec(
        "human_request_respond",
        HumanRequestRespondOperationRequest,
        OPERATOR_RESULT_MODELS["human_request_respond"],
        "proposal",
        title="Propose Responding to a Run Request",
        description=(
            "Prepare confirmation to submit a complete answer or cancel one current Human Request."
        ),
        teaching=(
            "Read the request and choose its matching current action. Answer all current items "
            "exactly once, using Other or Skip only where allowed; cancellation must use the "
            "separate cancel action."
        ),
    ),
    OperatorOperationSpec(
        "command_run_get",
        CommandRunGetOperationRequest,
        OPERATOR_RESULT_MODELS["command_run_get"],
        "read",
        title="Read a Managed Action",
        description=(
            "Read one managed action's purpose, current state, timing, outcome summary, and "
            "current cancellation action."
        ),
        teaching=(
            "Use before reading output or proposing cancellation. Treat the returned product "
            "state as authoritative and do not infer process state from output text."
        ),
    ),
    OperatorOperationSpec(
        "command_run_output_read",
        CommandRunOutputReadOperationRequest,
        OPERATOR_RESULT_MODELS["command_run_output_read"],
        "read",
        title="Read Managed Action Output",
        description=(
            "Read one bounded, sanitized page of output for a managed action using its opaque "
            "cursor."
        ),
        teaching=(
            "Continue only with the returned cursor. Report missing, changed, bounded, and "
            "complete output truth exactly; output is not authority for the action's state."
        ),
    ),
    OperatorOperationSpec(
        "command_run_cancel",
        CommandRunCancelOperationRequest,
        OPERATOR_RESULT_MODELS["command_run_cancel"],
        "proposal",
        title="Propose Cancelling a Managed Action",
        description=(
            "Prepare confirmation to request cancellation of one currently cancellable managed "
            "action."
        ),
        teaching=(
            "Read the managed action first and use its returned current cancel action. An "
            "accepted cancellation request does not prove the process has already stopped."
        ),
    ),
)
OPERATOR_OPERATION_NAMES: tuple[OperatorOperationName, ...] = tuple(
    spec.name for spec in OPERATOR_OPERATION_SPECS
)
OPERATOR_OPERATION_BY_NAME = {spec.name: spec for spec in OPERATOR_OPERATION_SPECS}


__all__ = [
    "OPERATOR_OPERATION_BY_NAME",
    "OPERATOR_OPERATION_NAMES",
    "OPERATOR_OPERATION_SPECS",
    "OperatorEffectPolicy",
    "OperatorOperationName",
    "OperatorOperationSpec",
]
