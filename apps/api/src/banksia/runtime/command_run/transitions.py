from __future__ import annotations

import shlex
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from sqlalchemy import delete, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from banksia.persistence.models import (
    AttemptModel,
    AttemptWaitModel,
    CommandRunModel,
    FlowModel,
)
from banksia.runtime.contracts import (
    COMMAND_RUN_TERMINAL_EVENT_TYPES,
    CommandRunStartRequest,
    CommandRunState,
    TaskEventSource,
    TaskEventType,
)
from banksia.runtime.dispatch.currentness import (
    AttemptWaitIdentity,
    clear_current_attempt_wait,
)
from banksia.runtime.task_events import append_task_event


@dataclass(frozen=True, slots=True)
class CommandRunLaunchClaim:
    run_id: str
    task_id: str
    flow_id: str
    assignment_id: str
    attempt_id: str
    source_dispatch_id: str
    ownership_revision: int
    request: CommandRunStartRequest
    output_path: str


@dataclass(frozen=True, slots=True)
class CommandRunRunningResult:
    ownership_revision: int
    due_at: datetime | None


async def claim_command_run_launch(
    session: AsyncSession,
    *,
    run_id: str,
    owner_ref: str,
    claimed_at: datetime,
) -> CommandRunLaunchClaim | None:
    """Claim one never-owned pending run without launching inside the transaction."""

    source = await session.scalar(
        select(CommandRunModel)
        .options(raiseload("*"))
        .where(
            CommandRunModel.run_id == run_id,
            CommandRunModel.state == CommandRunState.PENDING_START.value,
            CommandRunModel.ownership_revision == 0,
            CommandRunModel.process_metadata_json.is_(None),
        )
    )
    if source is None:
        return None
    request = command_run_request_from_model(source)
    ownership_revision = source.ownership_revision + 1
    claimed_run_id = await session.scalar(
        update(CommandRunModel)
        .where(
            CommandRunModel.task_id == source.task_id,
            CommandRunModel.run_id == source.run_id,
            CommandRunModel.state == CommandRunState.PENDING_START.value,
            CommandRunModel.ownership_revision == source.ownership_revision,
            CommandRunModel.process_metadata_json.is_(None),
        )
        .values(
            ownership_revision=ownership_revision,
            process_metadata_json={
                "owner_ref": owner_ref,
                "phase": "launching",
                "claimed_at": claimed_at.isoformat(),
            },
        )
        .returning(CommandRunModel.run_id)
    )
    if claimed_run_id is None:
        await session.rollback()
        return None
    await session.commit()
    return CommandRunLaunchClaim(
        run_id=source.run_id,
        task_id=source.task_id,
        flow_id=source.flow_id,
        assignment_id=source.assignment_id,
        attempt_id=source.attempt_id,
        source_dispatch_id=source.source_dispatch_id,
        ownership_revision=ownership_revision,
        request=request,
        output_path=source.output_path,
    )


async def mark_command_run_running(
    session: AsyncSession,
    *,
    claim: CommandRunLaunchClaim,
    owner_ref: str,
    pid: int,
    started_at: datetime,
    due_at: datetime | None,
) -> CommandRunRunningResult | None:
    run_id = await session.scalar(
        update(CommandRunModel)
        .where(
            CommandRunModel.run_id == claim.run_id,
            CommandRunModel.task_id == claim.task_id,
            CommandRunModel.state == CommandRunState.PENDING_START.value,
            CommandRunModel.ownership_revision == claim.ownership_revision,
        )
        .values(
            state=CommandRunState.RUNNING.value,
            started_at=started_at,
            due_at=due_at,
            process_metadata_json={
                "owner_ref": owner_ref,
                "phase": "running",
                "pid": pid,
            },
        )
        .returning(CommandRunModel.run_id)
    )
    if run_id is None:
        await session.rollback()
        return None
    await append_task_event(
        session,
        task_id=claim.task_id,
        event_type=TaskEventType.COMMAND_RUN_STARTED,
        event_source=TaskEventSource.CONTROLLER,
        occurred_at=started_at,
        dispatch_id=claim.source_dispatch_id,
        attempt_id=claim.attempt_id,
        payload={
            "run_id": claim.run_id,
            "source_dispatch_id": claim.source_dispatch_id,
            "state": CommandRunState.RUNNING.value,
            "command": _command_display(claim.request),
            "description": claim.request.summary,
            "workdir": claim.request.cwd,
            "started_at": started_at,
            "ownership_revision": claim.ownership_revision,
            "due_at": due_at,
            "output_path": claim.output_path,
        },
    )
    await session.commit()
    return CommandRunRunningResult(
        ownership_revision=claim.ownership_revision,
        due_at=due_at,
    )


