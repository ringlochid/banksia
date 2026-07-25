from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from banksia.runtime.contracts import FileReference
from banksia.runtime.contracts.human_requests import HumanRequestItemAnswer
from banksia.runtime.contracts.refs import (
    reject_duplicate_file_references,
    validate_file_reference_limit,
)
from banksia.runtime.contracts.text import MAX_WORK_PROMPT_BYTES, normalize_exact_text
from banksia.workflows import DraftOperation
from banksia.workflows.authoring_contracts import WorkflowDraftOpenRequest
from banksia.workflows.contracts import Identifier


class OperationRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class WorkflowSearchOperationRequest(OperationRequest):
    query: str | None = None
    cursor: str | None = None
    limit: int = Field(default=50, ge=1, le=100)


class WorkflowGetOperationRequest(OperationRequest):
    workflow_id: str
    revision_no: int | None = Field(default=None, ge=1)
    should_include_revisions: bool = Field(default=True, alias="include_revisions")
    revision_cursor: str | None = None
    revision_limit: int = Field(default=20, ge=1, le=100)


class WorkflowAuthoringOptionsOperationRequest(OperationRequest):
    pass


class WorkflowDraftCreateOperationRequest(OperationRequest):
    request: WorkflowDraftOpenRequest


class WorkflowDraftEditOperationRequest(OperationRequest):
    draft_id: str
    etag: str
    operation: DraftOperation


class WorkflowDraftValidateOperationRequest(OperationRequest):
    draft_id: str


class WorkflowDraftUndoOperationRequest(OperationRequest):
    draft_id: str
    etag: str
    receipt_id: str


class WorkflowDraftDiscardOperationRequest(OperationRequest):
    draft_id: str
    etag: str


class WorkflowDraftPublishOperationRequest(OperationRequest):
    draft_id: str
    etag: str


class TaskSearchOperationRequest(OperationRequest):
    q: str | None = None
    status: str = "any"
    cursor: str | None = None
    limit: int = Field(default=50, ge=1, le=100)


class TaskGetOperationRequest(OperationRequest):
    task_id: str


class TaskStartOperationRequest(OperationRequest):
    workflow: Identifier
    prompt: str
    workspace: Path | None = None
    files: tuple[FileReference, ...] = ()

    @field_validator("prompt", mode="before")
    @classmethod
    def normalize_prompt(cls, value: object) -> str:
        return normalize_exact_text(
            value,
            label="task prompt",
            max_utf8_bytes=MAX_WORK_PROMPT_BYTES,
            is_nonblank_required=True,
        )

    @field_validator("files")
    @classmethod
    def validate_files(
        cls,
        files: tuple[FileReference, ...],
    ) -> tuple[FileReference, ...]:
        validate_file_reference_limit(files, label="task")
        return reject_duplicate_file_references(files, label="task")


class TaskControlOperationRequest(OperationRequest):
    task_id: str
    action_id: str


class OperatorHumanAnswerInput(OperationRequest):
    kind: Literal["answer"]
    item_responses: dict[str, HumanRequestItemAnswer] = Field(min_length=1, max_length=3)


class OperatorHumanCancelInput(OperationRequest):
    kind: Literal["cancel"]


OperatorHumanResponseInput = Annotated[
    OperatorHumanAnswerInput | OperatorHumanCancelInput,
    Field(discriminator="kind"),
]


class HumanRequestRespondOperationRequest(OperationRequest):
    task_id: str
    request_id: str
    action_id: str
    input: OperatorHumanResponseInput


class CommandRunGetOperationRequest(OperationRequest):
    task_id: str
    command_id: str


class CommandRunOutputReadOperationRequest(OperationRequest):
    task_id: str
    command_id: str
    cursor: str | None = None
    limit: int = Field(default=65_536, ge=1, le=65_536)


class CommandRunCancelOperationRequest(OperationRequest):
    task_id: str
    command_id: str
    action_id: str


__all__ = [
    "CommandRunCancelOperationRequest",
    "CommandRunGetOperationRequest",
    "CommandRunOutputReadOperationRequest",
    "HumanRequestRespondOperationRequest",
    "OperationRequest",
    "OperatorHumanAnswerInput",
    "OperatorHumanCancelInput",
    "OperatorHumanResponseInput",
    "TaskControlOperationRequest",
    "TaskGetOperationRequest",
    "TaskSearchOperationRequest",
    "TaskStartOperationRequest",
    "WorkflowAuthoringOptionsOperationRequest",
    "WorkflowDraftCreateOperationRequest",
    "WorkflowDraftDiscardOperationRequest",
    "WorkflowDraftEditOperationRequest",
    "WorkflowDraftPublishOperationRequest",
    "WorkflowDraftUndoOperationRequest",
    "WorkflowDraftValidateOperationRequest",
    "WorkflowGetOperationRequest",
    "WorkflowSearchOperationRequest",
]
