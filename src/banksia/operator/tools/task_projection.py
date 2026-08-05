from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from banksia.operator.tools.contracts import TaskGetSelection
from banksia.runtime.contracts.human_requests import HumanRequestItem
from banksia.runtime.contracts.refs import FileReference
from banksia.runtime.contracts.task import (
    CommandRunProductState,
    CommandRunView,
    HumanRequestProductStatus,
    HumanRequestResolutionView,
    HumanRequestResponseReceipt,
    HumanRequestView,
    ProductAction,
    ProductActionConfirmation,
    TaskActivity,
    TaskActivityKind,
    TaskActivityLink,
    TaskActivityOutcome,
    TaskAttention,
    TaskAttentionKind,
    TaskControlKind,
    TaskControlReceipt,
    TaskMemberReference,
    TaskMemberUpdate,
    TaskMemberView,
    TaskMemberWorkState,
    TaskPlanView,
    TaskProductStatus,
    TaskResultView,
    TaskView,
    TaskWorkflowView,
)
from banksia.runtime.errors import missing_resource_error

_OVERVIEW_COLLECTION_LIMIT = 20
_OVERVIEW_TEXT_LIMIT = 512
_MEMBER_NAME_LIMIT = 240


class _TaskProjectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OperatorProductAction(_TaskProjectionModel):
    id: str
    kind: str
    label: str
    confirmation: ProductActionConfirmation


class OperatorTaskMemberReference(_TaskProjectionModel):
    id: str
    name: Annotated[str, Field(max_length=_MEMBER_NAME_LIMIT)]


class OperatorTaskMemberSummary(OperatorTaskMemberReference):
    state: TaskMemberWorkState
    child_ids: tuple[str, ...] = ()


class OperatorTaskMemberDetail(_TaskProjectionModel):
    id: str
    name: str
    purpose: str | None = None
    state: TaskMemberWorkState
    latest_update: TaskMemberUpdate | None = None
    child_ids: tuple[str, ...] = ()


class OperatorTaskResultSummary(_TaskProjectionModel):
    status: Literal["completed", "blocked"]
    summary: Annotated[str, Field(max_length=_OVERVIEW_TEXT_LIMIT)]
    has_details: bool
    file_count: int = Field(ge=0)
    completed_at: datetime


class OperatorTaskAttentionSummary(_TaskProjectionModel):
    id: str
    kind: TaskAttentionKind
    title: Annotated[str, Field(max_length=_OVERVIEW_TEXT_LIMIT)]
    summary: Annotated[str, Field(max_length=_OVERVIEW_TEXT_LIMIT)]
    member: OperatorTaskMemberReference | None = None
    file_count: int = Field(ge=0)
    action: OperatorProductAction | None = None
    link: TaskActivityLink | None = None


class OperatorTaskActivitySummary(_TaskProjectionModel):
    id: str
    kind: TaskActivityKind
    occurred_at: datetime
    title: Annotated[str, Field(max_length=_OVERVIEW_TEXT_LIMIT)]
    summary: Annotated[str, Field(max_length=_OVERVIEW_TEXT_LIMIT)] | None = None
    member: OperatorTaskMemberReference | None = None
    outcome: TaskActivityOutcome | None = None
    file_count: int = Field(ge=0)
    action: TaskActivityLink | None = None


class OperatorHumanRequestSummary(_TaskProjectionModel):
    id: str
    kind: Literal["input", "direction", "approval", "review"]
    summary: Annotated[str, Field(max_length=_OVERVIEW_TEXT_LIMIT)]
    status: HumanRequestProductStatus
    member: OperatorTaskMemberReference | None = None
    item_count: int = Field(ge=1, le=3)
    file_count: int = Field(ge=0)
    opened_at: datetime
    due_at: datetime | None = None
    action: OperatorProductAction | None = None
    cancel_action: OperatorProductAction | None = None


class OperatorCommandRunSummary(_TaskProjectionModel):
    id: str
    purpose: Annotated[str, Field(max_length=_OVERVIEW_TEXT_LIMIT)]
    state: CommandRunProductState
    member: OperatorTaskMemberReference | None = None
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    outcome_summary: Annotated[str, Field(max_length=_OVERVIEW_TEXT_LIMIT)] | None = None
    output_href: str
    is_output_complete: bool = Field(serialization_alias="output_complete")
    cancel_action: OperatorProductAction | None = None


