from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload
from sqlalchemy.sql.elements import ColumnElement

from banksia.persistence.models import (
    AssignmentModel,
    AttemptModel,
    DispatchTurnModel,
    TaskModel,
    TeamRevisionMemberModel,
)
from banksia.runtime.contracts import TaskEventSource, TaskEventType
from banksia.runtime.control_transitions import (
    TaskDispatchControlConflictError,
    close_current_task_dispatches,
)
from banksia.runtime.post_commit import WatchdogDue
from banksia.runtime.task_events import append_task_event
from banksia.runtime.watchdog.context import (
    WatchdogRecoverySnapshot,
    dispatch_owns_external_source,
)
from banksia.runtime.watchdog.deadline import calculate_watchdog_due_at
from banksia.runtime.watchdog.predicates import (
    dispatch_has_no_external_source,
    dispatch_has_no_successor,
    nullable_datetime_matches,
    watchdog_context_is_current,
    watchdog_replacement_count_matches,
)


@dataclass(frozen=True, slots=True)
class _FailedWatchdogCandidate:
    dispatch_id: str
    task_id: str
    assignment_id: str
    attempt_id: str
    source_team_revision_id: str
    current_team_revision_id: str
    member_id: str
    member_configuration_id: str
    member_branch_basis_id: str
    adapter_started_at: datetime
    last_node_activity_at: datetime | None
    task_control_revision: int


type _FailedWatchdogRows = tuple[
    DispatchTurnModel,
    TaskModel,
    AssignmentModel,
    AttemptModel,
    TeamRevisionMemberModel,
]


async def pause_watchdog_snapshot(
    session: AsyncSession,
    *,
    snapshot: WatchdogRecoverySnapshot,
    paused_at: datetime,
    pause_reason: str,
    failure_code: str | None,
) -> tuple[str, ...] | None:
    """Pause a still-current rendered watchdog source and all runnable lanes."""

    dispatch = snapshot.dispatch
    prompt = dispatch.prompt
    return await _commit_watchdog_pause(
        session,
        task_id=prompt.task_id,
        current_team_revision_id=prompt.team_revision_id,
        dispatch_id=prompt.predecessor_dispatch_id,
        assignment_id=prompt.assignment_id,
        attempt_id=prompt.attempt_id,
        member_id=prompt.member_id,
        control_revision=dispatch.task_control_revision,
        source_is_current=(
            watchdog_context_is_current(snapshot) & watchdog_replacement_count_matches(snapshot)
        ),
        paused_at=paused_at,
        pause_reason=pause_reason,
        failure_code=failure_code,
    )


async def pause_failed_watchdog_signal(
    session: AsyncSession,
    *,
    signal: WatchdogDue,
    paused_at: datetime,
    inactivity_timeout_seconds: int,
    failure_code: str,
) -> tuple[str, ...] | None:
    """Reread a failed preparation source, then pause every runnable lane."""

    candidate = await _read_failed_watchdog_candidate(
        session,
        signal=signal,
        paused_at=paused_at,
        inactivity_timeout_seconds=inactivity_timeout_seconds,
    )
    if candidate is None:
        return None
    return await _commit_watchdog_pause(
        session,
        task_id=candidate.task_id,
        current_team_revision_id=candidate.current_team_revision_id,
        dispatch_id=candidate.dispatch_id,
        assignment_id=candidate.assignment_id,
        attempt_id=candidate.attempt_id,
        member_id=candidate.member_id,
        control_revision=candidate.task_control_revision,
        source_is_current=_failed_watchdog_candidate_is_current(candidate, signal),
        paused_at=paused_at,
        pause_reason="runtime_transition_failed",
        failure_code=failure_code,
    )


