from __future__ import annotations

from typing import Literal, assert_never, cast

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from autoclaw.definitions.contracts import DefinitionKind, DefinitionListQuery
from autoclaw.definitions.contracts.workflow import NodeKind
from autoclaw.persistence.models import (
    AcceptedBoundaryModel,
    DispatchPromptRefsModel,
    FlowNodeModel,
)
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.contracts.prompt import RuntimeReadbackRefs
from autoclaw.runtime.dispatch.authority import NodeOperationAuthority
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.node_operations.catalog import (
    list_node_operation_descriptors_for_kind,
)
from autoclaw.runtime.node_operations.contracts import (
    AssignmentContextRead,
    AttemptContextRead,
    CurrentContextTriggerKind,
    CurrentContextTriggerRead,
    EffectiveCapabilitySetRead,
    EffectiveValueRead,
    EmptyNodeOperationRequest,
    FileEntryRead,
    GetCurrentContextResponse,
    GetDefinitionRequest,
    HumanRequestCapabilityRead,
    ListFilesRequest,
    ListFilesResponse,
    NodeOperationName,
    ReadFileRequest,
    ReadFileResponse,
    SearchDefinitionsRequest,
    SlotContextRead,
    WorkflowNeighborRead,
)
from autoclaw.runtime.node_operations.state_legality import (
    read_state_legal_node_operations,
)
from autoclaw.runtime.task_root.file_access import (
    list_logical_directory,
    read_logical_text_file,
)
from autoclaw.runtime.task_root.reads import read_task_root_paths
from autoclaw.runtime.work_plan import (
    SetWorkPlanRequest,
    read_assignment_work_plan,
    set_assignment_work_plan,
)

type CapabilityDecisionValue = Literal["allow", "deny"]
type SlotKind = Literal["artifact", "criteria", "checkpoint", "transient", "workspace"]

