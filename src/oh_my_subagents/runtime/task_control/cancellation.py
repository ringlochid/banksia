"""Task cancellation row transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from oh_my_subagents.persistence.models import (
    AttemptModel,
    AttemptWaitModel,
    DelegationWaveMemberModel,
    DelegationWaveModel,
    HumanRequestModel,
    TaskModel,
)
from oh_my_subagents.runtime.command_run.service import request_command_run_cancellation
from oh_my_subagents.runtime.contracts import (
    HumanRequestResolutionSurface,
    TaskEventSource,
    TaskEventType,
)
from oh_my_subagents.runtime.contracts.operation_failure import OperationFailureCode
from oh_my_subagents.runtime.dispatch.currentness import (
    AttemptWaitIdentity,
    clear_current_attempt_wait,
)
from oh_my_subagents.runtime.errors import RuntimeOperationError, illegal_state_error
from oh_my_subagents.runtime.post_commit import (
    CommandRunCancellationRequested,
    HumanRequestTerminal,
)
from oh_my_subagents.runtime.task_events import append_task_event


@dataclass(frozen=True, slots=True)
class CancellationSignals:
    """Exact post-commit source signals collected in stable Attempt order."""

    human: tuple[HumanRequestTerminal, ...]
    command: tuple[CommandRunCancellationRequested, ...]


async def cancel_execution_rows(
    session: AsyncSession,
    *,
    task: TaskModel,
    cancelled_at: datetime,
) -> None:
    await session.execute(
        update(DelegationWaveModel)
        .where(
            DelegationWaveModel.task_id == task.task_id,
            DelegationWaveModel.status.in_(("open", "settled")),
            DelegationWaveModel.successor_dispatch_id.is_(None),
        )
        .values(status="cancelled", cancelled_at=cancelled_at)
    )
    await session.execute(
        update(DelegationWaveMemberModel)
        .where(
            DelegationWaveMemberModel.task_id == task.task_id,
            DelegationWaveMemberModel.status == "pending",
        )
        .values(status="cancelled", cancelled_at=cancelled_at)
    )
    await session.execute(
        update(AttemptModel)
        .where(
            AttemptModel.task_id == task.task_id,
            AttemptModel.status.in_(("pending", "running")),
        )
        .values(
            status="cancelled",
            terminal_outcome=None,
            current_dispatch_id=None,
            current_wait_id=None,
            closed_at=cancelled_at,
        )
    )


async def cancel_attempt_waits(
    session: AsyncSession,
    *,
    task: TaskModel,
    actor_ref: str | None,
    event_source: TaskEventSource,
    cancelled_at: datetime,
) -> CancellationSignals:
    """Settle and delete every current Attempt wait after global cancellation wins."""

    waits = await _read_current_attempt_waits(session, task)
    human_signals: list[HumanRequestTerminal] = []
    command_signals: list[CommandRunCancellationRequested] = []
    for wait in waits:
        human_signal, command_signal = await _cancel_attempt_wait_source(
            session,
            task=task,
            wait=wait,
            actor_ref=actor_ref,
            event_source=event_source,
            cancelled_at=cancelled_at,
        )
        if human_signal is not None:
            human_signals.append(human_signal)
        if command_signal is not None:
            command_signals.append(command_signal)
        await _clear_and_delete_attempt_wait(session, wait)
    await _ensure_no_attempt_waits_remain(session, task)
    return CancellationSignals(
        human=tuple(human_signals),
        command=tuple(command_signals),
    )


async def _read_current_attempt_waits(
    session: AsyncSession,
    task: TaskModel,
) -> tuple[AttemptWaitModel, ...]:
    waits = (
        await session.scalars(
            select(AttemptWaitModel)
            .options(raiseload("*"))
            .join(
                AttemptModel,
                (AttemptModel.task_id == AttemptWaitModel.task_id)
                & (AttemptModel.assignment_id == AttemptWaitModel.assignment_id)
                & (AttemptModel.attempt_id == AttemptWaitModel.attempt_id)
                & (AttemptModel.current_wait_id == AttemptWaitModel.wait_id),
            )
            .where(
                AttemptWaitModel.task_id == task.task_id,
                AttemptModel.status == "running",
                AttemptModel.current_dispatch_id.is_(None),
            )
            .order_by(
                AttemptWaitModel.assignment_id,
                AttemptWaitModel.attempt_id,
                AttemptWaitModel.wait_id,
            )
        )
    ).all()
    return tuple(waits)


async def _cancel_attempt_wait_source(
    session: AsyncSession,
    *,
    task: TaskModel,
    wait: AttemptWaitModel,
    actor_ref: str | None,
    event_source: TaskEventSource,
    cancelled_at: datetime,
) -> tuple[HumanRequestTerminal | None, CommandRunCancellationRequested | None]:
    if wait.human_request_id is not None:
        request_id = await _cancel_human_request(
            session,
            task=task,
            wait=wait,
            actor_ref=actor_ref,
            event_source=event_source,
            cancelled_at=cancelled_at,
        )
        return HumanRequestTerminal(request_id=request_id), None
    if wait.command_run_id is not None:
        signal = await _request_waiting_command_cancellation(
            session,
            task=task,
            wait=wait,
            actor_ref=actor_ref,
            event_source=event_source,
        )
        return None, signal
    if wait.delegation_wave_id is not None:
        await _cancel_waiting_delegation_wave(
            session,
            task=task,
            wait=wait,
            cancelled_at=cancelled_at,
        )
        return None, None
    raise illegal_state_error("Attempt wait has no typed source")


async def _clear_and_delete_attempt_wait(
    session: AsyncSession,
    wait: AttemptWaitModel,
) -> None:
    cleared = await clear_current_attempt_wait(
        session,
        identity=AttemptWaitIdentity(
            task_id=wait.task_id,
            assignment_id=wait.assignment_id,
            attempt_id=wait.attempt_id,
            wait_id=wait.wait_id,
        ),
    )
    if not cleared:
        raise _task_control_conflict("an Attempt wait changed before task cancellation")
    deleted_wait_id = await session.scalar(
        delete(AttemptWaitModel)
        .where(
            AttemptWaitModel.wait_id == wait.wait_id,
            AttemptWaitModel.task_id == wait.task_id,
            AttemptWaitModel.assignment_id == wait.assignment_id,
            AttemptWaitModel.attempt_id == wait.attempt_id,
            AttemptWaitModel.source_dispatch_id == wait.source_dispatch_id,
        )
        .returning(AttemptWaitModel.wait_id)
    )
    if deleted_wait_id is None:
        raise _task_control_conflict("an Attempt wait changed before task cancellation")


async def _ensure_no_attempt_waits_remain(
    session: AsyncSession,
    task: TaskModel,
) -> None:
    residual_wait_id = await session.scalar(
        select(AttemptWaitModel.wait_id)
        .where(
            AttemptWaitModel.task_id == task.task_id,
        )
        .limit(1)
    )
    if residual_wait_id is not None:
        raise illegal_state_error("task cancellation did not settle every Attempt wait")


async def _cancel_waiting_delegation_wave(
    session: AsyncSession,
    *,
    task: TaskModel,
    wait: AttemptWaitModel,
    cancelled_at: datetime,
) -> None:
    wave_id = wait.delegation_wave_id
    if wave_id is None:
        raise illegal_state_error("Attempt Delegation Wave wait source is missing")
    cancelled = await session.scalar(
        update(DelegationWaveModel)
        .where(
            DelegationWaveModel.delegation_wave_id == wave_id,
            DelegationWaveModel.task_id == task.task_id,
            DelegationWaveModel.parent_assignment_id == wait.assignment_id,
            DelegationWaveModel.parent_attempt_id == wait.attempt_id,
            DelegationWaveModel.source_dispatch_id == wait.source_dispatch_id,
            DelegationWaveModel.status == "open",
            DelegationWaveModel.successor_dispatch_id.is_(None),
        )
        .values(status="cancelled", cancelled_at=cancelled_at)
        .returning(DelegationWaveModel.delegation_wave_id)
    )
    if cancelled is None:
        raise _task_control_conflict("the waiting Delegation Wave changed before task cancellation")
    await session.execute(
        update(DelegationWaveMemberModel)
        .where(
            DelegationWaveMemberModel.delegation_wave_id == wave_id,
            DelegationWaveMemberModel.task_id == task.task_id,
            DelegationWaveMemberModel.status == "pending",
        )
        .values(status="cancelled", cancelled_at=cancelled_at)
    )


async def _cancel_human_request(
    session: AsyncSession,
    *,
    task: TaskModel,
    wait: AttemptWaitModel,
    actor_ref: str | None,
    event_source: TaskEventSource,
    cancelled_at: datetime,
) -> str:
    request_id = wait.human_request_id
    if request_id is None:
        raise illegal_state_error("Attempt human-request wait source is missing")
    source = await session.scalar(
        select(HumanRequestModel)
        .options(raiseload("*"))
        .where(
            HumanRequestModel.request_id == request_id,
            HumanRequestModel.task_id == task.task_id,
            HumanRequestModel.assignment_id == wait.assignment_id,
            HumanRequestModel.attempt_id == wait.attempt_id,
            HumanRequestModel.source_dispatch_id == wait.source_dispatch_id,
            HumanRequestModel.status == "open",
            HumanRequestModel.successor_dispatch_id.is_(None),
        )
    )
    if source is None:
        raise _task_control_conflict("the waiting human request changed before task cancellation")
    changed = await session.scalar(
        update(HumanRequestModel)
        .where(
            HumanRequestModel.request_id == request_id,
            HumanRequestModel.task_id == task.task_id,
            HumanRequestModel.assignment_id == wait.assignment_id,
            HumanRequestModel.attempt_id == wait.attempt_id,
            HumanRequestModel.source_dispatch_id == wait.source_dispatch_id,
            HumanRequestModel.status == "open",
            HumanRequestModel.successor_dispatch_id.is_(None),
        )
        .values(
            status="cancelled",
            resolution_kind="cancelled",
            item_responses_json=None,
            resolution_summary="Cancelled because the task was cancelled.",
            resolved_by_actor_ref=actor_ref,
            resolved_by_surface=_human_resolution_surface(event_source).value,
            resolved_at=cancelled_at,
        )
        .returning(HumanRequestModel.request_id)
    )
    if changed is None:
        raise _task_control_conflict("the waiting human request changed before task cancellation")
    await _append_human_request_cancelled_event(
        session,
        task=task,
        wait=wait,
        source=source,
        actor_ref=actor_ref,
        event_source=event_source,
        cancelled_at=cancelled_at,
    )
    return request_id


async def _append_human_request_cancelled_event(
    session: AsyncSession,
    *,
    task: TaskModel,
    wait: AttemptWaitModel,
    source: HumanRequestModel,
    actor_ref: str | None,
    event_source: TaskEventSource,
    cancelled_at: datetime,
) -> None:
    await append_task_event(
        session,
        task_id=task.task_id,
        event_type=TaskEventType.HUMAN_REQUEST_CANCELLED,
        event_source=event_source,
        occurred_at=cancelled_at,
        team_revision_id=task.current_team_revision_id,
        dispatch_id=wait.source_dispatch_id,
        actor_ref=actor_ref,
        payload={
            "request_id": source.request_id,
            "kind": source.request_kind,
            "summary": source.request_summary,
            "source_dispatch_id": source.source_dispatch_id,
            "due_at": source.due_at,
            "status": "cancelled",
            "resolution_kind": "cancelled",
            "resolution_summary": "Cancelled because the task was cancelled.",
            "resolved_at": cancelled_at,
            "resolved_by_surface": _human_resolution_surface(event_source).value,
            "resolved_by_actor_ref": actor_ref,
        },
    )


async def _request_waiting_command_cancellation(
    session: AsyncSession,
    *,
    task: TaskModel,
    wait: AttemptWaitModel,
    actor_ref: str | None,
    event_source: TaskEventSource,
) -> CommandRunCancellationRequested | None:
    run_id = wait.command_run_id
    if run_id is None:
        raise illegal_state_error("Attempt command-run wait source is missing")
    source, _ = await request_command_run_cancellation(
        session,
        task_id=task.task_id,
        run_id=run_id,
        actor_ref=actor_ref,
        event_source=event_source,
        is_already_requested_allowed=True,
        is_cancelled_task_allowed=True,
    )
    return CommandRunCancellationRequested(
        run_id=source.run_id,
        ownership_revision=source.ownership_revision,
    )


def _human_resolution_surface(event_source: TaskEventSource) -> HumanRequestResolutionSurface:
    if event_source == TaskEventSource.OPERATOR:
        return HumanRequestResolutionSurface.OPERATOR
    if event_source == TaskEventSource.CONTROL_API:
        return HumanRequestResolutionSurface.CONTROL_API
    return HumanRequestResolutionSurface.CONTROLLER


def _task_control_conflict(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary=summary,
        is_retryable=False,
        suggested_next_step="Reread the task and retry only against its current revisions.",
    )


__all__ = [
    "CancellationSignals",
    "cancel_attempt_waits",
    "cancel_execution_rows",
]