async def _read_failed_watchdog_candidate(
    session: AsyncSession,
    *,
    signal: WatchdogDue,
    paused_at: datetime,
    inactivity_timeout_seconds: int,
) -> _FailedWatchdogCandidate | None:
    rows = await _select_failed_watchdog_rows(session, signal.dispatch_id)
    if rows is None:
        await session.rollback()
        return None
    dispatch, task, assignment, attempt, selection = rows
    if not _failed_watchdog_candidate_is_plausible(
        dispatch=dispatch,
        task=task,
        assignment=assignment,
        attempt=attempt,
        signal=signal,
    ) or await dispatch_owns_external_source(
        session,
        dispatch_id=dispatch.dispatch_id,
    ):
        await session.rollback()
        return None
    assert dispatch.adapter_started_at is not None
    due_at = calculate_watchdog_due_at(
        adapter_started_at=dispatch.adapter_started_at,
        last_node_activity_at=dispatch.last_node_activity_at,
        inactivity_timeout_seconds=inactivity_timeout_seconds,
    )
    if due_at != _as_utc(signal.due_at) or _as_utc(paused_at) < due_at:
        await session.rollback()
        return None
    candidate = _FailedWatchdogCandidate(
        dispatch_id=dispatch.dispatch_id,
        task_id=dispatch.task_id,
        assignment_id=dispatch.assignment_id,
        attempt_id=dispatch.attempt_id,
        source_team_revision_id=dispatch.team_revision_id,
        current_team_revision_id=selection.team_revision_id,
        member_id=dispatch.member_id,
        member_configuration_id=dispatch.member_configuration_id,
        member_branch_basis_id=dispatch.member_branch_basis_id,
        adapter_started_at=dispatch.adapter_started_at,
        last_node_activity_at=dispatch.last_node_activity_at,
        task_control_revision=task.control_revision,
    )
    await session.rollback()
    return candidate


async def _select_failed_watchdog_rows(
    session: AsyncSession,
    dispatch_id: str,
) -> _FailedWatchdogRows | None:
    row = (
        await session.execute(
            select(
                DispatchTurnModel,
                TaskModel,
                AssignmentModel,
                AttemptModel,
                TeamRevisionMemberModel,
            )
            .options(raiseload("*"))
            .join(TaskModel, TaskModel.task_id == DispatchTurnModel.task_id)
            .join(
                AssignmentModel,
                (AssignmentModel.task_id == DispatchTurnModel.task_id)
                & (AssignmentModel.assignment_id == DispatchTurnModel.assignment_id)
                & (AssignmentModel.member_id == DispatchTurnModel.member_id),
            )
            .join(
                AttemptModel,
                (AttemptModel.task_id == DispatchTurnModel.task_id)
                & (AttemptModel.assignment_id == DispatchTurnModel.assignment_id)
                & (AttemptModel.attempt_id == DispatchTurnModel.attempt_id),
            )
            .join(
                TeamRevisionMemberModel,
                (TeamRevisionMemberModel.task_id == DispatchTurnModel.task_id)
                & (TeamRevisionMemberModel.team_revision_id == TaskModel.current_team_revision_id)
                & (TeamRevisionMemberModel.member_id == DispatchTurnModel.member_id)
                & (
                    TeamRevisionMemberModel.member_configuration_id
                    == DispatchTurnModel.member_configuration_id
                )
                & (
                    TeamRevisionMemberModel.member_branch_basis_id
                    == DispatchTurnModel.member_branch_basis_id
                ),
            )
            .where(DispatchTurnModel.dispatch_id == dispatch_id)
        )
    ).one_or_none()
    if row is None:
        return None
    dispatch, task, assignment, attempt, selection = row
    return dispatch, task, assignment, attempt, selection


def _failed_watchdog_candidate_is_plausible(
    *,
    dispatch: DispatchTurnModel,
    task: TaskModel,
    assignment: AssignmentModel,
    attempt: AttemptModel,
    signal: WatchdogDue,
) -> bool:
    return (
        dispatch.status == "open"
        and dispatch.adapter_started_at is not None
        and dispatch.node_activity_revision == signal.activity_revision
        and task.status == "running"
        and assignment.current_attempt_id == attempt.attempt_id
        and assignment.terminal_outcome is None
        and attempt.status == "running"
        and attempt.current_dispatch_id == dispatch.dispatch_id
        and attempt.current_wait_id is None
    )


