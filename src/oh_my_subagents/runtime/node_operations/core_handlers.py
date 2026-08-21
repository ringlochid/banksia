from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from oh_my_subagents.persistence.models import (
    DispatchRequestModel,
    MemberConfigurationModel,
    TaskModel,
    TeamRevisionMemberModel,
    WorkflowRevisionModel,
)
from oh_my_subagents.runtime.assignment import read_assignment_file_references
from oh_my_subagents.runtime.clock import utc_now
from oh_my_subagents.runtime.contracts.operation_failure import OperationFailureCode
from oh_my_subagents.runtime.contracts.prompt import (
    PromptAssignment,
    PromptDispatch,
    PromptTask,
)
from oh_my_subagents.runtime.contracts.team_read import CurrentMemberRead, MemberBehavior
from oh_my_subagents.runtime.dispatch.authority import NodeOperationAuthority
from oh_my_subagents.runtime.dispatch.preparation import DispatchOpeningDependencies
from oh_my_subagents.runtime.dispatch.prompt_snapshot import (
    workspace_projection,
)
from oh_my_subagents.runtime.errors import RuntimeOperationError
from oh_my_subagents.runtime.node_operations.contracts import (
    EmptyNodeOperationRequest,
    GetCurrentContextResponse,
    NodeOperationName,
)
from oh_my_subagents.runtime.node_operations.state_legality import (
    read_state_legal_node_operations,
)
from oh_my_subagents.runtime.prompt import parse_prompt_continuation
from oh_my_subagents.runtime.steering import read_assignment_prompt_steers
from oh_my_subagents.runtime.task_root import read_task_root_paths
from oh_my_subagents.runtime.team.reads import (
    available_member_actions,
    effective_capabilities_read,
    persisted_provider_read,
    read_direct_team_members,
)
from oh_my_subagents.runtime.work_plan import (
    SetWorkPlanRequest,
    read_assignment_work_plan,
    set_assignment_work_plan,
    work_plan_view,
)


async def execute_core_node_operation(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    operation_name: NodeOperationName,
    request: BaseModel,
    *,
    dispatch_opening_dependencies: DispatchOpeningDependencies | None,
) -> BaseModel | None:
    if operation_name == NodeOperationName.GET_CURRENT_CONTEXT:
        assert isinstance(request, EmptyNodeOperationRequest)
        if dispatch_opening_dependencies is None:
            raise _invalid_committed_request(
                "current-context provider resolution is not configured"
            )
        return await _get_current_context(
            session,
            authority,
            dependencies=dispatch_opening_dependencies,
        )
    if operation_name == NodeOperationName.SET_WORK_PLAN:
        assert isinstance(request, SetWorkPlanRequest)
        return await set_assignment_work_plan(
            session,
            authority=authority,
            request=request,
        )
    return None


async def _get_current_context(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    dependencies: DispatchOpeningDependencies,
) -> GetCurrentContextResponse:
    plan = await read_assignment_work_plan(session, assignment_id=authority.assignment_id)
    children = await _read_direct_team_members(session, authority)
    direct_team = await read_direct_team_members(
        session,
        children=children,
        dependencies=dependencies,
    )
    assignment_files = await read_assignment_file_references(
        session,
        assignment_id=authority.assignment_id,
    )
    state_legal_actions = await read_state_legal_node_operations(session, authority)
    available_actions = available_member_actions(
        direct_team=direct_team,
        capabilities=effective_capabilities_read(authority.capabilities),
        state_legal_actions=state_legal_actions,
    )
    workflow_id, workflow_note = await _read_workflow_context(session, authority)
    configuration = await _read_member_configuration(session, authority)
    request = await session.get(DispatchRequestModel, authority.dispatch_id)
    if request is None:
        raise _invalid_committed_request("current Dispatch request is missing")
    try:
        continuation = parse_prompt_continuation(request.input)
    except ValueError as exc:
        raise _invalid_committed_request(str(exc)) from exc
    paths = await read_task_root_paths(session, authority.task_id)
    capabilities = effective_capabilities_read(authority.capabilities)
    steering = await read_assignment_prompt_steers(
        session,
        assignment_id=authority.assignment_id,
    )
    return GetCurrentContextResponse(
        task=PromptTask(id=authority.task_id, workflow_id=workflow_id),
        dispatch=PromptDispatch(
            id=authority.dispatch_id,
            attempt_id=authority.attempt_id,
            assignment_id=authority.assignment_id,
        ),
        current_member=CurrentMemberRead(
            id=authority.dispatch.member_id,
            title=configuration.title,
            description=configuration.description,
            instruction=configuration.instruction,
            position=("task_lead" if authority.is_task_lead else None),
            behavior=(MemberBehavior.MANAGER if direct_team else MemberBehavior.CONTRIBUTOR),
            provider=persisted_provider_read(
                authority.dispatch,
                authority.capabilities,
            ),
            effective_capabilities=capabilities,
        ),
        assignment=PromptAssignment(
            id=authority.assignment_id,
            prompt=authority.assignment.prompt,
            files=assignment_files,
        ),
        steering=steering,
        continuation=continuation,
        direct_team=direct_team,
        work_plan=work_plan_view(plan),
        available_actions=tuple(NodeOperationName(action) for action in available_actions),
        workspace=workspace_projection(
            paths,
            has_workflow_note=bool(workflow_note and workflow_note.strip()),
        ),
        observed_at=utc_now(),
    )


async def _read_direct_team_members(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> tuple[TeamRevisionMemberModel, ...]:
    return tuple(
        await session.scalars(
            select(TeamRevisionMemberModel)
            .options(raiseload("*"))
            .where(
                TeamRevisionMemberModel.task_id == authority.task_id,
                TeamRevisionMemberModel.team_revision_id == authority.current_team_revision_id,
                TeamRevisionMemberModel.parent_member_id == authority.member_id,
            )
            .order_by(TeamRevisionMemberModel.sibling_order)
        )
    )


async def _read_workflow_context(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> tuple[str, str | None]:
    row = (
        await session.execute(
            select(TaskModel, WorkflowRevisionModel)
            .options(raiseload("*"))
            .join(
                WorkflowRevisionModel,
                (WorkflowRevisionModel.workflow_key == TaskModel.workflow_key)
                & (WorkflowRevisionModel.revision_no == TaskModel.workflow_revision_no)
                & (WorkflowRevisionModel.content_hash == TaskModel.workflow_content_hash),
            )
            .where(TaskModel.task_id == authority.task_id)
        )
    ).one_or_none()
    if row is None:
        raise RuntimeOperationError(
            code=OperationFailureCode.INTERNAL_ERROR,
            summary="current Dispatch is missing its pinned Workflow",
            is_retryable=False,
        )
    task, workflow = row
    note = workflow.content_json.get("note")
    if note is not None and not isinstance(note, str):
        raise _invalid_committed_request("pinned Workflow note is not text")
    return task.workflow_key, note


async def _read_member_configuration(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> MemberConfigurationModel:
    configuration = await session.scalar(
        select(MemberConfigurationModel)
        .options(raiseload("*"))
        .where(
            MemberConfigurationModel.task_id == authority.task_id,
            MemberConfigurationModel.member_id == authority.member_id,
            MemberConfigurationModel.member_configuration_id
            == authority.team_selection.member_configuration_id,
        )
    )
    if configuration is None:
        raise _invalid_committed_request("current Member configuration is missing")
    return configuration


def _invalid_committed_request(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.INTERNAL_ERROR,
        summary=summary,
        is_retryable=False,
    )


__all__ = ["execute_core_node_operation"]