_CURRENT_TRIGGER_KIND_BY_OPENED_REASON = {
    "root": CurrentContextTriggerKind.ROOT_START,
    "boundary": CurrentContextTriggerKind.ACCEPTED_BOUNDARY,
    "child_return": CurrentContextTriggerKind.CHILD_RETURN,
    "human_result": CurrentContextTriggerKind.HUMAN_RESULT,
    "command_result": CurrentContextTriggerKind.COMMAND_RESULT,
    "watchdog_recovery": CurrentContextTriggerKind.WATCHDOG_RECOVERY,
    "semantic_retry": CurrentContextTriggerKind.SEMANTIC_RETRY,
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
    if operation_name == NodeOperationName.LIST_FILES:
        assert isinstance(request, ListFilesRequest)
        return await _list_files(session, authority, request)
    if operation_name == NodeOperationName.READ_FILE:
        assert isinstance(request, ReadFileRequest)
        return await _read_file(session, authority, request)
    if operation_name == NodeOperationName.SET_WORK_PLAN:
        assert isinstance(request, SetWorkPlanRequest)
        return await set_assignment_work_plan(
            session,
            authority=authority,
            request=request,
        )
    if operation_name == NodeOperationName.SEARCH_DEFINITIONS:
        from autoclaw.definitions.registry.definition_catalog import (
            list_policy_definitions,
            list_role_definitions,
        )

        assert isinstance(request, SearchDefinitionsRequest)
        query = DefinitionListQuery(
            q=request.query,
            limit=request.limit,
            cursor=request.cursor,
            sort=request.sort,
            allowed_node_kind=request.allowed_node_kind,
            applies_to=request.applies_to,
        )
        if request.kind == DefinitionKind.ROLE:
            return await list_role_definitions(session, query)
        if request.kind == DefinitionKind.POLICY:
            return await list_policy_definitions(session, query)
        assert_never(request.kind)
    if operation_name == NodeOperationName.GET_DEFINITION:
        from autoclaw.definitions.registry.definition_catalog import get_definition_detail

        assert isinstance(request, GetDefinitionRequest)
        if request.kind == DefinitionKind.ROLE:
            return await get_definition_detail(session, DefinitionKind.ROLE, request.key)
        if request.kind == DefinitionKind.POLICY:
            return await get_definition_detail(session, DefinitionKind.POLICY, request.key)
        assert_never(request.kind)
    return None


async def _get_current_context(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> GetCurrentContextResponse:
    plan = await read_assignment_work_plan(session, assignment_id=authority.assignment_id)
    workflow_neighborhood = await _read_workflow_neighborhood(session, authority)
    readback_refs = await _read_runtime_readback_refs(session, authority)
    checkpoint_to_resume_from = await _read_boundary_checkpoint_ref(session, authority)
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
            summary=authority.assignment.summary,
            instruction=authority.assignment.instruction,
            criteria=tuple(authority.assignment.criteria_json),
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
        consume_slots=_slot_reads(authority.assignment.consumes_json, default_kind="artifact"),
        produce_slots=_slot_reads(authority.assignment.produces_json, default_kind="artifact"),
        checkpoint_to_resume_from=checkpoint_to_resume_from,
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


async def _read_boundary_checkpoint_ref(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> str | None:
    source_dispatch_id = authority.predecessor_dispatch_id
    if source_dispatch_id is None:
        return None
    row = (
        await session.execute(
            select(
                AcceptedBoundaryModel.attempt_id,
                AcceptedBoundaryModel.checkpoint_id,
            ).where(
                AcceptedBoundaryModel.successor_dispatch_id == authority.dispatch_id,
                AcceptedBoundaryModel.source_dispatch_id == source_dispatch_id,
                AcceptedBoundaryModel.task_id == authority.task_id,
                AcceptedBoundaryModel.flow_id == authority.flow_id,
            )
        )
    ).one_or_none()
    if row is None or row.checkpoint_id is None:
        return None
    return f"_runtime/attempts/{row.attempt_id}/latest-checkpoint.md"


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
        workflow_manifest="_runtime/workflow-manifest.md",
    )


async def _list_files(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    request: ListFilesRequest,
) -> ListFilesResponse:
    paths = await read_task_root_paths(session, authority.task_id)
    directory, entries = list_logical_directory(paths, request.directory)
    return ListFilesResponse(
        directory=directory,
        entries=tuple(
            FileEntryRead(name=name, path=path, kind=kind, size_bytes=size)
            for name, path, kind, size in entries
        ),
    )


async def _read_file(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    request: ReadFileRequest,
) -> ReadFileResponse:
    paths = await read_task_root_paths(session, authority.task_id)
    path, content, line_count, has_more, next_line = read_logical_text_file(
        paths,
        request.path,
        start_line=request.start_line,
        max_lines=request.max_lines,
    )
    return ReadFileResponse(
        path=path,
        start_line=request.start_line,
        max_lines=request.max_lines,
        content=content,
        lines_returned=line_count,
        has_more=has_more,
        next_start_line=next_line,
    )


def _slot_reads(
    values: list[dict[str, object]],
    *,
    default_kind: str,
) -> tuple[SlotContextRead, ...]:
    result: list[SlotContextRead] = []
    for value in values:
        slot = value.get("slot")
        if not isinstance(slot, str) or not slot.strip():
            continue
        description = value.get("description")
        kind = value.get("kind", default_kind)
        if kind not in {"artifact", "criteria", "checkpoint", "transient", "workspace"}:
            kind = default_kind
        path = value.get("path")
        version = value.get("version")
        result.append(
            SlotContextRead(
                slot=slot,
                kind=cast(SlotKind, kind),
                description=(
                    description if isinstance(description, str) and description.strip() else slot
                ),
                path=path if isinstance(path, str) and path.strip() else None,
                version=version if isinstance(version, int) and version >= 1 else None,
            )
        )
    return tuple(result)


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
