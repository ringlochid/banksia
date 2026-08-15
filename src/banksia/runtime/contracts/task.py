from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from banksia.runtime.contracts.human_requests import HumanRequestItem, HumanRequestItemAnswer
from banksia.runtime.contracts.refs import FileReference
from banksia.runtime.contracts.start import TaskStartRequest
from banksia.runtime.contracts.text import normalize_exact_text

type TaskProductStatus = Literal[
    "starting",
    "working",
    "waiting_for_you",
    "paused",
    "completed",
    "blocked",
    "cancelled",
]
type TaskMemberWorkState = Literal[
    "not_started",
    "working",
    "waiting",
    "done",
    "blocked",
]
type TaskActivityKind = Literal[
    "task_started",
    "task_paused",
    "task_resumed",
    "task_cancelled",
    "task_completed",
    "task_blocked",
    "work_completed",
    "work_blocked",
    "input_requested",
    "input_received",
    "input_expired",
    "input_cancelled",
    "action_started",
    "action_succeeded",
    "action_failed",
    "action_timed_out",
    "action_cancelled",
    "member_steered",
]
type TaskActivityOutcome = Literal["completed", "blocked", "failed", "cancelled"]
type TaskControlKind = Literal["pause", "resume", "cancel"]
type TaskAttentionKind = Literal[
    "human_request",
    "blocked_result",
    "workspace_unavailable",
]
type CommandRunProductState = Literal[
    "queued",
    "running",
    "cancelling",
    "succeeded",
    "failed",
    "timed_out",
    "cancelled",
]
type HumanRequestProductStatus = Literal["open", "answered", "expired", "cancelled"]


class _ProductModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        from_attributes=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class ProductActionConfirmation(_ProductModel):
    is_required: bool = Field(
        validation_alias="required",
        serialization_alias="required",
    )
    title: str
    consequence: str


class ProductAction(_ProductModel):
    id: str
    kind: str
    label: str
    href: str
    confirmation: ProductActionConfirmation
    input_schema: dict[str, JsonValue] | None = None


class TaskWorkflowView(_ProductModel):
    id: str
    description: str


class TaskMemberReference(_ProductModel):
    id: str
    name: str


class TaskMemberUpdate(_ProductModel):
    summary: str
    occurred_at: datetime
    files: tuple[FileReference, ...] = ()


class TaskPlanStep(_ProductModel):
    text: str
    status: Literal["pending", "in_progress", "completed"]


class TaskPlanView(_ProductModel):
    explanation: str | None = None
    steps: tuple[TaskPlanStep, ...]
    updated_at: datetime


class TaskMemberView(_ProductModel):
    id: str
    name: str
    purpose: str | None = None
    state: TaskMemberWorkState
    latest_update: TaskMemberUpdate | None = None
    plan: TaskPlanView | None = None
    steer_action: ProductAction | None = None
    children: tuple[TaskMemberView, ...] = ()


class TaskResultView(_ProductModel):
    status: Literal["completed", "blocked"]
    summary: str
    details: str | None = None
    files: tuple[FileReference, ...] = ()
    completed_at: datetime


class TaskActivityLink(_ProductModel):
    label: str
    href: str


class TaskActivity(_ProductModel):
    id: str
    kind: TaskActivityKind
    occurred_at: datetime
    title: str
    summary: str | None = None
    member: TaskMemberReference | None = None
    outcome: TaskActivityOutcome | None = None
    files: tuple[FileReference, ...] = ()
    action: TaskActivityLink | None = None


class TaskActivityPage(_ProductModel):
    items: tuple[TaskActivity, ...]
    next_cursor: str | None = None


class HumanRequestResolutionView(_ProductModel):
    status: Literal["answered", "expired", "cancelled"]
    summary: str
    resolved_at: datetime


class HumanRequestView(_ProductModel):
    id: str
    kind: Literal["input", "direction", "approval", "review"]
    summary: str
    items: tuple[HumanRequestItem, ...]
    files: tuple[FileReference, ...] = ()
    opened_at: datetime
    due_at: datetime | None = None
    status: HumanRequestProductStatus
    member: TaskMemberReference | None = None
    action: ProductAction | None = None
    cancel_action: ProductAction | None = None
    resolution: HumanRequestResolutionView | None = None


class CommandRunView(_ProductModel):
    id: str
    purpose: str
    state: CommandRunProductState
    member: TaskMemberReference | None = None
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    elapsed_seconds: float | None = Field(default=None, ge=0)
    outcome_summary: str | None = None
    output_href: str
    is_output_complete: bool = Field(
        validation_alias="output_complete",
        serialization_alias="output_complete",
    )
    cancel_action: ProductAction | None = None


class CommandRunPage(_ProductModel):
    items: tuple[CommandRunView, ...]
    next_cursor: str | None = None


class TaskAttention(_ProductModel):
    id: str
    kind: TaskAttentionKind
    title: str
    summary: str
    member: TaskMemberReference | None = None
    files: tuple[FileReference, ...] = ()
    action: ProductAction | None = None
    link: TaskActivityLink | None = None


