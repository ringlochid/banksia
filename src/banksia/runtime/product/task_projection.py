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
    TeamRevisionMemberModel,
    WorkflowRevisionModel,
)
from banksia.runtime.checkpoint import read_checkpoint_file_references
from banksia.runtime.contracts.task import (
    HumanRequestView,
    TaskAttention,
    TaskMemberUpdate,
    TaskMemberView,
    TaskMemberWorkState,
    TaskPlanStep,
    TaskPlanView,
    TaskProductStatus,
    TaskResultView,
    TaskWorkflowView,
)
from banksia.runtime.errors import missing_resource_error
from banksia.runtime.product.action_ids import product_action_id
from banksia.runtime.product.member_steering import read_task_member_steer_actions
from banksia.runtime.providers import ProviderAdapterRegistry
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
    provider_adapters: ProviderAdapterRegistry | None = None,
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
    plans_by_assignment = await _read_product_plans_by_assignment(
        session,
        latest_assignments.values(),
    )
    steer_actions = await read_task_member_steer_actions(
        session,
        task_id=task.task_id,
        adapters=provider_adapters,
    )
    children_by_parent: dict[str | None, list[str]] = {}
    selections: dict[str, tuple[TeamRevisionMemberModel, MemberConfigurationModel]] = {}
    for selection, configuration in rows:
        selections[selection.member_id] = (selection, configuration)
        children_by_parent.setdefault(selection.parent_member_id, []).append(selection.member_id)

    roots = children_by_parent.get(None, ())
    if len(roots) != 1:
        raise RuntimeError("current Team must contain exactly one root Member")
    root_member_id = roots[0]

    async def build(member_id: str) -> TaskMemberView:
        _selection, configuration = selections[member_id]
        assignment = latest_assignments.get(member_id)
        owns_terminal_result = task.result is not None and member_id == root_member_id
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
                if assignment is not None and not owns_terminal_result
                else None
            ),
            plan=(
                plans_by_assignment.get(assignment.assignment_id)
                if assignment is not None
                else None
            ),
            steer_action=steer_actions.get(member_id),
            children=tuple(
                [await build(child_id) for child_id in children_by_parent.get(member_id, ())]
            ),
        )

    return await build(root_member_id)


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


async def _read_product_plans_by_assignment(
    session: AsyncSession,
    assignments: Iterable[AssignmentModel],
) -> dict[str, TaskPlanView]:
    assignment_ids = tuple(assignment.assignment_id for assignment in assignments)
    if not assignment_ids:
        return {}
    plans = tuple(
        await session.scalars(
            select(AssignmentWorkPlanModel).where(
                AssignmentWorkPlanModel.assignment_id.in_(assignment_ids)
            )
        )
    )
    steps = tuple(
        await session.scalars(
            select(AssignmentWorkPlanStepModel)
            .where(AssignmentWorkPlanStepModel.assignment_id.in_(assignment_ids))
            .order_by(
                AssignmentWorkPlanStepModel.assignment_id,
                AssignmentWorkPlanStepModel.order_index,
            )
        )
    )
    steps_by_assignment: dict[str, list[AssignmentWorkPlanStepModel]] = {}
    for step in steps:
        steps_by_assignment.setdefault(step.assignment_id, []).append(step)
    return {
        plan.assignment_id: TaskPlanView(
            explanation=plan.explanation,
            steps=tuple(
                TaskPlanStep(
                    text=step.step,
                    status=cast(
                        Literal["pending", "in_progress", "completed"],
                        step.status,
                    ),
                )
                for step in steps_by_assignment.get(plan.assignment_id, ())
            ),
            updated_at=plan.committed_at,
        )
        for plan in plans
    }


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
    "product_task_result",
    "read_product_task_status",
    "read_product_task_workflow",
    "read_product_team",
    "task_status_message",
]
