from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, cast

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AssignmentModel,
    AssignmentWorkPlanModel,
    AssignmentWorkPlanStepModel,
    AttemptCheckpointModel,
    AttemptModel,
    DispatchTurnModel,
    HumanRequestModel,
    MemberConfigurationModel,
    TaskModel,
    TeamRevisionMemberModel,
    WorkflowRevisionModel,
)
from banksia.runtime.checkpoint import read_checkpoint_file_references
from banksia.runtime.contracts.task import (
    CommandRunView,
    HumanRequestView,
    TaskActivityLink,
    TaskAttention,
    TaskMemberUpdate,
    TaskMemberView,
    TaskMemberWorkState,
    TaskPlanStep,
    TaskPlanView,
    TaskProductStatus,
    TaskResultView,
    TaskSummary,
    TaskView,
    TaskWorkflowView,
)
from banksia.runtime.errors import missing_resource_error
from banksia.runtime.product.action_ids import product_action_id
from banksia.runtime.task_control.contracts import ControllerTaskState
from banksia.workflows.integrity import validate_persisted_workflow_identity


async def read_product_task_status(
    session: AsyncSession,
    task: ControllerTaskState,
) -> TaskProductStatus:
    if task.status.value == "completed":
        return "blocked" if task.terminal_outcome == "blocked" else "completed"
    if task.status.value == "paused":
        return "paused"
    if task.status.value == "cancelled":
        return "cancelled"
    has_open_request = await session.scalar(
        select(
            exists().where(
                HumanRequestModel.task_id == task.task_id,
                HumanRequestModel.status == "open",
            )
        )
    )
    if has_open_request:
        return "waiting_for_you"
    has_starting_dispatch = await session.scalar(
        select(DispatchTurnModel.dispatch_id)
        .where(
            DispatchTurnModel.task_id == task.task_id,
            DispatchTurnModel.status == "starting",
        )
        .limit(1)
    )
    return "starting" if has_starting_dispatch is not None else "working"


async def read_product_team(
    session: AsyncSession,
    *,
    task: ControllerTaskState,
) -> TaskMemberView:
    rows = list(
        (
            await session.execute(
                select(TeamRevisionMemberModel, MemberConfigurationModel)
                .join(
                    MemberConfigurationModel,
                    (
                        MemberConfigurationModel.member_configuration_id
                        == TeamRevisionMemberModel.member_configuration_id
                    ),
                )
                .where(
                    TeamRevisionMemberModel.task_id == task.task_id,
                    TeamRevisionMemberModel.team_revision_id == task.current_team_revision_id,
                )
                .order_by(TeamRevisionMemberModel.preorder_index)
            )
        ).all()
    )
    latest_assignments = await _latest_assignments_by_member(session, task_id=task.task_id)
    children_by_parent: dict[str | None, list[str]] = {}
    selections: dict[str, tuple[TeamRevisionMemberModel, MemberConfigurationModel]] = {}
    for selection, configuration in rows:
        selections[selection.member_id] = (selection, configuration)
        children_by_parent.setdefault(selection.parent_member_id, []).append(selection.member_id)

    async def build(member_id: str) -> TaskMemberView:
        _selection, configuration = selections[member_id]
        assignment = latest_assignments.get(member_id)
        return TaskMemberView(
            id=member_id,
            name=configuration.title or configuration.description or "Team member",
            purpose=configuration.description,
            state=await _read_member_work_state(
                session,
                task=task,
                assignment=assignment,
            ),
            latest_update=(
                await _read_latest_member_update(session, assignment)
                if assignment is not None
                else None
            ),
            children=tuple(
                [await build(child_id) for child_id in children_by_parent.get(member_id, ())]
            ),
        )

    roots = children_by_parent.get(None, ())
    if len(roots) != 1:
        raise RuntimeError("current Team must contain exactly one root Member")
    return await build(roots[0])


async def read_product_task_workflow(
    session: AsyncSession,
    *,
    workflow_id: str,
    revision_no: int,
) -> TaskWorkflowView:
    revision = await session.scalar(
        select(WorkflowRevisionModel).where(
            WorkflowRevisionModel.workflow_key == workflow_id,
            WorkflowRevisionModel.revision_no == revision_no,
            WorkflowRevisionModel.provenance.is_not(None),
        )
    )
    if revision is None:
        raise missing_resource_error("The Workflow used by this run could not be found.")
    validate_persisted_workflow_identity(
        revision.content_json.get("id"),
        expected_workflow_id=workflow_id,
        source="published Workflow",
    )
    description = revision.content_json.get("description")
    if not isinstance(description, str) or not description.strip():
        raise RuntimeError("published Workflow has no product description")
    return TaskWorkflowView(
        id=workflow_id,
        description=description,
    )


