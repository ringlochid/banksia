from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from banksia.runtime.contracts.common import RuntimeSchemaText
from banksia.runtime.contracts.human_requests import HumanRequestItemAnswer
from banksia.runtime.contracts.primitives import TaskIdentifier
from banksia.runtime.contracts.task import HumanRequestAnswerInput
from banksia.workflows.contracts import Identifier, NormalizedWorkflow
from banksia.workflows.ingest import normalize_workflow_object
from banksia.workflows.operations import DraftOperation

RequestT = TypeVar("RequestT", bound=BaseModel)
ResultT = TypeVar("ResultT", bound=BaseModel)
OperatorToolHandler = Callable[[BaseModel], Awaitable[BaseModel]]
type OperatorToolResult = dict[str, Any]
type TaskSearchStatus = Literal[
    "any",
    "starting",
    "working",
    "waiting_for_you",
    "paused",
    "completed",
    "blocked",
    "cancelled",
]


class OperatorToolName(StrEnum):
    WORKFLOW_SEARCH = "workflow_search"
    WORKFLOW_GET = "workflow_get"
    WORKFLOW_AUTHORING_OPTIONS = "workflow_authoring_options"
    WORKFLOW_DRAFT_CREATE = "workflow_draft_create"
    WORKFLOW_DRAFT_EDIT = "workflow_draft_edit"
    WORKFLOW_DRAFT_VALIDATE = "workflow_draft_validate"
    WORKFLOW_DRAFT_UNDO = "workflow_draft_undo"
    WORKFLOW_DRAFT_DISCARD = "workflow_draft_discard"
    WORKFLOW_DRAFT_PUBLISH = "workflow_draft_publish"
    TASK_SEARCH = "task_search"
    TASK_GET = "task_get"
    TASK_START = "task_start"
    TASK_CONTROL = "task_control"
    HUMAN_REQUEST_RESPOND = "human_request_respond"
    COMMAND_RUN_GET = "command_run_get"
    COMMAND_RUN_OUTPUT_READ = "command_run_output_read"
    COMMAND_RUN_CANCEL = "command_run_cancel"


@dataclass(frozen=True, slots=True)
class OperatorTool:
    """One direct, typed Banksia product operation bound to its owner service."""

    name: OperatorToolName
    description: str
    input_model: type[BaseModel]
    handler: OperatorToolHandler

    @property
    def input_schema(self) -> dict[str, Any]:
        schema = self.input_model.model_json_schema(by_alias=True)
        if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            raise ValueError(f"Operator tool {self.name!r} requires a closed object schema")
        return schema

    async def call(self, arguments: object) -> OperatorToolResult:
        request = self.input_model.model_validate(arguments)
        result = await self.handler(request)
        return result.model_dump(mode="json", by_alias=True)


class OperatorToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EmptyOperatorToolInput(OperatorToolInput):
    pass


class WorkflowSearchInput(OperatorToolInput):
    query: str | None = None
    cursor: str | None = None
    limit: Annotated[int, Field(ge=1, le=100)] = 50


class WorkflowGetInput(OperatorToolInput):
    workflow_id: Identifier
    revision_no: Annotated[int, Field(ge=1)] | None = None
    should_include_revisions: bool = True
    revision_cursor: str | None = None
    revision_limit: Annotated[int, Field(ge=1, le=100)] = 20


class WorkflowDraftCreateInput(OperatorToolInput):
    workflow: NormalizedWorkflow
    etag: RuntimeSchemaText | None = None

    @field_validator("workflow", mode="before")
    @classmethod
    def normalize_complete_workflow(cls, value: object) -> NormalizedWorkflow:
        return normalize_workflow_object(value)


class WorkflowDraftEditInput(OperatorToolInput):
    draft_id: RuntimeSchemaText
    etag: RuntimeSchemaText
    operation: DraftOperation


class WorkflowDraftValidateInput(OperatorToolInput):
    draft_id: RuntimeSchemaText


class WorkflowDraftUndoInput(OperatorToolInput):
    draft_id: RuntimeSchemaText
    etag: RuntimeSchemaText
    receipt_id: RuntimeSchemaText


class WorkflowDraftMutationInput(OperatorToolInput):
    draft_id: RuntimeSchemaText
    etag: RuntimeSchemaText


class TaskSearchInput(OperatorToolInput):
    query: str | None = None
    status: TaskSearchStatus = "any"
    cursor: str | None = None
    limit: Annotated[int, Field(ge=1, le=100)] = 50


class TaskGetInput(OperatorToolInput):
    task_id: TaskIdentifier


class TaskControlInput(OperatorToolInput):
    task_id: TaskIdentifier
    action_id: RuntimeSchemaText


class OperatorHumanRequestCancelInput(OperatorToolInput):
    kind: Literal["cancel"]


type OperatorHumanRequestResponseInput = Annotated[
    HumanRequestAnswerInput | OperatorHumanRequestCancelInput,
    Field(discriminator="kind"),
]


class HumanRequestRespondInput(OperatorToolInput):
    task_id: TaskIdentifier
    request_id: RuntimeSchemaText
    action_id: RuntimeSchemaText
    input: OperatorHumanRequestResponseInput


class CommandRunGetInput(OperatorToolInput):
    task_id: TaskIdentifier
    command_id: RuntimeSchemaText


class CommandRunOutputReadInput(CommandRunGetInput):
    cursor: str | None = None
    limit: Annotated[int, Field(ge=1, le=65_536)] = 65_536


class CommandRunCancelInput(CommandRunGetInput):
    action_id: RuntimeSchemaText


for _operator_tool_model in (
    WorkflowDraftEditInput,
    HumanRequestRespondInput,
):
    _operator_tool_model.model_rebuild(
        _types_namespace={
            **globals(),
            "HumanRequestItemAnswer": HumanRequestItemAnswer,
        }
    )


def bind_operator_tool(
    *,
    name: OperatorToolName,
    description: str,
    input_model: type[RequestT],
    handler: Callable[[RequestT], Awaitable[ResultT]],
) -> OperatorTool:
    async def bound_handler(request: BaseModel) -> BaseModel:
        if not isinstance(request, input_model):  # pragma: no cover - call validates first
            raise TypeError(f"Operator tool {name!r} received the wrong request model")
        return await handler(request)

    return OperatorTool(
        name=name,
        description=description,
        input_model=input_model,
        handler=bound_handler,
    )


__all__ = [
    "CommandRunCancelInput",
    "CommandRunGetInput",
    "CommandRunOutputReadInput",
    "EmptyOperatorToolInput",
    "HumanRequestRespondInput",
    "OperatorHumanRequestCancelInput",
    "OperatorHumanRequestResponseInput",
    "OperatorTool",
    "OperatorToolInput",
    "OperatorToolName",
    "OperatorToolResult",
    "TaskControlInput",
    "TaskGetInput",
    "TaskSearchInput",
    "TaskSearchStatus",
    "WorkflowDraftCreateInput",
    "WorkflowDraftEditInput",
    "WorkflowDraftMutationInput",
    "WorkflowDraftUndoInput",
    "WorkflowDraftValidateInput",
    "WorkflowGetInput",
    "WorkflowSearchInput",
    "bind_operator_tool",
]