class OperatorTaskOverview(_TaskProjectionModel):
    kind: Literal["overview"] = "overview"
    id: str
    prompt_excerpt: str
    workflow: TaskWorkflowView
    status: TaskProductStatus
    status_message: str
    started_at: datetime
    updated_at: datetime
    team: tuple[OperatorTaskMemberSummary, ...]
    plan: TaskPlanView | None = None
    attention: tuple[OperatorTaskAttentionSummary, ...] = ()
    attention_count: int = Field(ge=0)
    is_attention_truncated: bool = Field(
        default=False,
        serialization_alias="attention_truncated",
    )
    actions: tuple[OperatorProductAction, ...] = ()
    result: OperatorTaskResultSummary | None = None
    activities: tuple[OperatorTaskActivitySummary, ...] = ()
    activities_href: str
    is_activities_truncated: bool = Field(
        default=False,
        serialization_alias="activities_truncated",
    )
    human_requests: tuple[OperatorHumanRequestSummary, ...] = ()
    human_request_count: int = Field(ge=0)
    is_human_requests_truncated: bool = Field(
        default=False,
        serialization_alias="human_requests_truncated",
    )
    command_runs: tuple[OperatorCommandRunSummary, ...] = ()
    command_run_count: int = Field(ge=0)
    is_command_runs_truncated: bool = Field(
        default=False,
        serialization_alias="command_runs_truncated",
    )


class OperatorTaskMemberResult(_TaskProjectionModel):
    kind: Literal["member"] = "member"
    task_id: str
    member: OperatorTaskMemberDetail


class OperatorTaskResultDetail(_TaskProjectionModel):
    kind: Literal["result"] = "result"
    task_id: str
    result: TaskResultView


class OperatorTaskActivityDetail(_TaskProjectionModel):
    kind: Literal["activity"] = "activity"
    task_id: str
    activity: TaskActivity


class OperatorHumanRequestDetail(_TaskProjectionModel):
    id: str
    kind: Literal["input", "direction", "approval", "review"]
    summary: str
    items: tuple[HumanRequestItem, ...]
    file_count: int = Field(ge=0)
    opened_at: datetime
    due_at: datetime | None = None
    status: HumanRequestProductStatus
    member: TaskMemberReference | None = None
    action: OperatorProductAction | None = None
    cancel_action: OperatorProductAction | None = None
    resolution: HumanRequestResolutionView | None = None


class OperatorTaskHumanRequestResult(_TaskProjectionModel):
    kind: Literal["human_request"] = "human_request"
    task_id: str
    request: OperatorHumanRequestDetail


class OperatorTaskHumanRequestFilesResult(_TaskProjectionModel):
    kind: Literal["human_request_files"] = "human_request_files"
    task_id: str
    request_id: str
    files: tuple[FileReference, ...]


type OperatorTaskGetResult = (
    OperatorTaskOverview
    | OperatorTaskMemberResult
    | OperatorTaskResultDetail
    | OperatorTaskActivityDetail
    | OperatorTaskHumanRequestResult
    | OperatorTaskHumanRequestFilesResult
)


class OperatorTaskStateReference(_TaskProjectionModel):
    id: str
    status: TaskProductStatus
    status_message: str
    updated_at: datetime
    actions: tuple[OperatorProductAction, ...] = ()


class OperatorTaskControlReceipt(_TaskProjectionModel):
    receipt_id: str
    action: TaskControlKind
    status_message: str
    task: OperatorTaskStateReference


class OperatorHumanRequestStateReference(_TaskProjectionModel):
    id: str
    status: HumanRequestProductStatus
    resolution: HumanRequestResolutionView | None = None


class OperatorHumanRequestResponseReceipt(_TaskProjectionModel):
    receipt_id: str
    status_message: str
    is_continuation_pending: Literal[True] = Field(
        default=True,
        serialization_alias="continuation_pending",
    )
    request: OperatorHumanRequestStateReference


