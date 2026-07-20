from __future__ import annotations

import shlex
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from autoclaw.persistence.models import CommandRunModel, FlowModel, FlowWaitModel
from autoclaw.runtime.contracts import (
    COMMAND_RUN_TERMINAL_EVENT_TYPES,
    CommandRunStartRequest,
    CommandRunState,
    TaskEventSource,
    TaskEventType,
)
from autoclaw.runtime.task_events import append_task_event


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
    stdout_log_ref: str
    stderr_log_ref: str


@dataclass(frozen=True, slots=True)
class CommandRunRunningResult:
    ownership_revision: int
    due_at: datetime | None


async def claim_command_run_launch(
    session: AsyncSession,
    *,
    run_id: str,
    owner_ref: str,
    stdout_log_ref: str,
    stderr_log_ref: str,
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
        stdout_log_ref=stdout_log_ref,
        stderr_log_ref=stderr_log_ref,
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
            stdout_logical_path=claim.stdout_log_ref,
            stderr_logical_path=claim.stderr_log_ref,
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
            "log_refs": [claim.stdout_log_ref, claim.stderr_log_ref],
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
) -> bool:
    """Commit one exact terminal winner and clear only its matching flow wait."""

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
    ):
        await session.rollback()
        return False
    if not await _clear_matching_flow_wait(session, source):
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
            "environment": source.environment_refs_json or (),
            "timeout_seconds": source.timeout_seconds,
            "summary": source.summary,
            "expected_outputs": source.expected_outputs_json or (),
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
) -> bool:
    predicates = [
        CommandRunModel.task_id == source.task_id,
        CommandRunModel.run_id == source.run_id,
        CommandRunModel.ownership_revision == expected_ownership_revision,
        CommandRunModel.state.in_(state.value for state in expected_states),
    ]
    if should_match_due_at:
        predicates.append(CommandRunModel.due_at == expected_due_at)
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
        )
        .returning(CommandRunModel.run_id)
    )
    return won_run_id is not None


async def _clear_matching_flow_wait(
    session: AsyncSession,
    source: CommandRunModel,
) -> bool:
    wait_id = await session.scalar(
        delete(FlowWaitModel)
        .where(
            FlowWaitModel.flow_id == source.flow_id,
            FlowWaitModel.task_id == source.task_id,
            FlowWaitModel.source_dispatch_id == source.source_dispatch_id,
            FlowWaitModel.command_run_id == source.run_id,
        )
        .returning(FlowWaitModel.flow_id)
    )
    flow = await session.scalar(
        select(FlowModel)
        .options(raiseload("*"))
        .where(
            FlowModel.flow_id == source.flow_id,
            FlowModel.task_id == source.task_id,
        )
    )
    if flow is None or (
        wait_id is None
        and flow.status not in {"cancelled", "completed"}
        and flow.waiting_source_id == source.run_id
    ):
        return False

    await session.execute(
        update(FlowModel)
        .where(
            FlowModel.flow_id == source.flow_id,
            FlowModel.task_id == source.task_id,
            FlowModel.waiting_cause == "command_run",
            FlowModel.waiting_source_id == source.run_id,
        )
        .values(
            waiting_cause="none",
            waiting_source_id=None,
            control_revision=FlowModel.control_revision + 1,
        )
    )
    return True


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
            "log_refs": [
                ref
                for ref in (source.stdout_logical_path, source.stderr_logical_path)
                if ref is not None
            ],
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
