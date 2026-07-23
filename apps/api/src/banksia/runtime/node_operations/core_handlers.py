from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from banksia.persistence.models import (
    CompiledPlanModel,
    DispatchRequestModel,
    FlowModel,
    FlowNodeModel,
    WorkflowRevisionModel,
)
from banksia.runtime.assignment import read_assignment_file_references
from banksia.runtime.clock import utc_now
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.contracts.prompt import (
    PromptAssignment,
    PromptBehavior,
    PromptCurrentMember,
    PromptDispatch,
    PromptTask,
)
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.dispatch.prompt_snapshot import (
    capability_projection,
    persisted_provider_projection,
    read_prompt_direct_team,
    workspace_projection,
)
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.node_operations.catalog import (
    list_node_operation_descriptors_for_kind,
)
from banksia.runtime.node_operations.contracts import (
    EmptyNodeOperationRequest,
    GetCurrentContextResponse,
    NodeOperationName,
)
from banksia.runtime.node_operations.state_legality import (
    read_state_legal_node_operations,
)
from banksia.runtime.prompt import parse_prompt_continuation
from banksia.runtime.task_root import read_task_root_paths
from banksia.runtime.work_plan import (
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
    children = await _read_direct_children(session, authority)
    direct_team = await read_prompt_direct_team(
        session,
        children=children,
        dependencies=dependencies,
    )
    assignment_files = await read_assignment_file_references(
        session,
        assignment_id=authority.assignment_id,
    )
    state_legal_actions = await read_state_legal_node_operations(session, authority)
    available_actions = tuple(
        descriptor.name
        for descriptor in list_node_operation_descriptors_for_kind(authority.node_kind)
        if descriptor.name in state_legal_actions
        and _capability_allows(descriptor.name, authority.capabilities)
    )
    workflow_id, workflow_note = await _read_workflow_context(session, authority)
    request = await session.get(DispatchRequestModel, authority.dispatch_id)
    if request is None:
        raise _invalid_committed_request("current Dispatch request is missing")
    try:
        continuation = parse_prompt_continuation(request.input)
    except ValueError as exc:
        raise _invalid_committed_request(str(exc)) from exc
    paths = await read_task_root_paths(session, authority.task_id)
    capabilities = capability_projection(authority.capabilities)
    return GetCurrentContextResponse(
        task=PromptTask(id=authority.task_id, workflow_id=workflow_id),
        dispatch=PromptDispatch(
            id=authority.dispatch_id,
            attempt_id=authority.attempt_id,
            assignment_id=authority.assignment_id,
        ),
        current_member=PromptCurrentMember(
            id=authority.dispatch.member_id,
            title=authority.flow_node.member_title,
            description=authority.flow_node.description,
            instruction=authority.flow_node.node_instruction,
            position=("task_lead" if authority.flow_node.parent_node_key is None else None),
            behavior=(PromptBehavior.MANAGER if direct_team else PromptBehavior.CONTRIBUTOR),
            provider=persisted_provider_projection(
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
        continuation=continuation,
        direct_team=direct_team,
        work_plan=work_plan_view(plan),
        available_actions=available_actions,
        workspace=workspace_projection(
            paths,
            has_workflow_note=bool(workflow_note and workflow_note.strip()),
        ),
        observed_at=utc_now(),
    )


async def _read_direct_children(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> tuple[FlowNodeModel, ...]:
    return tuple(
        await session.scalars(
            select(FlowNodeModel)
            .options(raiseload("*"))
            .where(
                FlowNodeModel.flow_id == authority.flow_id,
                FlowNodeModel.flow_revision_id == authority.flow_revision_id,
                FlowNodeModel.parent_node_key == authority.node_key,
            )
            .order_by(FlowNodeModel.order_index)
        )
    )


async def _read_workflow_context(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> tuple[str, str | None]:
    row = (
        await session.execute(
            select(CompiledPlanModel, WorkflowRevisionModel)
            .options(raiseload("*"))
            .join(
                FlowModel,
                FlowModel.compiled_plan_id == CompiledPlanModel.compiled_plan_id,
            )
            .join(
                WorkflowRevisionModel,
                (WorkflowRevisionModel.workflow_key == CompiledPlanModel.workflow_key)
                & (WorkflowRevisionModel.revision_no == CompiledPlanModel.workflow_revision_no),
            )
            .where(FlowModel.flow_id == authority.flow_id)
        )
    ).one_or_none()
    if row is None:
        raise RuntimeOperationError(
            code=OperationFailureCode.INTERNAL_ERROR,
            summary="current Dispatch is missing its pinned Workflow",
            is_retryable=False,
        )
    compiled_plan, workflow = row
    note = workflow.content_json.get("note")
    if note is not None and not isinstance(note, str):
        raise _invalid_committed_request("pinned Workflow note is not text")
    return compiled_plan.workflow_key, note


def _capability_allows(operation_name: NodeOperationName, capabilities: object) -> bool:
    if operation_name == NodeOperationName.START_COMMAND_RUN:
        return getattr(capabilities, "command_run", "deny") == "allow"
    if operation_name == NodeOperationName.OPEN_HUMAN_REQUEST:
        return any(
            getattr(capabilities, field_name, "deny") == "allow"
            for field_name in (
                "human_direction",
                "human_approval",
                "human_input",
                "human_review",
            )
        )
    return True


def _invalid_committed_request(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.INTERNAL_ERROR,
        summary=summary,
        is_retryable=False,
    )


__all__ = ["execute_core_node_operation"]