def build_operator_task_result(
    view: TaskView,
    *,
    selection: TaskGetSelection,
) -> OperatorTaskGetResult:
    if selection.kind == "overview":
        return _build_task_overview(view)
    if selection.kind == "member":
        member = _find_task_member(view.team, selection.member_id)
        if member is None:
            raise missing_resource_error("That team member could not be found.")
        return OperatorTaskMemberResult(
            task_id=view.id,
            member=_task_member_detail(member),
        )
    if selection.kind == "result":
        if view.result is None:
            raise missing_resource_error("This run does not have a result.")
        return OperatorTaskResultDetail(task_id=view.id, result=view.result)
    if selection.kind == "activity":
        activity = next(
            (item for item in view.activities if item.id == selection.activity_id),
            None,
        )
        if activity is None:
            raise missing_resource_error(
                "That recent Activity item could not be found. Reload the run overview."
            )
        return OperatorTaskActivityDetail(task_id=view.id, activity=activity)
    raise TypeError("Human Request selections require their owning product read")


def build_operator_human_request_result(
    request: HumanRequestView,
    *,
    task_id: str,
    should_include_files: bool,
) -> OperatorTaskHumanRequestResult | OperatorTaskHumanRequestFilesResult:
    if should_include_files:
        return OperatorTaskHumanRequestFilesResult(
            task_id=task_id,
            request_id=request.id,
            files=request.files,
        )
    return OperatorTaskHumanRequestResult(
        task_id=task_id,
        request=OperatorHumanRequestDetail(
            id=request.id,
            kind=request.kind,
            summary=request.summary,
            items=request.items,
            file_count=len(request.files),
            opened_at=request.opened_at,
            due_at=request.due_at,
            status=request.status,
            member=request.member,
            action=_product_action(request.action),
            cancel_action=_product_action(request.cancel_action),
            resolution=request.resolution,
        ),
    )


def map_operator_task_control_receipt(
    receipt: TaskControlReceipt,
) -> OperatorTaskControlReceipt:
    return OperatorTaskControlReceipt(
        receipt_id=receipt.receipt_id,
        action=receipt.action,
        status_message=receipt.status_message,
        task=OperatorTaskStateReference(
            id=receipt.task.id,
            status=receipt.task.status,
            status_message=receipt.task.status_message,
            updated_at=receipt.task.updated_at,
            actions=tuple(_required_product_action(action) for action in receipt.task.actions),
        ),
    )


def map_operator_human_request_response_receipt(
    receipt: HumanRequestResponseReceipt,
) -> OperatorHumanRequestResponseReceipt:
    return OperatorHumanRequestResponseReceipt(
        receipt_id=receipt.receipt_id,
        status_message=receipt.status_message,
        request=OperatorHumanRequestStateReference(
            id=receipt.request.id,
            status=receipt.request.status,
            resolution=receipt.request.resolution,
        ),
    )


def _build_task_overview(view: TaskView) -> OperatorTaskOverview:
    attention = view.attention[:_OVERVIEW_COLLECTION_LIMIT]
    activities = view.activities[:_OVERVIEW_COLLECTION_LIMIT]
    human_requests = view.human_requests[:_OVERVIEW_COLLECTION_LIMIT]
    command_runs = view.command_runs[:_OVERVIEW_COLLECTION_LIMIT]
    return OperatorTaskOverview(
        id=view.id,
        prompt_excerpt=view.prompt_excerpt,
        workflow=view.workflow,
        status=view.status,
        status_message=view.status_message,
        started_at=view.started_at,
        updated_at=view.updated_at,
        team=tuple(_flatten_task_team(view.team)),
        plan=view.team.plan,
        attention=tuple(_attention_summary(item) for item in attention),
        attention_count=len(view.attention),
        is_attention_truncated=len(view.attention) > len(attention),
        actions=tuple(_required_product_action(action) for action in view.actions),
        result=_result_summary(view.result),
        activities=tuple(_activity_summary(item) for item in activities),
        activities_href=view.activities_href,
        is_activities_truncated=(
            view.is_activity_history_truncated or len(view.activities) > len(activities)
        ),
        human_requests=tuple(_human_request_summary(item) for item in human_requests),
        human_request_count=view.human_request_count,
        is_human_requests_truncated=(
            view.is_human_request_history_truncated
            or len(view.human_requests) > len(human_requests)
        ),
        command_runs=tuple(_command_run_summary(item) for item in command_runs),
        command_run_count=view.command_run_count,
        is_command_runs_truncated=(
            view.is_command_run_history_truncated or len(view.command_runs) > len(command_runs)
        ),
    )