def _failed_watchdog_candidate_is_current(
    candidate: _FailedWatchdogCandidate,
    signal: WatchdogDue,
) -> ColumnElement[bool]:
    return (
        exists().where(
            TeamRevisionMemberModel.task_id == candidate.task_id,
            TeamRevisionMemberModel.team_revision_id == candidate.current_team_revision_id,
            TeamRevisionMemberModel.member_id == candidate.member_id,
            TeamRevisionMemberModel.member_configuration_id == candidate.member_configuration_id,
            TeamRevisionMemberModel.member_branch_basis_id == candidate.member_branch_basis_id,
        )
        & exists().where(
            AssignmentModel.task_id == candidate.task_id,
            AssignmentModel.assignment_id == candidate.assignment_id,
            AssignmentModel.member_id == candidate.member_id,
            AssignmentModel.current_attempt_id == candidate.attempt_id,
            AssignmentModel.terminal_outcome.is_(None),
        )
        & exists().where(
            AttemptModel.task_id == candidate.task_id,
            AttemptModel.assignment_id == candidate.assignment_id,
            AttemptModel.attempt_id == candidate.attempt_id,
            AttemptModel.status == "running",
            AttemptModel.current_dispatch_id == candidate.dispatch_id,
            AttemptModel.current_wait_id.is_(None),
        )
        & exists().where(
            DispatchTurnModel.dispatch_id == candidate.dispatch_id,
            DispatchTurnModel.task_id == candidate.task_id,
            DispatchTurnModel.assignment_id == candidate.assignment_id,
            DispatchTurnModel.attempt_id == candidate.attempt_id,
            DispatchTurnModel.team_revision_id == candidate.source_team_revision_id,
            DispatchTurnModel.member_id == candidate.member_id,
            DispatchTurnModel.member_configuration_id == candidate.member_configuration_id,
            DispatchTurnModel.member_branch_basis_id == candidate.member_branch_basis_id,
            DispatchTurnModel.status == "open",
            DispatchTurnModel.adapter_started_at == candidate.adapter_started_at,
            nullable_datetime_matches(
                DispatchTurnModel.last_node_activity_at,
                candidate.last_node_activity_at,
            ),
            DispatchTurnModel.node_activity_revision == signal.activity_revision,
        )
    )


async def _commit_watchdog_pause(
    session: AsyncSession,
    *,
    task_id: str,
    current_team_revision_id: str,
    dispatch_id: str,
    assignment_id: str,
    attempt_id: str,
    member_id: str,
    control_revision: int,
    source_is_current: ColumnElement[bool],
    paused_at: datetime,
    pause_reason: str,
    failure_code: str | None,
) -> tuple[str, ...] | None:
    details: dict[str, object] = {
        "source": "watchdog",
        "source_dispatch_id": dispatch_id,
    }
    if failure_code is not None:
        details["failure_code"] = failure_code
    updated_task_id = await session.scalar(
        update(TaskModel)
        .where(
            TaskModel.task_id == task_id,
            TaskModel.status == "running",
            TaskModel.current_team_revision_id == current_team_revision_id,
            TaskModel.control_revision == control_revision,
            source_is_current,
            dispatch_has_no_external_source(dispatch_id),
            dispatch_has_no_successor(dispatch_id),
        )
        .values(
            status="paused",
            pause_reason=pause_reason,
            pause_details=details,
            paused_at=paused_at,
            paused_by_actor_ref="controller.runtime",
            control_revision=TaskModel.control_revision + 1,
            updated_at=paused_at,
        )
        .returning(TaskModel.task_id)
    )
    if updated_task_id is None:
        await session.rollback()
        return None
    try:
        closed_dispatch_ids = await close_current_task_dispatches(
            session,
            task_id=task_id,
            closed_reason="paused",
            closed_at=paused_at,
            reason_overrides={dispatch_id: "control_failed"},
        )
    except TaskDispatchControlConflictError:
        await session.rollback()
        return None
    await _append_watchdog_pause_event(
        session,
        task_id=task_id,
        dispatch_id=dispatch_id,
        attempt_id=attempt_id,
        member_id=member_id,
        current_team_revision_id=current_team_revision_id,
        control_revision=control_revision + 1,
        paused_at=paused_at,
        pause_reason=pause_reason,
        details=details,
    )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return closed_dispatch_ids


async def _append_watchdog_pause_event(
    session: AsyncSession,
    *,
    task_id: str,
    dispatch_id: str,
    attempt_id: str,
    member_id: str,
    current_team_revision_id: str,
    control_revision: int,
    paused_at: datetime,
    pause_reason: str,
    details: dict[str, object],
) -> None:
    await append_task_event(
        session,
        task_id=task_id,
        event_type=TaskEventType.TASK_PAUSED,
        event_source=TaskEventSource.CONTROLLER,
        occurred_at=paused_at,
        team_revision_id=current_team_revision_id,
        dispatch_id=dispatch_id,
        attempt_id=attempt_id,
        member_id=member_id,
        actor_ref="controller.runtime",
        payload={
            "pause_reason": pause_reason,
            "control_revision": control_revision,
            "actor_ref": "controller.runtime",
            "summary": _pause_event_summary(pause_reason, details),
        },
    )


def _pause_event_summary(pause_reason: str, details: dict[str, object]) -> str:
    failure_code = details.get("failure_code")
    if isinstance(failure_code, str):
        return f"Runtime recovery paused the task: {failure_code}."
    return f"Runtime recovery paused the task: {pause_reason}."


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "pause_failed_watchdog_signal",
    "pause_watchdog_snapshot",
]
