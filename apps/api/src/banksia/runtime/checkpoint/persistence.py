from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import exists, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentDecisionModel,
    AttemptCheckpointModel,
    AttemptModel,
    CheckpointFileReferenceModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
    TaskModel,
    TeamRevisionMemberModel,
)
from banksia.runtime.boundary.source_transition import advance_accepted_boundary_state
from banksia.runtime.clock import utc_now
from banksia.runtime.contracts import (
    CheckpointRequest,
    CheckpointResponse,
    FileReference,
    TaskEventSource,
    TaskEventType,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.authority import (
    NodeOperationAuthority,
    exact_node_operation_authority_exists,
)
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.file_references import validate_file_references
from banksia.runtime.node_operations.source_transitions import close_source_dispatch
from banksia.runtime.task_events import append_task_event
from banksia.runtime.task_root.reads import read_task_root_paths


async def commit_checkpoint(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    request: CheckpointRequest,
) -> CheckpointResponse:
    """Commit one progress or terminal Checkpoint against exact Dispatch authority."""

    paths = await read_task_root_paths(session, authority.task_id)
    files = validate_file_references(paths.workspace_path, request.files)
    outcome = request.outcome.value if request.outcome is not None else None
    if outcome is not None:
        await _require_no_staged_child(session, authority)
    if outcome == "green":
        await _require_current_direct_child_participation(session, authority)

    now = utc_now()
    checkpoint_id = f"checkpoint.{authority.task_id}.{uuid4().hex}"
    checkpoint = AttemptCheckpointModel(
        checkpoint_id=checkpoint_id,
        task_id=authority.task_id,
        flow_id=authority.flow_id,
        assignment_id=authority.assignment_id,
        attempt_id=authority.attempt_id,
        authoring_dispatch_id=authority.dispatch_id,
        outcome=outcome,
        summary=request.summary,
        details=request.details,
        recorded_at=now,
    )
    session.add(checkpoint)
    _stage_file_references(
        session,
        checkpoint_id=checkpoint_id,
        files=files,
    )
    await _advance_latest_checkpoint(
        session,
        authority,
        checkpoint_id=checkpoint_id,
        observed_checkpoint_id=authority.attempt.latest_checkpoint_id,
    )
    await _append_checkpoint_event(
        session,
        authority,
        checkpoint_id=checkpoint_id,
        request=request,
        files=files,
        occurred_at=now,
    )

    terminal = outcome is not None
    if terminal:
        assert outcome is not None
        await _commit_terminal_boundary(
            session,
            authority,
            checkpoint_id=checkpoint_id,
            outcome=outcome,
            transitioned_at=now,
        )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _checkpoint_conflict("another operation won the exact Checkpoint transition") from exc
    return CheckpointResponse(
        checkpoint=request,
        recorded_at=now,
        terminal=terminal,
        must_stop=terminal,
    )


def _stage_file_references(
    session: AsyncSession,
    *,
    checkpoint_id: str,
    files: tuple[FileReference, ...],
) -> None:
    session.add_all(
        CheckpointFileReferenceModel(
            checkpoint_id=checkpoint_id,
            order_index=index,
            path=file.path,
            description=file.description,
        )
        for index, file in enumerate(files)
    )


async def _advance_latest_checkpoint(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    checkpoint_id: str,
    observed_checkpoint_id: str | None,
) -> None:
    latest_matches = (
        AttemptModel.latest_checkpoint_id.is_(None)
        if observed_checkpoint_id is None
        else AttemptModel.latest_checkpoint_id == observed_checkpoint_id
    )
    changed = await session.scalar(
        update(AttemptModel)
        .where(
            AttemptModel.task_id == authority.task_id,
            AttemptModel.flow_id == authority.flow_id,
            AttemptModel.assignment_id == authority.assignment_id,
            AttemptModel.attempt_id == authority.attempt_id,
            AttemptModel.status.in_(("pending", "running")),
            latest_matches,
            exact_node_operation_authority_exists(authority),
        )
        .values(latest_checkpoint_id=checkpoint_id)
        .returning(AttemptModel.attempt_id)
    )
    if changed is None:
        raise _checkpoint_conflict("another Checkpoint changed the Attempt latest pointer")


async def _require_no_staged_child(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> None:
    staged = await session.scalar(
        select(AssignmentDecisionModel.assignment_decision_id).where(
            AssignmentDecisionModel.source_dispatch_id == authority.dispatch_id,
            AssignmentDecisionModel.decision_kind == "staged_child",
        )
    )
    if staged is not None:
        raise RuntimeOperationError(
            code=OperationFailureCode.BOUNDARY_PRECONDITION_FAILED,
            summary="a terminal Checkpoint cannot replace a staged child handoff",
            is_retryable=False,
        )


async def _require_current_direct_child_participation(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> None:
    children = tuple(
        await session.scalars(
            select(TeamRevisionMemberModel)
            .where(
                TeamRevisionMemberModel.task_id == authority.task_id,
                TeamRevisionMemberModel.team_revision_id == authority.dispatch.team_revision_id,
                TeamRevisionMemberModel.parent_member_id == authority.dispatch.member_id,
            )
            .order_by(TeamRevisionMemberModel.sibling_order)
        )
    )
    missing: list[str] = []
    for child in children:
        current_assignment_id = await session.scalar(
            select(FlowNodeModel.current_assignment_id).where(
                FlowNodeModel.task_id == authority.task_id,
                FlowNodeModel.flow_id == authority.flow_id,
                FlowNodeModel.flow_revision_id == authority.flow_revision_id,
                FlowNodeModel.team_revision_id == authority.dispatch.team_revision_id,
                FlowNodeModel.member_id == child.member_id,
                FlowNodeModel.member_configuration_id == child.member_configuration_id,
                FlowNodeModel.member_branch_basis_id == child.member_branch_basis_id,
            )
        )
        if current_assignment_id is None:
            missing.append(child.member_id)
            continue
        participated = await session.scalar(
            select(
                exists().where(
                    AcceptedBoundaryModel.task_id == authority.task_id,
                    AcceptedBoundaryModel.flow_id == authority.flow_id,
                    AcceptedBoundaryModel.assignment_id == current_assignment_id,
                    AcceptedBoundaryModel.outcome == "green",
                    DispatchTurnModel.dispatch_id == AcceptedBoundaryModel.source_dispatch_id,
                    DispatchTurnModel.team_revision_id == authority.dispatch.team_revision_id,
                    DispatchTurnModel.member_id == child.member_id,
                    DispatchTurnModel.member_configuration_id == child.member_configuration_id,
                    DispatchTurnModel.member_branch_basis_id == child.member_branch_basis_id,
                )
            )
        )
        if not participated:
            missing.append(child.member_id)
    if missing:
        raise RuntimeOperationError(
            code=OperationFailureCode.BOUNDARY_PRECONDITION_FAILED,
            summary=(
                "green requires an accepted green Checkpoint from every current "
                f"direct child; missing: {', '.join(missing)}"
            ),
            is_retryable=False,
        )


async def _commit_terminal_boundary(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    checkpoint_id: str,
    outcome: str,
    transitioned_at: datetime,
) -> None:
    await close_source_dispatch(
        session,
        authority,
        now=transitioned_at,
        closed_reason="boundary",
        waiting_cause="none",
        waiting_source_id=None,
    )
    await advance_accepted_boundary_state(
        session,
        authority,
        outcome=outcome,
        decision=None,
        transitioned_at=transitioned_at,
    )
    boundary_id = f"accepted-boundary.{authority.dispatch_id}"
    session.add(
        AcceptedBoundaryModel(
            accepted_boundary_id=boundary_id,
            source_dispatch_id=authority.dispatch_id,
            task_id=authority.task_id,
            flow_id=authority.flow_id,
            assignment_id=authority.assignment_id,
            attempt_id=authority.attempt_id,
            outcome=outcome,
            checkpoint_id=checkpoint_id,
            assignment_decision_id=None,
            committed_at=transitioned_at,
        )
    )
    if outcome in {"green", "blocked"} and authority.assignment.parent_assignment_id is None:
        await _select_task_result(
            session,
            authority,
            boundary_id=boundary_id,
            transitioned_at=transitioned_at,
        )
    resulting_flow_status = await session.scalar(
        select(FlowModel.status).where(FlowModel.flow_id == authority.flow_id)
    )
    if resulting_flow_status is None:
        raise _checkpoint_conflict("terminal Checkpoint lost its Flow")
    await append_task_event(
        session,
        task_id=authority.task_id,
        event_type=TaskEventType.BOUNDARY_ACCEPTED,
        event_source=TaskEventSource.NODE,
        occurred_at=transitioned_at,
        flow_revision_id=authority.flow_revision_id,
        dispatch_id=authority.dispatch_id,
        attempt_id=authority.attempt_id,
        node_key=authority.node_key,
        payload={
            "source_dispatch_id": authority.dispatch_id,
            "assignment_id": authority.assignment_id,
            "attempt_id": authority.attempt_id,
            "outcome": outcome,
            "checkpoint_id": checkpoint_id,
            "assignment_decision_id": None,
            "resulting_flow_status": resulting_flow_status,
        },
    )


async def _select_task_result(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    boundary_id: str,
    transitioned_at: datetime,
) -> None:
    selected = await session.scalar(
        update(TaskModel)
        .where(
            TaskModel.task_id == authority.task_id,
            TaskModel.current_team_revision_id == authority.dispatch.team_revision_id,
            TaskModel.result_boundary_id.is_(None),
        )
        .values(
            result_boundary_id=boundary_id,
            updated_at=transitioned_at,
        )
        .returning(TaskModel.task_id)
    )
    if selected is None:
        raise _checkpoint_conflict("Task Result was already selected")


async def _append_checkpoint_event(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    checkpoint_id: str,
    request: CheckpointRequest,
    files: tuple[FileReference, ...],
    occurred_at: datetime,
) -> None:
    await append_task_event(
        session,
        task_id=authority.task_id,
        event_type=TaskEventType.CHECKPOINT_RECORDED,
        event_source=TaskEventSource.NODE,
        occurred_at=occurred_at,
        flow_revision_id=authority.flow_revision_id,
        dispatch_id=authority.dispatch_id,
        attempt_id=authority.attempt_id,
        node_key=authority.node_key,
        payload={
            "checkpoint_id": checkpoint_id,
            "assignment_id": authority.assignment_id,
            "attempt_id": authority.attempt_id,
            "outcome": request.outcome.value if request.outcome is not None else None,
            "summary": request.summary,
            "details": request.details,
            "files": [file.model_dump(mode="json") for file in files],
            "authored_by_dispatch_id": authority.dispatch_id,
        },
    )


def _checkpoint_conflict(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary=summary,
        is_retryable=False,
    )


__all__ = ["commit_checkpoint"]
