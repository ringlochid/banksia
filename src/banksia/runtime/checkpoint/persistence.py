from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AttemptCheckpointModel,
    AttemptModel,
    CheckpointFileReferenceModel,
    TaskModel,
    TeamRevisionMemberModel,
)
from banksia.runtime.clock import utc_now
from banksia.runtime.contracts import (
    CheckpointRequest,
    CheckpointResponse,
    FileReference,
    TaskEventSource,
    TaskEventType,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.delegation.settlement import settle_wave_member_for_checkpoint
from banksia.runtime.dispatch.authority import (
    NodeOperationAuthority,
    exact_node_operation_authority_exists,
)
from banksia.runtime.dispatch.opening import stage_starting_dispatch
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError, budget_exhausted_error
from banksia.runtime.file_references import validate_file_references
from banksia.runtime.node_operations.follow_on import (
    CommittedNodeOperationFollowOn,
    CommittedNodeOperationResult,
)
from banksia.runtime.node_operations.source_transitions import close_source_dispatch
from banksia.runtime.post_commit import (
    DispatchStartDue,
    RuntimeEffectSignal,
    WaveMemberSettled,
)
from banksia.runtime.providers import ProviderResolutionError
from banksia.runtime.task_events import append_task_event
from banksia.runtime.task_root.reads import read_task_root_paths
from banksia.runtime.team.participation import read_accepted_green_participation

from .semantic_retry import PreparedSemanticRetry, prepare_semantic_retry
from .transitions import advance_terminal_checkpoint_state


async def commit_checkpoint(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    request: CheckpointRequest,
    *,
    dispatch_opening_dependencies: DispatchOpeningDependencies | None = None,
) -> CheckpointResponse | CommittedNodeOperationResult:
    """Commit one progress or terminal Checkpoint against exact Dispatch authority."""

    paths = await read_task_root_paths(session, authority.task_id)
    files = validate_file_references(paths.workspace_path, request.files)
    outcome = request.outcome.value if request.outcome is not None else None
    if outcome == "green":
        await _require_current_direct_child_participation(session, authority)
    recorded_at = utc_now()
    checkpoint_id = f"checkpoint.{authority.task_id}.{uuid4().hex}"
    boundary_id = f"accepted-boundary.{authority.dispatch_id}"
    semantic_retry = await _prepare_checkpoint_semantic_retry(
        session,
        authority,
        request,
        files=files,
        checkpoint_id=checkpoint_id,
        boundary_id=boundary_id,
        outcome=outcome,
        dispatch_opening_dependencies=dispatch_opening_dependencies,
    )
    session.add(
        AttemptCheckpointModel(
            checkpoint_id=checkpoint_id,
            task_id=authority.task_id,
            assignment_id=authority.assignment_id,
            attempt_id=authority.attempt_id,
            authoring_dispatch_id=authority.dispatch_id,
            outcome=outcome,
            summary=request.summary,
            details=request.details,
            recorded_at=recorded_at,
        )
    )
    _stage_file_references(session, checkpoint_id=checkpoint_id, files=files)
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
        occurred_at=recorded_at,
    )
    settled_wave_id = None
    if outcome is not None:
        settled_wave_id = await _stage_terminal_boundary(
            session,
            authority,
            checkpoint_id=checkpoint_id,
            boundary_id=boundary_id,
            outcome=outcome,
            transitioned_at=recorded_at,
            prepared_retry=semantic_retry,
        )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _checkpoint_conflict("another operation won the exact Checkpoint transition") from exc
    return _checkpoint_commit_result(
        request,
        recorded_at=recorded_at,
        terminal=outcome is not None,
        semantic_retry=semantic_retry,
        settled_wave_id=settled_wave_id,
    )


async def _prepare_checkpoint_semantic_retry(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    request: CheckpointRequest,
    *,
    files: tuple[FileReference, ...],
    checkpoint_id: str,
    boundary_id: str,
    outcome: str | None,
    dispatch_opening_dependencies: DispatchOpeningDependencies | None,
) -> PreparedSemanticRetry | None:
    if outcome != "retry":
        return None
    if dispatch_opening_dependencies is None:
        raise RuntimeOperationError(
            code=OperationFailureCode.INTERNAL_ERROR,
            summary="semantic retry requires Dispatch opening dependencies",
            is_retryable=False,
        )
    _require_retry_budget(authority)
    retry_attempt_id = f"attempt.{authority.task_id}.{authority.member_id}.{uuid4().hex}"
    retry_dispatch_id = f"dispatch.{uuid4().hex}"
    try:
        return await prepare_semantic_retry(
            session,
            authority,
            request,
            files=files,
            checkpoint_id=checkpoint_id,
            accepted_boundary_id=boundary_id,
            retry_attempt_id=retry_attempt_id,
            retry_dispatch_id=retry_dispatch_id,
            dependencies=dispatch_opening_dependencies,
        )
    except (ProviderResolutionError, ValueError, OSError) as exc:
        raise RuntimeOperationError(
            code=OperationFailureCode.ILLEGAL_STATE,
            summary="semantic retry Dispatch preparation failed",
            is_retryable=False,
            suggested_next_step=(
                "Repair the current provider route or workflow configuration, "
                "then retry the Checkpoint."
            ),
        ) from exc