async def read_product_root_plan(
    session: AsyncSession,
    task: TaskModel,
) -> TaskPlanView | None:
    if task.root_assignment_id is None:
        return None
    plan = await session.scalar(
        select(AssignmentWorkPlanModel).where(
            AssignmentWorkPlanModel.assignment_id == task.root_assignment_id
        )
    )
    if plan is None:
        return None
    steps = tuple(
        await session.scalars(
            select(AssignmentWorkPlanStepModel)
            .where(AssignmentWorkPlanStepModel.assignment_id == task.root_assignment_id)
            .order_by(AssignmentWorkPlanStepModel.order_index)
        )
    )
    return TaskPlanView(
        explanation=plan.explanation,
        steps=tuple(
            TaskPlanStep(
                text=step.step,
                status=cast(
                    Literal["pending", "in_progress", "completed"],
                    step.status,
                ),
            )
            for step in steps
        ),
        updated_at=plan.committed_at,
    )


def product_task_result(task: ControllerTaskState) -> TaskResultView | None:
    if task.result is None:
        return None
    return TaskResultView(
        status="blocked" if task.result.outcome == "blocked" else "completed",
        summary=task.result.summary,
        details=task.result.details,
        files=task.result.files,
        completed_at=task.result.completed_at,
    )


def build_task_attention(
    *,
    task_id: str,
    human_requests: Iterable[HumanRequestView],
    command_runs: Iterable[CommandRunView],
    result: TaskResultView | None,
) -> tuple[TaskAttention, ...]:
    attention: list[TaskAttention] = []
    for request in human_requests:
        if request.status != "open":
            continue
        attention.append(
            TaskAttention(
                id=request.id,
                kind="human_request",
                title="Needs your attention",
                summary=request.summary,
                member=request.member,
                files=request.files,
                action=request.action,
            )
        )
    for command in command_runs:
        if command.state not in {"failed", "timed_out"}:
            continue
        attention.append(
            TaskAttention(
                id=command.id,
                kind="action_failed",
                title="An action needs review",
                summary=command.outcome_summary or command.purpose,
                member=command.member,
                link=TaskActivityLink(
                    label="View output",
                    href=command.output_href,
                ),
            )
        )
    if result is not None and result.status == "blocked":
        attention.append(
            TaskAttention(
                id=product_action_id("blocked-result", task_id, result.completed_at),
                kind="blocked_result",
                title="The run is blocked",
                summary=result.summary,
                files=result.files,
            )
        )
    return tuple(attention)


def build_task_summary(view: TaskView) -> TaskSummary:
    return TaskSummary(
        id=view.id,
        prompt_excerpt=view.prompt_excerpt,
        workflow=view.workflow,
        status=view.status,
        status_message=view.status_message,
        started_at=view.started_at,
        updated_at=view.updated_at,
        attention_count=len(view.attention),
        result_status=view.result.status if view.result is not None else None,
    )


def task_status_message(status: TaskProductStatus) -> str:
    return {
        "starting": "Banksia accepted the run and is starting the team.",
        "working": "The team is working.",
        "waiting_for_you": "The team needs your input before it can continue.",
        "paused": "The run is paused.",
        "completed": "The run completed with an accepted result.",
        "blocked": "The run ended with an accepted blocked result.",
        "cancelled": "The run was cancelled.",
    }[status]


async def _latest_assignments_by_member(
    session: AsyncSession,
    *,
    task_id: str,
) -> dict[str, AssignmentModel]:
    assignments = tuple(
        await session.scalars(
            select(AssignmentModel)
            .where(AssignmentModel.task_id == task_id)
            .order_by(AssignmentModel.created_at.asc())
        )
    )
    return {assignment.member_id: assignment for assignment in assignments}


async def _read_member_work_state(
    session: AsyncSession,
    *,
    task: ControllerTaskState,
    assignment: AssignmentModel | None,
) -> TaskMemberWorkState:
    if assignment is None:
        return "not_started"
    if assignment.terminal_outcome == "green":
        return "done"
    if assignment.terminal_outcome == "blocked" or task.status.value == "cancelled":
        return "blocked"
    if assignment.current_attempt_id is None:
        return "working"
    attempt = await session.get(AttemptModel, assignment.current_attempt_id)
    if attempt is not None and attempt.current_wait_id is not None:
        return "waiting"
    return "working"


async def _read_latest_member_update(
    session: AsyncSession,
    assignment: AssignmentModel,
) -> TaskMemberUpdate | None:
    checkpoint = await session.scalar(
        select(AttemptCheckpointModel)
        .where(AttemptCheckpointModel.assignment_id == assignment.assignment_id)
        .order_by(AttemptCheckpointModel.recorded_at.desc())
        .limit(1)
    )
    if checkpoint is None:
        return None
    files = await read_checkpoint_file_references(
        session,
        checkpoint_id=checkpoint.checkpoint_id,
    )
    return TaskMemberUpdate(
        summary=checkpoint.summary,
        occurred_at=checkpoint.recorded_at,
        files=files,
    )


__all__ = [
    "build_task_attention",
    "build_task_summary",
    "product_task_result",
    "read_product_root_plan",
    "read_product_task_status",
    "read_product_task_workflow",
    "read_product_team",
    "task_status_message",
]
