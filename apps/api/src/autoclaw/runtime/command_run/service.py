from __future__ import annotations

import logging
import shlex
from typing import cast

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload
from sqlalchemy.sql.elements import ColumnElement

from autoclaw.persistence.models import CommandRunModel, FlowModel, FlowWaitModel
from autoclaw.runtime.clock import utc_now
from autoclaw.runtime.contracts import (
    TERMINAL_COMMAND_RUN_STATES,
    CommandRunCancelResponse,
    CommandRunListItem,
    CommandRunListResponse,
    CommandRunLogReadResponse,
    CommandRunRecord,
    CommandRunStartRequest,
    CommandRunState,
    CommandRunTerminalResult,
    CommandRunTerminalSource,
    TaskEventSource,
    TaskEventType,
)
from autoclaw.runtime.contracts.command_runs import CommandRunTerminalState
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.errors import RuntimeOperationError, missing_resource_error
from autoclaw.runtime.post_commit import (
    CommandRunCancellationRequested,
    RuntimeEffectPublisher,
)
from autoclaw.runtime.task_events import append_task_event
from autoclaw.runtime.task_root import read_logical_text_file, read_task_root_paths

logger = logging.getLogger(__name__)

_MAX_COMMAND_RUN_PAGE_SIZE = 200
_MAX_COMMAND_LOG_READ_BYTES = 1_048_576
_COMMAND_CONFLICT_NEXT_STEP = "Reread the exact command-run source before retrying."