class TaskView(_ProductModel):
    id: str
    prompt_excerpt: str
    workflow: TaskWorkflowView
    status: TaskProductStatus
    status_message: str
    started_at: datetime
    updated_at: datetime
    team: TaskMemberView
    attention: tuple[TaskAttention, ...] = ()
    actions: tuple[ProductAction, ...] = ()
    result: TaskResultView | None = None
    activities: tuple[TaskActivity, ...] = ()
    activities_href: str
    is_activity_history_truncated: bool = Field(
        default=False,
        validation_alias="activities_truncated",
        serialization_alias="activities_truncated",
    )
    human_requests: tuple[HumanRequestView, ...] = ()
    human_request_count: int = Field(default=0, ge=0)
    is_human_request_history_truncated: bool = Field(
        default=False,
        validation_alias="human_requests_truncated",
        serialization_alias="human_requests_truncated",
    )
    command_runs: tuple[CommandRunView, ...] = ()
    command_runs_href: str
    command_run_count: int = Field(default=0, ge=0)
    is_command_run_history_truncated: bool = Field(
        default=False,
        validation_alias="command_runs_truncated",
        serialization_alias="command_runs_truncated",
    )


class TaskSummary(_ProductModel):
    id: str
    prompt_excerpt: str
    workflow: TaskWorkflowView
    status: TaskProductStatus
    status_message: str
    started_at: datetime
    updated_at: datetime
    attention_count: int = Field(ge=0)
    result_status: Literal["completed", "blocked"] | None = None


class TaskSearchResponse(_ProductModel):
    items: tuple[TaskSummary, ...]
    next_cursor: str | None = None


class TaskStartReceipt(_ProductModel):
    receipt_id: str
    task_id: str
    workflow_id: str
    workflow_revision: int = Field(ge=1)
    workspace: str
    manifest: str
    status: Literal["accepted"] = "accepted"
    status_message: str = (
        "The run was accepted. Work starts asynchronously and may still need attention."
    )


class TaskControlRequest(_ProductModel):
    is_confirmed: bool = Field(
        default=False,
        validation_alias="confirmed",
        serialization_alias="confirmed",
    )


class TaskControlReceipt(_ProductModel):
    receipt_id: str
    action: TaskControlKind
    status_message: str
    task: TaskView


class MemberSteerRequest(_ProductModel):
    action_id: str
    message: str = Field(min_length=1, max_length=4_096)

    @field_validator("message", mode="before")
    @classmethod
    def normalize_message(cls, value: object) -> str:
        return normalize_exact_text(
            value,
            label="Member steer message",
            is_nonblank_required=True,
        )


class MemberSteerReceipt(_ProductModel):
    receipt_id: str
    status: Literal["delivered", "uncertain"]
    status_message: str
    task: TaskView


class HumanRequestAnswerInput(_ProductModel):
    kind: Literal["answer"]
    item_responses: dict[str, HumanRequestItemAnswer] = Field(min_length=1, max_length=3)


class HumanRequestCancelInput(_ProductModel):
    kind: Literal["cancel"]
    is_confirmed: Literal[True] = Field(
        validation_alias="confirmed",
        serialization_alias="confirmed",
    )


type HumanRequestResponseInput = Annotated[
    HumanRequestAnswerInput | HumanRequestCancelInput,
    Field(discriminator="kind"),
]


class HumanRequestResponseRequest(_ProductModel):
    action_id: str
    input: HumanRequestResponseInput


class HumanRequestResponseReceipt(_ProductModel):
    receipt_id: str
    status_message: str
    is_continuation_pending: Literal[True] = Field(
        default=True,
        validation_alias="continuation_pending",
        serialization_alias="continuation_pending",
    )
    request: HumanRequestView


class CommandRunOutputPage(_ProductModel):
    command_id: str
    content: str
    next_cursor: str | None = None
    is_output_complete: bool = Field(
        validation_alias="output_complete",
        serialization_alias="output_complete",
    )
    is_missing: bool
    is_changed: bool
    is_bounded: bool


class CommandRunCancelRequest(_ProductModel):
    action_id: str
    is_confirmed: Literal[True] = Field(
        validation_alias="confirmed",
        serialization_alias="confirmed",
    )


class CommandRunCancelReceipt(_ProductModel):
    receipt_id: str
    status_message: str
    command_run: CommandRunView


for _task_product_contract in (
    ProductAction,
    TaskMemberView,
    TaskActivity,
    HumanRequestView,
    TaskView,
    HumanRequestAnswerInput,
    HumanRequestResponseRequest,
    MemberSteerReceipt,
):
    _task_product_contract.model_rebuild(_types_namespace=globals())


__all__ = [
    "CommandRunCancelReceipt",
    "CommandRunCancelRequest",
    "CommandRunOutputPage",
    "CommandRunPage",
    "CommandRunProductState",
    "CommandRunView",
    "HumanRequestAnswerInput",
    "HumanRequestCancelInput",
    "HumanRequestProductStatus",
    "HumanRequestResolutionView",
    "HumanRequestResponseInput",
    "HumanRequestResponseReceipt",
    "HumanRequestResponseRequest",
    "HumanRequestView",
    "MemberSteerReceipt",
    "MemberSteerRequest",
    "ProductAction",
    "ProductActionConfirmation",
    "TaskActivity",
    "TaskActivityKind",
    "TaskActivityLink",
    "TaskActivityOutcome",
    "TaskActivityPage",
    "TaskAttention",
    "TaskAttentionKind",
    "TaskControlKind",
    "TaskControlReceipt",
    "TaskControlRequest",
    "TaskMemberReference",
    "TaskMemberUpdate",
    "TaskMemberView",
    "TaskMemberWorkState",
    "TaskPlanStep",
    "TaskPlanView",
    "TaskProductStatus",
    "TaskResultView",
    "TaskSearchResponse",
    "TaskStartReceipt",
    "TaskStartRequest",
    "TaskSummary",
    "TaskView",
    "TaskWorkflowView",
]