def _checkpoint_commit_result(
    request: CheckpointRequest,
    *,
    recorded_at: datetime,
    terminal: bool,
    semantic_retry: PreparedSemanticRetry | None,
    settled_wave_id: str | None,
) -> CheckpointResponse | CommittedNodeOperationResult:
    response = CheckpointResponse(
        checkpoint=request,
        recorded_at=recorded_at,
        terminal=terminal,
        must_stop=terminal,
    )
    if semantic_retry is None and settled_wave_id is None:
        return response
    runtime_signals: tuple[RuntimeEffectSignal, ...]
    if semantic_retry is not None:
        runtime_signals = (
            DispatchStartDue(
                dispatch_id=semantic_retry.request.dispatch_id,
                provider_start_revision=0,
                due_at=semantic_retry.request.due_at,
            ),
        )
    else:
        assert settled_wave_id is not None
        runtime_signals = (WaveMemberSettled(delegation_wave_id=settled_wave_id),)
    return CommittedNodeOperationResult(
        response=response,
        follow_on=CommittedNodeOperationFollowOn(
            runtime_signals=runtime_signals,
        ),
    )


def _require_retry_budget(authority: NodeOperationAuthority) -> None:
    retries_remaining = authority.assignment.retries_remaining
    if retries_remaining is not None and retries_remaining <= 0:
        raise budget_exhausted_error("the current assignment has no semantic retries remaining")


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
        participated = await read_accepted_green_participation(
            session,
            task_id=authority.task_id,
            member_id=child.member_id,
            member_configuration_id=child.member_configuration_id,
            member_branch_basis_id=child.member_branch_basis_id,
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


async def _stage_terminal_boundary(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    checkpoint_id: str,
    boundary_id: str,
    outcome: str,
    transitioned_at: datetime,
    prepared_retry: PreparedSemanticRetry | None,
) -> str | None:
    await close_source_dispatch(
        session,
        authority,
        now=transitioned_at,
        closed_reason="boundary",
    )
    session.add(
        AcceptedBoundaryModel(
            accepted_boundary_id=boundary_id,
            source_dispatch_id=authority.dispatch_id,
            task_id=authority.task_id,
            assignment_id=authority.assignment_id,
            attempt_id=authority.attempt_id,
            outcome=outcome,
            checkpoint_id=checkpoint_id,
            successor_attempt_id=(
                prepared_retry.basis.attempt_id if prepared_retry is not None else None
            ),
            successor_dispatch_id=(
                prepared_retry.request.dispatch_id if prepared_retry is not None else None
            ),
            committed_at=transitioned_at,
        )
    )
    await advance_terminal_checkpoint_state(
        session,
        authority,
        outcome=outcome,
        boundary_id=boundary_id,
        transitioned_at=transitioned_at,
        retry_attempt_id=(prepared_retry.basis.attempt_id if prepared_retry is not None else None),
    )
    settled_wave_id: str | None = None
    if outcome in {"green", "blocked"} and authority.assignment.parent_assignment_id is not None:
        settled_wave_id = await settle_wave_member_for_checkpoint(
            session,
            authority,
            boundary_id=boundary_id,
            outcome=outcome,
            settled_at=transitioned_at,
        )
    if prepared_retry is not None:
        await stage_starting_dispatch(
            session,
            basis=prepared_retry.basis,
            prepared=prepared_retry.request,
        )
    await _append_boundary_accepted_event(
        session,
        authority,
        checkpoint_id=checkpoint_id,
        outcome=outcome,
        transitioned_at=transitioned_at,
    )
    return settled_wave_id


async def _append_boundary_accepted_event(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    checkpoint_id: str,
    outcome: str,
    transitioned_at: datetime,
) -> None:
    resulting_task_status = await session.scalar(
        select(TaskModel.status).where(TaskModel.task_id == authority.task_id)
    )
    if resulting_task_status is None:
        raise _checkpoint_conflict("terminal Checkpoint lost its Task")
    await append_task_event(
        session,
        task_id=authority.task_id,
        event_type=TaskEventType.BOUNDARY_ACCEPTED,
        event_source=TaskEventSource.NODE,
        occurred_at=transitioned_at,
        team_revision_id=authority.team_revision_id,
        dispatch_id=authority.dispatch_id,
        attempt_id=authority.attempt_id,
        member_id=authority.member_id,
        payload={
            "source_dispatch_id": authority.dispatch_id,
            "assignment_id": authority.assignment_id,
            "attempt_id": authority.attempt_id,
            "outcome": outcome,
            "checkpoint_id": checkpoint_id,
            "resulting_task_status": resulting_task_status,
        },
    )


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
        team_revision_id=authority.team_revision_id,
        dispatch_id=authority.dispatch_id,
        attempt_id=authority.attempt_id,
        member_id=authority.member_id,
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