async def terminalize_command_run(
    session: AsyncSession,
    *,
    task_id: str,
    run_id: str,
    expected_ownership_revision: int,
    expected_states: tuple[CommandRunState, ...],
    terminal_state: CommandRunState,
    summary: str,
    ended_at: datetime,
    exit_code: int | None = None,
    failure_code: str | None = None,
    expected_due_at: datetime | None = None,
    should_match_due_at: bool = False,
    event_source: TaskEventSource = TaskEventSource.CONTROLLER,
    actor_ref: str | None = None,
    output_observed_bytes: int | None = None,
    output_written_bytes: int | None = None,
    output_complete: bool | None = None,
) -> bool:
    """Commit one exact terminal winner and clear only its matching Attempt wait."""

    event_type = _validate_terminal_transition(terminal_state, failure_code)
    source = await _read_terminal_source(
        session,
        task_id=task_id,
        run_id=run_id,
        expected_ownership_revision=expected_ownership_revision,
        expected_states=expected_states,
    )
    if source is None or (should_match_due_at and source.due_at != expected_due_at):
        return False
    source_state = CommandRunState(source.state)
    if not await _persist_terminal_state(
        session,
        source=source,
        expected_ownership_revision=expected_ownership_revision,
        expected_states=expected_states,
        terminal_state=terminal_state,
        summary=summary,
        ended_at=ended_at,
        exit_code=exit_code,
        failure_code=failure_code,
        expected_due_at=expected_due_at,
        should_match_due_at=should_match_due_at,
        actor_ref=actor_ref,
        output_observed_bytes=output_observed_bytes,
        output_written_bytes=output_written_bytes,
        output_complete=output_complete,
    ):
        await session.rollback()
        return False
    wait_cleared = await _clear_matching_attempt_wait(session, source)
    if not wait_cleared and not await _cancelled_owner_accepts_terminal_state(
        session,
        source=source,
        source_state=source_state,
        terminal_state=terminal_state,
        expected_ownership_revision=expected_ownership_revision,
    ):
        await session.rollback()
        return False

    await _append_terminal_event(
        session,
        source=source,
        event_type=event_type,
        event_source=event_source,
        terminal_state=terminal_state,
        summary=summary,
        ended_at=ended_at,
        exit_code=exit_code,
        failure_code=failure_code,
        expected_ownership_revision=expected_ownership_revision,
        actor_ref=actor_ref,
        output_observed_bytes=(
            source.output_observed_bytes if output_observed_bytes is None else output_observed_bytes
        ),
        output_written_bytes=(
            source.output_written_bytes if output_written_bytes is None else output_written_bytes
        ),
        output_complete=(source.output_complete if output_complete is None else output_complete),
    )
    await session.commit()
    return True


def command_run_request_from_model(source: CommandRunModel) -> CommandRunStartRequest:
    cwd: str | None = None
    if source.cwd_policy_json is not None:
        if set(source.cwd_policy_json) != {"logical_path"}:
            raise ValueError("command cwd policy has an invalid shape")
        logical_path = source.cwd_policy_json["logical_path"]
        if not isinstance(logical_path, str):
            raise ValueError("command cwd policy requires a text logical path")
        cwd = logical_path
    return CommandRunStartRequest.model_validate(
        {
            "command": source.command_spec_json,
            "cwd": cwd,
            "timeout_seconds": source.timeout_seconds,
            "summary": source.summary,
        }
    )


def _validate_terminal_transition(
    terminal_state: CommandRunState,
    failure_code: str | None,
) -> TaskEventType:
    event_type = COMMAND_RUN_TERMINAL_EVENT_TYPES.get(terminal_state)
    if event_type is None:
        raise ValueError(f"command state is not terminal: {terminal_state.value}")
    if terminal_state == CommandRunState.ABANDONED and failure_code != "command_ownership_lost":
        raise ValueError("abandoned command runs require command_ownership_lost")
    return event_type