def _flatten_task_team(root: TaskMemberView) -> list[OperatorTaskMemberSummary]:
    result: list[OperatorTaskMemberSummary] = []

    def visit(member: TaskMemberView) -> None:
        result.append(
            OperatorTaskMemberSummary(
                id=member.id,
                name=_excerpt(member.name, limit=_MEMBER_NAME_LIMIT),
                state=member.state,
                child_ids=tuple(child.id for child in member.children),
            )
        )
        for child in member.children:
            visit(child)

    visit(root)
    return result


def _find_task_member(root: TaskMemberView, member_id: str) -> TaskMemberView | None:
    if root.id == member_id:
        return root
    for child in root.children:
        if (match := _find_task_member(child, member_id)) is not None:
            return match
    return None


def _task_member_detail(member: TaskMemberView) -> OperatorTaskMemberDetail:
    return OperatorTaskMemberDetail(
        id=member.id,
        name=member.name,
        purpose=member.purpose,
        state=member.state,
        latest_update=member.latest_update,
        child_ids=tuple(child.id for child in member.children),
    )


def _result_summary(result: TaskResultView | None) -> OperatorTaskResultSummary | None:
    if result is None:
        return None
    return OperatorTaskResultSummary(
        status=result.status,
        summary=_excerpt(result.summary),
        has_details=result.details is not None,
        file_count=len(result.files),
        completed_at=result.completed_at,
    )


def _attention_summary(attention: TaskAttention) -> OperatorTaskAttentionSummary:
    return OperatorTaskAttentionSummary(
        id=attention.id,
        kind=attention.kind,
        title=_excerpt(attention.title),
        summary=_excerpt(attention.summary),
        member=_member_reference(attention.member),
        file_count=len(attention.files),
        action=_product_action(attention.action),
        link=attention.link,
    )


def _activity_summary(activity: TaskActivity) -> OperatorTaskActivitySummary:
    return OperatorTaskActivitySummary(
        id=activity.id,
        kind=activity.kind,
        occurred_at=activity.occurred_at,
        title=_excerpt(activity.title),
        summary=_excerpt(activity.summary) if activity.summary is not None else None,
        member=_member_reference(activity.member),
        outcome=activity.outcome,
        file_count=len(activity.files),
        action=activity.action,
    )


def _human_request_summary(request: HumanRequestView) -> OperatorHumanRequestSummary:
    return OperatorHumanRequestSummary(
        id=request.id,
        kind=request.kind,
        summary=_excerpt(request.summary),
        status=request.status,
        member=_member_reference(request.member),
        item_count=len(request.items),
        file_count=len(request.files),
        opened_at=request.opened_at,
        due_at=request.due_at,
        action=_product_action(request.action),
        cancel_action=_product_action(request.cancel_action),
    )


def _command_run_summary(command: CommandRunView) -> OperatorCommandRunSummary:
    return OperatorCommandRunSummary(
        id=command.id,
        purpose=_excerpt(command.purpose),
        state=command.state,
        member=_member_reference(command.member),
        created_at=command.created_at,
        started_at=command.started_at,
        ended_at=command.ended_at,
        outcome_summary=(
            _excerpt(command.outcome_summary) if command.outcome_summary is not None else None
        ),
        output_href=command.output_href,
        is_output_complete=command.is_output_complete,
        cancel_action=_product_action(command.cancel_action),
    )


def _member_reference(
    member: TaskMemberReference | None,
) -> OperatorTaskMemberReference | None:
    if member is None:
        return None
    return OperatorTaskMemberReference(
        id=member.id,
        name=_excerpt(member.name, limit=_MEMBER_NAME_LIMIT),
    )


def _required_product_action(action: ProductAction) -> OperatorProductAction:
    projected = _product_action(action)
    if projected is None:  # pragma: no cover - non-null input
        raise TypeError("product action projection is missing")
    return projected


def _product_action(action: ProductAction | None) -> OperatorProductAction | None:
    if action is None:
        return None
    return OperatorProductAction(
        id=action.id,
        kind=action.kind,
        label=action.label,
        confirmation=action.confirmation,
    )


def _excerpt(value: str, *, limit: int = _OVERVIEW_TEXT_LIMIT) -> str:
    return " ".join(value.split())[:limit]


__all__ = [
    "OperatorHumanRequestResponseReceipt",
    "OperatorTaskControlReceipt",
    "OperatorTaskGetResult",
    "build_operator_human_request_result",
    "build_operator_task_result",
    "map_operator_human_request_response_receipt",
    "map_operator_task_control_receipt",
]
