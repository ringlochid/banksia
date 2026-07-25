from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from banksia.runtime.contracts.task import (
    CommandRunCancelReceipt,
    CommandRunOutputPage,
    CommandRunView,
    HumanRequestResponseReceipt,
    TaskControlReceipt,
    TaskSearchResponse,
    TaskStartReceipt,
    TaskView,
)
from banksia.workflows.authoring_contracts import (
    WorkflowAuthoringOptions,
    WorkflowDraftMutationResult,
    WorkflowDraftOpenResult,
    WorkflowDraftReadback,
    WorkflowDraftValidationResult,
    WorkflowGetResponse,
    WorkflowPublishedReadback,
    WorkflowSearchResponse,
)


class WorkflowDraftDiscardResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    discarded: Literal[True]
    draft_id: str


type OperatorOperationResultModel = type[BaseModel]


OPERATOR_RESULT_MODELS: dict[str, OperatorOperationResultModel] = {
    "workflow_search": WorkflowSearchResponse,
    "workflow_get": WorkflowGetResponse,
    "workflow_authoring_options": WorkflowAuthoringOptions,
    "workflow_draft_create": WorkflowDraftOpenResult,
    "workflow_draft_edit": WorkflowDraftMutationResult,
    "workflow_draft_validate": WorkflowDraftValidationResult,
    "workflow_draft_undo": WorkflowDraftReadback,
    "workflow_draft_discard": WorkflowDraftDiscardResult,
    "workflow_draft_publish": WorkflowPublishedReadback,
    "task_search": TaskSearchResponse,
    "task_get": TaskView,
    "task_start": TaskStartReceipt,
    "task_control": TaskControlReceipt,
    "human_request_respond": HumanRequestResponseReceipt,
    "command_run_get": CommandRunView,
    "command_run_output_read": CommandRunOutputPage,
    "command_run_cancel": CommandRunCancelReceipt,
}


__all__ = [
    "OPERATOR_RESULT_MODELS",
    "OperatorOperationResultModel",
    "WorkflowDraftDiscardResult",
]