async def _read_terminal_source(
    session: AsyncSession,
    *,
    task_id: str,
    run_id: str,
    expected_ownership_revision: int,
    expected_states: tuple[CommandRunState, ...],
) -> CommandRunModel | None:
    return cast(
        CommandRunModel | None,
        await session.scalar(
            select(CommandRunModel)
            .options(raiseload("*"))
            .where(
                CommandRunModel.task_id == task_id,
                CommandRunModel.run_id == run_id,
                CommandRunModel.ownership_revision == expected_ownership_revision,
                CommandRunModel.state.in_(state.value for state in expected_states),
            )
        ),
    )


async def _persist_terminal_state(
    session: AsyncSession,
    *,
    source: CommandRunModel,
    expected_ownership_revision: int,
    expected_states: tuple[CommandRunState, ...],
    terminal_state: CommandRunState,
    summary: str,
    ended_at: datetime,
    exit_code: int | None,
    failure_code: str | None,
    expected_due_at: datetime | None,
    should_match_due_at: bool,
    actor_ref: str | None,
    output_observed_bytes: int | None,
    output_written_bytes: int | None,
    output_complete: bool | None,
) -> bool:
    predicates = [
        CommandRunModel.task_id == source.task_id,
        CommandRunModel.run_id == source.run_id,
        CommandRunModel.ownership_revision == expected_ownership_revision,
        CommandRunModel.state.in_(state.value for state in expected_states),
    ]
    if should_match_due_at:
        predicates.append(CommandRunModel.due_at == expected_due_at)
    output_values: dict[str, object] = {}
    if output_observed_bytes is not None:
        if output_written_bytes is None or output_complete is None:
            raise ValueError("command output terminal facts must be supplied together")
        if output_written_bytes > output_observed_bytes:
            raise ValueError("command output written bytes cannot exceed observed bytes")
        if output_complete and output_written_bytes != output_observed_bytes:
            raise ValueError("complete command output requires every observed byte to be written")
        output_values = {
            "output_observed_bytes": output_observed_bytes,
            "output_written_bytes": output_written_bytes,
            "output_complete": output_complete,
        }
    elif output_written_bytes is not None or output_complete is not None:
        raise ValueError("command output terminal facts must be supplied together")

    won_run_id = await session.scalar(
        update(CommandRunModel)
        .where(*predicates)
        .values(
            state=terminal_state.value,
            ended_at=ended_at,
            terminal_summary=summary,
            terminal_exit_code=exit_code,
            terminal_failure_code=failure_code,
            terminal_event_source="process_owner",
            terminal_actor_ref=actor_ref,
            process_metadata_json=None,
            **output_values,
        )
        .returning(CommandRunModel.run_id)
    )
    return won_run_id is not None


async def _clear_matching_attempt_wait(
    session: AsyncSession,
    source: CommandRunModel,
) -> bool:
    wait_id = await session.scalar(
        select(AttemptWaitModel.wait_id).where(
            AttemptWaitModel.task_id == source.task_id,
            AttemptWaitModel.flow_id == source.flow_id,
            AttemptWaitModel.assignment_id == source.assignment_id,
            AttemptWaitModel.attempt_id == source.attempt_id,
            AttemptWaitModel.source_dispatch_id == source.source_dispatch_id,
            AttemptWaitModel.command_run_id == source.run_id,
            AttemptWaitModel.human_request_id.is_(None),
            AttemptWaitModel.delegation_wave_id.is_(None),
        )
    )
    if wait_id is None:
        return False
    if not await clear_current_attempt_wait(
        session,
        identity=AttemptWaitIdentity(
            task_id=source.task_id,
            flow_id=source.flow_id,
            assignment_id=source.assignment_id,
            attempt_id=source.attempt_id,
            wait_id=wait_id,
        ),
    ):
        return False
    deleted_wait_id = await session.scalar(
        delete(AttemptWaitModel)
        .where(
            AttemptWaitModel.wait_id == wait_id,
            AttemptWaitModel.task_id == source.task_id,
            AttemptWaitModel.flow_id == source.flow_id,
            AttemptWaitModel.assignment_id == source.assignment_id,
            AttemptWaitModel.attempt_id == source.attempt_id,
            AttemptWaitModel.source_dispatch_id == source.source_dispatch_id,
            AttemptWaitModel.command_run_id == source.run_id,
            AttemptWaitModel.human_request_id.is_(None),
            AttemptWaitModel.delegation_wave_id.is_(None),
        )
        .returning(AttemptWaitModel.wait_id)
    )
    return deleted_wait_id is not None