async def list_command_runs(
    session: AsyncSession,
    *,
    task_id: str,
    cursor: str | None = None,
    limit: int = 100,
) -> CommandRunListResponse:
    await _require_task_flow_exists(session, task_id)
    if not 1 <= limit <= _MAX_COMMAND_RUN_PAGE_SIZE:
        raise ValueError(f"command run limit must be between 1 and {_MAX_COMMAND_RUN_PAGE_SIZE}")

    statement = (
        select(CommandRunModel)
        .options(raiseload("*"))
        .where(CommandRunModel.task_id == task_id)
        .order_by(CommandRunModel.created_at.desc(), CommandRunModel.run_id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        cursor_source = await session.scalar(
            select(CommandRunModel)
            .options(raiseload("*"))
            .where(
                CommandRunModel.task_id == task_id,
                CommandRunModel.run_id == cursor,
            )
        )
        if cursor_source is None:
            raise _command_run_conflict("command run cursor is stale or unknown")
        statement = statement.where(
            or_(
                CommandRunModel.created_at < cursor_source.created_at,
                and_(
                    CommandRunModel.created_at == cursor_source.created_at,
                    CommandRunModel.run_id < cursor_source.run_id,
                ),
            )
        )

    rows = list(await session.scalars(statement))
    page = rows[:limit]
    return CommandRunListResponse(
        task_id=task_id,
        items=tuple(command_run_list_item_from_model(source) for source in page),
        next_cursor=page[-1].run_id if len(rows) > limit else None,
    )


async def read_command_run(
    session: AsyncSession,
    *,
    task_id: str,
    run_id: str,
) -> CommandRunRecord:
    source = await _command_run_for_task(session, task_id=task_id, run_id=run_id)
    if source is None:
        raise missing_resource_error(f"unknown command run '{run_id}' for task '{task_id}'")
    return command_run_record_from_model(source)


async def read_command_run_log(
    session: AsyncSession,
    *,
    task_id: str,
    run_id: str,
) -> CommandRunLogReadResponse:
    source = await _command_run_for_task(session, task_id=task_id, run_id=run_id)
    if source is None:
        raise missing_resource_error(f"unknown command run '{run_id}' for task '{task_id}'")
    log_ref = _preferred_log_ref(source)
    if log_ref is None:
        raise missing_resource_error(f"command run '{run_id}' has no available log")
    paths = await read_task_root_paths(session, task_id)
    _, content, _, _, _ = read_logical_text_file(
        paths,
        log_ref,
        start_line=1,
        max_lines=1_000_000,
        byte_limit=_MAX_COMMAND_LOG_READ_BYTES,
    )
    return CommandRunLogReadResponse(
        task_id=task_id,
        run_id=run_id,
        log_ref=log_ref,
        content=content,
    )


async def cancel_command_run(
    session: AsyncSession,
    *,
    task_id: str,
    run_id: str,
    actor_ref: str | None = None,
    event_source: TaskEventSource = TaskEventSource.CONTROL_API,
    runtime_effect_publisher: RuntimeEffectPublisher | None = None,
) -> CommandRunCancelResponse:
    source, changed = await request_command_run_cancellation(
        session,
        task_id=task_id,
        run_id=run_id,
        actor_ref=actor_ref,
        event_source=event_source,
        is_already_requested_allowed=True,
    )
    await session.commit()
    if changed:
        _publish_command_cancellation(
            run_id=source.run_id,
            ownership_revision=source.ownership_revision,
            runtime_effect_publisher=runtime_effect_publisher,
        )
    return CommandRunCancelResponse(
        task_id=task_id,
        run=command_run_list_item_from_model(source),
    )


async def request_command_run_cancellation(
    session: AsyncSession,
    *,
    task_id: str,
    run_id: str,
    actor_ref: str | None = None,
    event_source: TaskEventSource = TaskEventSource.CONTROL_API,
    is_already_requested_allowed: bool = False,
) -> tuple[CommandRunModel, bool]:
    """Request exact-run cancellation without committing the caller's transaction."""

    source = await _command_run_for_task(session, task_id=task_id, run_id=run_id)
    if source is None:
        raise missing_resource_error(f"unknown command run '{run_id}' for task '{task_id}'")
    state = CommandRunState(source.state)
    if state in TERMINAL_COMMAND_RUN_STATES:
        return source, False
    if not await session.scalar(select(_current_command_wait_exists(source))):
        raise _command_run_conflict(
            f"command run '{run_id}' no longer owns the task's exact current wait"
        )
    if state == CommandRunState.CANCELLATION_REQUESTED:
        if is_already_requested_allowed:
            return source, False
        raise _command_run_conflict(f"command run '{run_id}' already has cancellation requested")
    if state not in {CommandRunState.PENDING_START, CommandRunState.RUNNING}:
        raise _command_run_conflict(
            f"command run '{run_id}' cannot be cancelled from {state.value}"
        )

    requested_at = utc_now()
    won_run_id = await session.scalar(
        update(CommandRunModel)
        .where(
            CommandRunModel.task_id == task_id,
            CommandRunModel.run_id == run_id,
            CommandRunModel.state == state.value,
            CommandRunModel.ownership_revision == source.ownership_revision,
            _current_command_wait_exists(source),
        )
        .values(
            state=CommandRunState.CANCELLATION_REQUESTED.value,
            cancellation_requested_at=requested_at,
            cancellation_requested_by_actor_ref=actor_ref,
        )
        .returning(CommandRunModel.run_id)
    )
    if won_run_id is None:
        await session.rollback()
        raise _command_run_conflict(f"command run '{run_id}' changed before cancellation")
    await append_task_event(
        session,
        task_id=source.task_id,
        event_type=TaskEventType.COMMAND_RUN_CANCEL_REQUESTED,
        event_source=event_source,
        occurred_at=requested_at,
        dispatch_id=source.source_dispatch_id,
        attempt_id=source.attempt_id,
        actor_ref=actor_ref,
        payload={
            "run_id": source.run_id,
            "source_dispatch_id": source.source_dispatch_id,
            "state": CommandRunState.CANCELLATION_REQUESTED.value,
            "requested_at": requested_at,
            "ownership_revision": source.ownership_revision,
        },
    )
    source.state = CommandRunState.CANCELLATION_REQUESTED.value
    source.cancellation_requested_at = requested_at
    source.cancellation_requested_by_actor_ref = actor_ref
    return source, True


def command_run_record_from_model(source: CommandRunModel) -> CommandRunRecord:
    return CommandRunRecord(
        run_id=source.run_id,
        task_id=source.task_id,
        flow_id=source.flow_id,
        assignment_id=source.assignment_id,
        attempt_id=source.attempt_id,
        source_dispatch_id=source.source_dispatch_id,
        request=command_run_request_from_model(source),
        state=CommandRunState(source.state),
        ownership_revision=source.ownership_revision,
        created_at=source.created_at,
        started_at=source.started_at,
        due_at=source.due_at,
        ended_at=source.ended_at,
        stdout_log_ref=source.stdout_logical_path,
        stderr_log_ref=source.stderr_logical_path,
        cancellation_requested_at=source.cancellation_requested_at,
        cancellation_requested_by_actor_ref=source.cancellation_requested_by_actor_ref,
        terminal_result=_terminal_result(source),
        successor_dispatch_id=source.successor_dispatch_id,
    )


def command_run_request_from_model(source: CommandRunModel) -> CommandRunStartRequest:
    return CommandRunStartRequest.model_validate(
        {
            "command": source.command_spec_json,
            "cwd": _command_workdir(source),
            "environment": source.environment_refs_json or (),
            "timeout_seconds": source.timeout_seconds,
            "summary": source.summary,
            "expected_outputs": source.expected_outputs_json or (),
        }
    )


def command_run_list_item_from_model(source: CommandRunModel) -> CommandRunListItem:
    return CommandRunListItem(
        run_id=source.run_id,
        state=CommandRunState(source.state),
        command=_command_display(source),
        description=source.summary,
        workdir=_command_workdir(source),
        created_at=source.created_at,
        started_at=source.started_at,
        ended_at=source.ended_at,
        timeout_seconds=source.timeout_seconds,
        summary=source.terminal_summary,
        exit_code=source.terminal_exit_code,
        signal=_exit_signal(source.terminal_exit_code),
        log_ref=_preferred_log_ref(source),
        failure_code=source.terminal_failure_code,
    )


def _current_command_wait_exists(source: CommandRunModel) -> ColumnElement[bool]:
    return exists().where(
        FlowModel.flow_id == source.flow_id,
        FlowModel.task_id == source.task_id,
        FlowModel.status.in_(("running", "paused")),
        FlowModel.current_dispatch_id.is_(None),
        FlowModel.waiting_cause == "command_run",
        FlowModel.waiting_source_id == source.run_id,
    ) & exists().where(
        FlowWaitModel.flow_id == source.flow_id,
        FlowWaitModel.task_id == source.task_id,
        FlowWaitModel.command_run_id == source.run_id,
        FlowWaitModel.source_dispatch_id == source.source_dispatch_id,
    )


async def _command_run_for_task(
    session: AsyncSession,
    *,
    task_id: str,
    run_id: str,
) -> CommandRunModel | None:
    return cast(
        CommandRunModel | None,
        await session.scalar(
            select(CommandRunModel)
            .options(raiseload("*"))
            .where(
                CommandRunModel.task_id == task_id,
                CommandRunModel.run_id == run_id,
            )
        ),
    )


async def _require_task_flow_exists(session: AsyncSession, task_id: str) -> None:
    flow_id = await session.scalar(
        select(FlowModel.flow_id).where(FlowModel.task_id == task_id).limit(1)
    )
    if flow_id is None:
        raise missing_resource_error(f"unknown task_id '{task_id}'")


def _command_display(source: CommandRunModel) -> str:
    command = source.command_spec_json
    if command.get("kind") == "argv":
        argv = command.get("argv")
        if not isinstance(argv, list) or not all(isinstance(value, str) for value in argv):
            raise ValueError("command argv source has an invalid shape")
        return shlex.join(argv)
    if command.get("kind") == "shell":
        value = command.get("command")
        if not isinstance(value, str):
            raise ValueError("shell command source has an invalid shape")
        return value
    raise ValueError("command source has an unknown discriminator")


def _command_workdir(source: CommandRunModel) -> str | None:
    if source.cwd_policy_json is None:
        return None
    if set(source.cwd_policy_json) != {"logical_path"}:
        raise ValueError("command cwd policy has an invalid shape")
    value = source.cwd_policy_json["logical_path"]
    if not isinstance(value, str):
        raise ValueError("command cwd policy requires a text logical path")
    return value


def _terminal_result(source: CommandRunModel) -> CommandRunTerminalResult | None:
    state = CommandRunState(source.state)
    if state not in TERMINAL_COMMAND_RUN_STATES:
        return None
    if source.terminal_summary is None or source.ended_at is None:
        raise ValueError("terminal command run is missing its result")
    if source.terminal_event_source is None:
        raise ValueError("terminal command run is missing its event source")
    return CommandRunTerminalResult(
        state=cast(CommandRunTerminalState, state),
        summary=source.terminal_summary,
        exit_code=source.terminal_exit_code,
        started_at=source.started_at,
        ended_at=source.ended_at,
        stdout_log_ref=source.stdout_logical_path,
        stderr_log_ref=source.stderr_logical_path,
        failure_code=source.terminal_failure_code,
        terminal_event_source=CommandRunTerminalSource(source.terminal_event_source),
        terminal_actor_ref=source.terminal_actor_ref,
    )


def _preferred_log_ref(source: CommandRunModel) -> str | None:
    if source.state in {CommandRunState.FAILED.value, CommandRunState.TIMED_OUT.value}:
        return source.stderr_logical_path or source.stdout_logical_path
    return source.stdout_logical_path or source.stderr_logical_path


def _exit_signal(exit_code: int | None) -> str | None:
    if exit_code is None or exit_code >= 0:
        return None
    return str(-exit_code)


def _publish_command_cancellation(
    *,
    run_id: str,
    ownership_revision: int,
    runtime_effect_publisher: RuntimeEffectPublisher | None,
) -> None:
    if runtime_effect_publisher is None:
        return
    try:
        runtime_effect_publisher.publish(
            CommandRunCancellationRequested(
                run_id=run_id,
                ownership_revision=ownership_revision,
            )
        )
    except Exception:
        logger.exception(
            "failed to publish committed command cancellation hint",
            extra={"run_id": run_id},
        )


def _command_run_conflict(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary=summary,
        is_retryable=False,
        suggested_next_step=_COMMAND_CONFLICT_NEXT_STEP,
        status_code_override=409,
    )


__all__ = [
    "cancel_command_run",
    "command_run_list_item_from_model",
    "command_run_record_from_model",
    "list_command_runs",
    "read_command_run",
    "read_command_run_log",
    "request_command_run_cancellation",
]
