from __future__ import annotations

from datetime import datetime

from sqlalchemy import exists, update
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.persistence.models import DispatchTurnModel, TaskModel
from oh_my_subagents.runtime.contracts import TaskEventSource, TaskEventType
from oh_my_subagents.runtime.control_transitions import (
    TaskDispatchControlConflictError,
    close_current_task_dispatches,
)
from oh_my_subagents.runtime.dispatch.currentness import (
    AttemptDispatchIdentity,
    attempt_dispatch_is_current,
    clear_current_attempt_dispatch,
    dispatch_attempt_is_current,
)
from oh_my_subagents.runtime.dispatch.provider_start import ProviderStartCandidate
from oh_my_subagents.runtime.post_commit import DispatchStartDue
from oh_my_subagents.runtime.task_events import append_task_event
from oh_my_subagents.runtime.team.currentness import dispatch_team_selection_is_current


async def pause_invalid_provider_start(
    session: AsyncSession,
    *,
    signal: DispatchStartDue,
    candidate: ProviderStartCandidate,
    failed_at: datetime,
    failure_code: str,
) -> tuple[str, ...]:
    """Pause one invalid start and close every runnable sibling Attempt lane."""

    if not await _pause_invalid_starting_task(
        session,
        signal,
        candidate,
        failed_at,
        failure_code,
    ):
        await session.rollback()
        return ()
    if not await _close_invalid_starting_dispatch(session, signal, candidate, failed_at):
        await session.rollback()
        return ()
    if not await clear_current_attempt_dispatch(
        session,
        identity=_attempt_dispatch_identity(signal, candidate),
    ):
        await session.rollback()
        return ()

    try:
        closed_sibling_dispatch_ids = await close_current_task_dispatches(
            session,
            task_id=candidate.task_id,
            closed_reason="paused",
            closed_at=failed_at,
        )
    except TaskDispatchControlConflictError:
        await session.rollback()
        return ()

    await _append_invalid_provider_start_event(
        session,
        signal,
        candidate,
        failed_at,
        failure_code,
    )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return closed_sibling_dispatch_ids


async def _close_invalid_starting_dispatch(
    session: AsyncSession,
    signal: DispatchStartDue,
    candidate: ProviderStartCandidate,
    failed_at: datetime,
) -> bool:
    dispatch_id = await session.scalar(
        update(DispatchTurnModel)
        .where(
            DispatchTurnModel.dispatch_id == signal.dispatch_id,
            DispatchTurnModel.task_id == candidate.task_id,
            DispatchTurnModel.assignment_id == candidate.assignment_id,
            DispatchTurnModel.attempt_id == candidate.attempt_id,
            DispatchTurnModel.team_revision_id == candidate.team_revision_id,
            DispatchTurnModel.member_id == candidate.member_id,
            DispatchTurnModel.status == "starting",
            DispatchTurnModel.provider_start_revision == signal.provider_start_revision,
            DispatchTurnModel.provider_start_attempt_count
            == candidate.provider_start_attempt_count,
            DispatchTurnModel.next_provider_start_at == candidate.persisted_due_at,
            dispatch_attempt_is_current(),
        )
        .values(
            status="closed",
            closed_at=failed_at,
            closed_reason="control_failed",
            next_provider_start_at=None,
            provider_start_retry_kind=None,
            provider_start_last_error_code=None,
        )
        .returning(DispatchTurnModel.dispatch_id)
    )
    return dispatch_id is not None


async def _pause_invalid_starting_task(
    session: AsyncSession,
    signal: DispatchStartDue,
    candidate: ProviderStartCandidate,
    failed_at: datetime,
    failure_code: str,
) -> bool:
    task_id = await session.scalar(
        update(TaskModel)
        .where(
            TaskModel.task_id == candidate.task_id,
            TaskModel.status == "running",
            TaskModel.control_revision == candidate.task_control_revision,
            attempt_dispatch_is_current(_attempt_dispatch_identity(signal, candidate)),
            exists().where(
                DispatchTurnModel.dispatch_id == signal.dispatch_id,
                DispatchTurnModel.task_id == candidate.task_id,
                DispatchTurnModel.assignment_id == candidate.assignment_id,
                DispatchTurnModel.attempt_id == candidate.attempt_id,
                DispatchTurnModel.team_revision_id == candidate.team_revision_id,
                DispatchTurnModel.member_id == candidate.member_id,
                DispatchTurnModel.status == "starting",
                DispatchTurnModel.provider_start_revision == signal.provider_start_revision,
                DispatchTurnModel.provider_start_attempt_count
                == candidate.provider_start_attempt_count,
                DispatchTurnModel.next_provider_start_at == candidate.persisted_due_at,
                dispatch_team_selection_is_current(),
            ),
        )
        .values(
            status="paused",
            pause_reason="runtime_transition_failed",
            pause_details={
                "source": "provider_start",
                "source_dispatch_id": signal.dispatch_id,
                "failure_code": failure_code,
            },
            paused_at=failed_at,
            paused_by_actor_ref="controller.runtime",
            control_revision=TaskModel.control_revision + 1,
            updated_at=failed_at,
        )
        .returning(TaskModel.task_id)
    )
    return task_id is not None


def _attempt_dispatch_identity(
    signal: DispatchStartDue,
    candidate: ProviderStartCandidate,
) -> AttemptDispatchIdentity:
    return AttemptDispatchIdentity(
        task_id=candidate.task_id,
        assignment_id=candidate.assignment_id,
        attempt_id=candidate.attempt_id,
        dispatch_id=signal.dispatch_id,
    )


async def _append_invalid_provider_start_event(
    session: AsyncSession,
    signal: DispatchStartDue,
    candidate: ProviderStartCandidate,
    failed_at: datetime,
    failure_code: str,
) -> None:
    await append_task_event(
        session,
        task_id=candidate.task_id,
        event_type=TaskEventType.TASK_PAUSED,
        event_source=TaskEventSource.CONTROLLER,
        occurred_at=failed_at,
        team_revision_id=candidate.team_revision_id,
        dispatch_id=signal.dispatch_id,
        attempt_id=candidate.attempt_id,
        member_id=candidate.member_id,
        actor_ref="controller.runtime",
        payload={
            "pause_reason": "runtime_transition_failed",
            "control_revision": candidate.task_control_revision + 1,
            "actor_ref": "controller.runtime",
            "summary": f"Provider start could not continue: {failure_code}.",
        },
    )


__all__ = ["pause_invalid_provider_start"]
