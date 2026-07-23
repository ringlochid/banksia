from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    DispatchTurnModel,
    FlowModel,
    ReplanTransitionModel,
    TaskModel,
)
from banksia.runtime.clock import utc_now
from banksia.runtime.contracts import (
    ReplanMemberRead,
    ReplanOperation,
    ReplanSuccess,
    TaskEventSource,
    TaskEventType,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.replan.context import (
    ReplanCommitContext,
    read_replan_context,
    require_replan_admission,
)
from banksia.runtime.replan.planning import (
    PlannedMember,
    ReplanMutation,
    ReplanRequest,
    build_replan_mutation,
)
from banksia.runtime.replan.staging import stage_replan_successor_rows
from banksia.runtime.task_events import append_task_event


@dataclass(frozen=True, slots=True)
class ReplanCommit:
    """Committed public result and durable transition identity."""

    result: ReplanSuccess
    transition_id: str


async def commit_replan_rows(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    operation: ReplanOperation,
    request: ReplanRequest,
) -> ReplanCommit:
    """Commit a complete immutable Team/Flow successor behind dual CAS pointers."""

    context = await read_replan_context(session, authority)
    mutation = build_replan_mutation(
        loaded=context.members,
        root_member_id=context.team_revision.root_member_id,
        caller_member_id=authority.assignment.member_id,
        request=request,
    )
    await require_replan_admission(session, authority, mutation)
    result = _build_result(mutation, authority.assignment.member_id, operation)
    successor_team_id = f"team-revision.{uuid4().hex}"
    successor_flow_id = f"flow-revision.{uuid4().hex}"
    transition_id = f"replan-transition.{uuid4().hex}"
    await _claim_replan_heads(
        session,
        authority,
        context,
        successor_team_id=successor_team_id,
        successor_flow_id=successor_flow_id,
    )
    stage_replan_successor_rows(
        session,
        authority,
        context,
        mutation,
        operation=operation,
        successor_team_id=successor_team_id,
        successor_flow_id=successor_flow_id,
    )
    await session.flush()
    await _stage_transition_and_event(
        session,
        authority,
        context,
        request=request,
        result=result,
        operation=operation,
        transition_id=transition_id,
        successor_team_id=successor_team_id,
        successor_flow_id=successor_flow_id,
    )
    await session.commit()
    return ReplanCommit(result=result, transition_id=transition_id)


async def _claim_replan_heads(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    context: ReplanCommitContext,
    *,
    successor_team_id: str,
    successor_flow_id: str,
) -> None:
    task_id = await session.scalar(
        update(TaskModel)
        .where(
            TaskModel.task_id == authority.task_id,
            TaskModel.current_team_revision_id == context.team_revision.team_revision_id,
        )
        .values(current_team_revision_id=successor_team_id)
        .returning(TaskModel.task_id)
    )
    flow_id = await session.scalar(
        update(FlowModel)
        .where(
            FlowModel.flow_id == authority.flow_id,
            FlowModel.task_id == authority.task_id,
            FlowModel.status == "running",
            FlowModel.active_flow_revision_id == context.flow_revision.flow_revision_id,
            FlowModel.current_dispatch_id == authority.dispatch_id,
            FlowModel.waiting_cause == "none",
            FlowModel.control_revision == context.flow.control_revision,
        )
        .values(
            active_flow_revision_id=successor_flow_id,
            current_dispatch_id=None,
            control_revision=FlowModel.control_revision + 1,
            updated_at=utc_now(),
        )
        .returning(FlowModel.flow_id)
    )
    if task_id is None or flow_id is None:
        raise _conflict("another replan or flow transition won the current pointers")
    closed = await session.scalar(
        update(DispatchTurnModel)
        .where(
            DispatchTurnModel.dispatch_id == authority.dispatch_id,
            DispatchTurnModel.status.in_(("starting", "open")),
        )
        .values(
            status="closed",
            closed_at=utc_now(),
            closed_reason="structural_replan",
            next_provider_start_at=None,
            provider_start_retry_kind=None,
        )
        .returning(DispatchTurnModel.dispatch_id)
    )
    if closed is None:
        raise _conflict("another transition closed the source Dispatch")


async def _stage_transition_and_event(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    context: ReplanCommitContext,
    *,
    request: ReplanRequest,
    result: ReplanSuccess,
    operation: ReplanOperation,
    transition_id: str,
    successor_team_id: str,
    successor_flow_id: str,
) -> None:
    session.add(
        ReplanTransitionModel(
            replan_transition_id=transition_id,
            task_id=authority.task_id,
            flow_id=authority.flow_id,
            assignment_id=authority.assignment_id,
            attempt_id=authority.attempt_id,
            source_dispatch_id=authority.dispatch_id,
            operation=operation,
            normalized_request_json=request.model_dump(mode="json", exclude_unset=True),
            committed_result_json=result.model_dump(mode="json", exclude_none=True),
            source_team_revision_id=context.team_revision.team_revision_id,
            successor_team_revision_id=successor_team_id,
            source_flow_revision_id=context.flow_revision.flow_revision_id,
            successor_flow_revision_id=successor_flow_id,
            manifest_state="pending",
            successor_state="blocked",
        )
    )
    target_id = (
        result.created_ids[0]
        if result.created_ids
        else (result.updated_ids[0] if result.updated_ids else result.removed_ids[0])
    )
    await append_task_event(
        session,
        task_id=authority.task_id,
        event_type=TaskEventType.STRUCTURAL_REVISION_ADOPTED,
        event_source=TaskEventSource.NODE,
        flow_revision_id=successor_flow_id,
        dispatch_id=authority.dispatch_id,
        attempt_id=authority.attempt_id,
        node_key=authority.node_key,
        payload={
            "source_flow_revision_id": context.flow_revision.flow_revision_id,
            "adopted_flow_revision_id": successor_flow_id,
            "operation": operation,
            "target_node_key": target_id,
            "cause": f"{operation} accepted from the exact current Dispatch.",
            "adopted_by_dispatch_id": authority.dispatch_id,
        },
    )


def _build_result(
    mutation: ReplanMutation,
    caller_member_id: str,
    operation: ReplanOperation,
) -> ReplanSuccess:
    direct_children = tuple(
        _member_read(mutation.members[child_id])
        for child_id in mutation.members[caller_member_id].children
    )
    return ReplanSuccess(
        operation=operation,
        created_ids=mutation.created_ids,
        updated_ids=mutation.updated_ids,
        removed_ids=mutation.removed_ids,
        direct_children=direct_children,
        must_stop=True,
    )


def _member_read(member: PlannedMember) -> ReplanMemberRead:
    return ReplanMemberRead.model_validate(
        {
            "id": member.member_id,
            "title": member.title,
            "description": member.description,
            "instruction": member.instruction,
            "provider": member.provider_json,
            "capabilities": member.capabilities_json,
            "child_ids": tuple(member.children),
        }
    )


def _conflict(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary=summary,
        is_retryable=False,
    )


__all__ = ["ReplanCommit", "commit_replan_rows"]