async def _cancelled_owner_accepts_terminal_state(
    session: AsyncSession,
    *,
    source: CommandRunModel,
    source_state: CommandRunState,
    terminal_state: CommandRunState,
    expected_ownership_revision: int,
) -> bool:
    """Accept exact late process truth only after Task cancellation won the wait."""

    if source_state != CommandRunState.CANCELLATION_REQUESTED or terminal_state not in {
        CommandRunState.CANCELLED,
        CommandRunState.ABANDONED,
    }:
        return False
    owner_attempt_id = await session.scalar(
        select(AttemptModel.attempt_id)
        .join(
            FlowModel,
            (FlowModel.task_id == AttemptModel.task_id)
            & (FlowModel.flow_id == AttemptModel.flow_id),
        )
        .where(
            FlowModel.task_id == source.task_id,
            FlowModel.flow_id == source.flow_id,
            FlowModel.status == "cancelled",
            AttemptModel.task_id == source.task_id,
            AttemptModel.flow_id == source.flow_id,
            AttemptModel.assignment_id == source.assignment_id,
            AttemptModel.attempt_id == source.attempt_id,
            AttemptModel.status == "cancelled",
            AttemptModel.current_dispatch_id.is_(None),
            AttemptModel.current_wait_id.is_(None),
            exists().where(
                CommandRunModel.task_id == source.task_id,
                CommandRunModel.run_id == source.run_id,
                CommandRunModel.flow_id == source.flow_id,
                CommandRunModel.assignment_id == source.assignment_id,
                CommandRunModel.attempt_id == source.attempt_id,
                CommandRunModel.source_dispatch_id == source.source_dispatch_id,
                CommandRunModel.state == terminal_state.value,
                CommandRunModel.ownership_revision == expected_ownership_revision,
                CommandRunModel.successor_dispatch_id.is_(None),
            ),
            ~exists(
                select(AttemptWaitModel.wait_id).where(
                    AttemptWaitModel.task_id == source.task_id,
                    AttemptWaitModel.flow_id == source.flow_id,
                    AttemptWaitModel.assignment_id == source.assignment_id,
                    AttemptWaitModel.attempt_id == source.attempt_id,
                    AttemptWaitModel.source_dispatch_id == source.source_dispatch_id,
                    AttemptWaitModel.command_run_id == source.run_id,
                )
            ),
        )
        .limit(1)
    )
    return owner_attempt_id is not None


async def _append_terminal_event(
    session: AsyncSession,
    *,
    source: CommandRunModel,
    event_type: TaskEventType,
    event_source: TaskEventSource,
    terminal_state: CommandRunState,
    summary: str,
    ended_at: datetime,
    exit_code: int | None,
    failure_code: str | None,
    expected_ownership_revision: int,
    actor_ref: str | None,
    output_observed_bytes: int,
    output_written_bytes: int,
    output_complete: bool,
) -> None:
    await append_task_event(
        session,
        task_id=source.task_id,
        event_type=event_type,
        event_source=event_source,
        occurred_at=ended_at,
        dispatch_id=source.source_dispatch_id,
        attempt_id=source.attempt_id,
        actor_ref=actor_ref,
        payload={
            "run_id": source.run_id,
            "source_dispatch_id": source.source_dispatch_id,
            "state": terminal_state.value,
            "summary": summary,
            "started_at": source.started_at,
            "ended_at": ended_at,
            "exit_code": exit_code,
            "failure_code": failure_code,
            "ownership_revision": expected_ownership_revision,
            "output_path": source.output_path,
            "output_observed_bytes": output_observed_bytes,
            "output_written_bytes": output_written_bytes,
            "output_complete": output_complete,
            "output_encoding": source.output_encoding,
        },
    )


def _command_display(request: CommandRunStartRequest) -> str:
    if request.command.kind == "argv":
        return shlex.join(request.command.argv)
    return request.command.command


__all__ = [
    "CommandRunLaunchClaim",
    "CommandRunRunningResult",
    "claim_command_run_launch",
    "command_run_request_from_model",
    "mark_command_run_running",
    "terminalize_command_run",
]
