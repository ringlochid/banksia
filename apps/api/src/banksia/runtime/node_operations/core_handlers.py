from __future__ import annotations

from typing import Literal, cast

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from banksia.persistence.models import (
    DispatchPromptRefsModel,
    FlowNodeModel,
)
from banksia.runtime.assignment import read_assignment_file_references
from banksia.runtime.contracts.member import NodeKind
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.contracts.prompt import RuntimeReadbackRefs
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.node_operations.catalog import (
    list_node_operation_descriptors_for_kind,
)
from banksia.runtime.node_operations.contracts import (
    AssignmentContextRead,
    AttemptContextRead,
    CurrentContextTriggerKind,
    CurrentContextTriggerRead,
    EffectiveCapabilitySetRead,
    EffectiveValueRead,
    EmptyNodeOperationRequest,
    GetCurrentContextResponse,
    HumanRequestCapabilityRead,
    NodeOperationName,
    WorkflowNeighborRead,
)
from banksia.runtime.node_operations.state_legality import (
    read_state_legal_node_operations,
)
from banksia.runtime.work_plan import (
    SetWorkPlanRequest,
    read_assignment_work_plan,
    set_assignment_work_plan,
)

type CapabilityDecisionValue = Literal["allow", "deny"]
_CURRENT_TRIGGER_KIND_BY_OPENED_REASON = {
    "root": CurrentContextTriggerKind.ROOT_START,
    "boundary": CurrentContextTriggerKind.ACCEPTED_BOUNDARY,
    "child_return": CurrentContextTriggerKind.CHILD_RETURN,
    "human_result": CurrentContextTriggerKind.HUMAN_RESULT,
    "command_result": CurrentContextTriggerKind.COMMAND_RESULT,
    "watchdog_recovery": CurrentContextTriggerKind.WATCHDOG_RECOVERY,
    "semantic_retry": CurrentContextTriggerKind.SEMANTIC_RETRY,
    "structural_replan": CurrentContextTriggerKind.STRUCTURAL_REPLAN,
    "operator_continue": CurrentContextTriggerKind.OPERATOR_CONTINUE,
}


async def execute_core_node_operation(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    operation_name: NodeOperationName,
    request: BaseModel,
) -> BaseModel | None:
    if operation_name == NodeOperationName.GET_CURRENT_CONTEXT:
        assert isinstance(request, EmptyNodeOperationRequest)
        return await _get_current_context(session, authority)
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
) -> GetCurrentContextResponse:
    plan = await read_assignment_work_plan(session, assignment_id=authority.assignment_id)
    workflow_neighborhood = await _read_workflow_neighborhood(session, authority)
    readback_refs = await _read_runtime_readback_refs(session, authority)
    assignment_files = await read_assignment_file_references(
        session,
        assignment_id=authority.assignment_id,
    )
    capabilities = authority.capabilities
    state_legal_actions = await read_state_legal_node_operations(session, authority)
    allowed_actions = tuple(
        descriptor.name
        for descriptor in list_node_operation_descriptors_for_kind(authority.node_kind)
        if descriptor.name in state_legal_actions
        and _capability_allows(descriptor.name, capabilities)
    )
    return GetCurrentContextResponse(
        task_id=authority.task_id,
        dispatch_id=authority.dispatch_id,
        assignment=AssignmentContextRead(
            assignment_id=authority.assignment_id,
            node_key=authority.node_key,
            node_kind=authority.node_kind,
            prompt=authority.assignment.prompt,
            files=assignment_files,
        ),
        attempt=AttemptContextRead(
            attempt_id=authority.attempt_id,
            assignment_id=authority.assignment_id,
            retry_of_attempt_id=authority.attempt.retry_of_attempt_id,
        ),
        trigger=_current_context_trigger(authority),
        plan=plan,
        workflow_neighborhood=workflow_neighborhood,
        readback_refs=readback_refs,
        capabilities=EffectiveCapabilitySetRead(
            dispatch_id=authority.dispatch_id,
            provider_native_access=EffectiveValueRead(
                effective=capabilities.provider_native_access,
                source=capabilities.provider_native_access_source,
            ),
            network_access=EffectiveValueRead(
                effective=capabilities.network_access,
                source=capabilities.network_access_source,
            ),
            human_request=HumanRequestCapabilityRead(
                direction=cast(CapabilityDecisionValue, capabilities.human_direction),
                approval=cast(CapabilityDecisionValue, capabilities.human_approval),
                input=cast(CapabilityDecisionValue, capabilities.human_input),
                review=cast(CapabilityDecisionValue, capabilities.human_review),
            ),
            command_run=cast(CapabilityDecisionValue, capabilities.command_run),
        ),
        allowed_actions=allowed_actions,
    )


def _current_context_trigger(authority: NodeOperationAuthority) -> CurrentContextTriggerRead:
    try:
        kind = _CURRENT_TRIGGER_KIND_BY_OPENED_REASON[authority.opened_reason]
    except KeyError as exc:
        raise RuntimeOperationError(
            code=OperationFailureCode.INTERNAL_ERROR,
            summary="current dispatch has an unsupported trigger kind",
            is_retryable=False,
        ) from exc
    return CurrentContextTriggerRead(
        kind=kind,
        source_dispatch_id=authority.predecessor_dispatch_id,
    )


async def _read_workflow_neighborhood(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> tuple[WorkflowNeighborRead, ...]:
    children = tuple(
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
    return tuple(
        WorkflowNeighborRead(
            node_key=child.node_key,
            node_kind=NodeKind(child.structural_kind),
            relationship="direct child",
            assignment_id=child.current_assignment_id,
        )
        for child in children
    )


async def _read_runtime_readback_refs(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> RuntimeReadbackRefs:
    prompt_refs = await session.get(
        DispatchPromptRefsModel,
        authority.dispatch_id,
        populate_existing=True,
    )
    expected_root = f"_runtime/dispatch/{authority.dispatch_id}"
    if (
        prompt_refs is None
        or prompt_refs.instructions_logical_path != f"{expected_root}/instructions.md"
        or prompt_refs.input_logical_path != f"{expected_root}/input.md"
    ):
        raise RuntimeOperationError(
            code=OperationFailureCode.INTERNAL_ERROR,
            summary="current dispatch is missing its exact request readback refs",
            is_retryable=False,
        )
    return RuntimeReadbackRefs(
        instructions=prompt_refs.instructions_logical_path,
        input=prompt_refs.input_logical_path,
        workflow_manifest="manifest.md",
    )


def _capability_allows(operation_name: NodeOperationName, capabilities: object) -> bool:
    if operation_name == NodeOperationName.START_COMMAND_RUN:
        return getattr(capabilities, "command_run", "deny") == "allow"
    if operation_name == NodeOperationName.OPEN_HUMAN_REQUEST:
        return any(
            getattr(capabilities, field_name, "deny") == "allow"
            for field_name in ("human_direction", "human_approval", "human_input", "human_review")
        )
    return True


__all__ = ["execute_core_node_operation"]
