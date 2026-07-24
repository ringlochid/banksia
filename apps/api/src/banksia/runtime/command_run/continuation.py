from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload
from sqlalchemy.sql.elements import ColumnElement

from banksia.persistence.models import AttemptModel, CommandRunModel, FlowModel
from banksia.persistence.models.runtime.common import COMMAND_RUN_TERMINAL_STATE_VALUES
from banksia.runtime.contracts.command_runs import CommandRunStartRequest
from banksia.runtime.contracts.prompt import (
    CommandResult,
    CommandResultSource,
    CommandResultTrigger,
    PromptCommandOutcome,
    PromptCommandResult,
    PromptCommandTerminalSource,
)
from banksia.runtime.control_transitions import (
    pause_flow_for_runtime_transition_failure,
)
from banksia.runtime.dispatch.ordinary_context import (
    OrdinaryContinuationBasis,
    OrdinaryDispatchSnapshot,
)
from banksia.runtime.dispatch.ordinary_continuation import (
    OrdinaryOpeningResult,
    open_ordinary_successor,
)
from banksia.runtime.dispatch.preparation import (
    DispatchOpeningDependencies,
    PreparedDispatchRequest,
)
from banksia.runtime.post_commit import CommandRunTerminal

type CommandRunTerminalHandler = Callable[[AsyncSession, CommandRunTerminal], Awaitable[None]]


def create_command_run_terminal_handler(
    dependencies: DispatchOpeningDependencies,
) -> CommandRunTerminalHandler:
    async def handle(session: AsyncSession, signal: CommandRunTerminal) -> None:
        await open_command_run_successor(
            session,
            signal=signal,
            dependencies=dependencies,
        )

    return handle


async def open_command_run_successor(
    session: AsyncSession,
    *,
    signal: CommandRunTerminal,
    dependencies: DispatchOpeningDependencies,
) -> OrdinaryOpeningResult:
    """Open at most one successor from one exact terminal command run."""

    return await open_ordinary_successor(
        session,
        source_id=signal.run_id,
        dependencies=dependencies,
        read_source=read_command_run_continuation_basis,
        claim_source=claim_command_run_continuation,
        record_failure=pause_failed_command_run_continuation,
        default_failure_code="command_result_dispatch_preparation_failed",
    )


async def read_command_run_continuation_basis(
    session: AsyncSession,
    run_id: str,
) -> OrdinaryContinuationBasis | None:
    """Read one terminal, unconsumed command source and its bounded result."""

    source = await session.scalar(
        select(CommandRunModel)
        .options(raiseload("*"))
        .where(
            CommandRunModel.run_id == run_id,
            CommandRunModel.state.in_(COMMAND_RUN_TERMINAL_STATE_VALUES),
            CommandRunModel.successor_dispatch_id.is_(None),
        )
    )
    if source is None:
        return None
    return command_run_continuation_basis(source, opened_reason="command_result")


async def claim_command_run_continuation(
    session: AsyncSession,
    snapshot: OrdinaryDispatchSnapshot,
    prepared: PreparedDispatchRequest,
) -> bool:
    """Conditionally record the one successor identity on the exact command source."""

    trigger = snapshot.basis.trigger
    if not isinstance(trigger, CommandResultTrigger):
        return False
    run_id = await session.scalar(
        update(CommandRunModel)
        .where(
            CommandRunModel.run_id == trigger.source.command_id,
            CommandRunModel.task_id == snapshot.prompt.task_id,
            CommandRunModel.flow_id == snapshot.prompt.flow_id,
            CommandRunModel.assignment_id == snapshot.prompt.assignment_id,
            CommandRunModel.attempt_id == snapshot.prompt.attempt_id,
            CommandRunModel.source_dispatch_id == snapshot.basis.source_dispatch_id,
            CommandRunModel.source_dispatch_id == trigger.source.source_dispatch_id,
            *_command_request_predicates(trigger.result.request),
            *_command_result_predicates(trigger.result.terminal),
            CommandRunModel.successor_dispatch_id.is_(None),
        )
        .values(successor_dispatch_id=prepared.dispatch_id)
        .returning(CommandRunModel.run_id)
    )
    return run_id is not None


async def pause_failed_command_run_continuation(
    session: AsyncSession,
    run_id: str,
    paused_at: datetime,
    failure_code: str,
) -> tuple[str, ...]:
    """Pause the exact failed source and every runnable sibling Attempt lane."""

    source_is_unconsumed = exists(
        select(CommandRunModel.run_id)
        .join(
            AttemptModel,
            (AttemptModel.task_id == CommandRunModel.task_id)
            & (AttemptModel.flow_id == CommandRunModel.flow_id)
            & (AttemptModel.assignment_id == CommandRunModel.assignment_id)
            & (AttemptModel.attempt_id == CommandRunModel.attempt_id),
        )
        .where(
            CommandRunModel.run_id == run_id,
            CommandRunModel.flow_id == FlowModel.flow_id,
            CommandRunModel.task_id == FlowModel.task_id,
            CommandRunModel.state.in_(COMMAND_RUN_TERMINAL_STATE_VALUES),
            CommandRunModel.successor_dispatch_id.is_(None),
            AttemptModel.status == "running",
            AttemptModel.current_dispatch_id.is_(None),
            AttemptModel.current_wait_id.is_(None),
        )
    )
    return await pause_flow_for_runtime_transition_failure(
        session,
        source_is_current=source_is_unconsumed,
        paused_at=paused_at,
        pause_details={
            "source": "command_run",
            "run_id": run_id,
            "failure_code": failure_code,
        },
    )


def command_run_continuation_basis(
    source: CommandRunModel,
    *,
    opened_reason: str,
) -> OrdinaryContinuationBasis:
    if (
        source.terminal_summary is None
        or source.ended_at is None
        or source.terminal_event_source is None
    ):
        raise ValueError("terminal command run is missing result truth")
    return OrdinaryContinuationBasis(
        task_id=source.task_id,
        flow_id=source.flow_id,
        assignment_id=source.assignment_id,
        attempt_id=source.attempt_id,
        source_dispatch_id=source.source_dispatch_id,
        source_dispatch_closed_reason="command_run_wait",
        opened_reason=opened_reason,
        trigger=CommandResultTrigger(
            source=CommandResultSource(
                command_id=source.run_id,
                source_dispatch_id=source.source_dispatch_id,
            ),
            result=CommandResult(
                request=_command_request(source),
                terminal=PromptCommandResult(
                    state=PromptCommandOutcome(source.state),
                    exit_code=source.terminal_exit_code,
                    summary=source.terminal_summary,
                    started_at=source.started_at,
                    ended_at=source.ended_at,
                    output_path=source.output_path,
                    output_observed_bytes=source.output_observed_bytes,
                    output_written_bytes=source.output_written_bytes,
                    output_complete=source.output_complete,
                    output_encoding="raw_bytes",
                    failure_code=source.terminal_failure_code,
                    terminal_event_source=PromptCommandTerminalSource(source.terminal_event_source),
                    terminal_actor_ref=source.terminal_actor_ref,
                ),
            ),
        ),
    )


def _command_request(source: CommandRunModel) -> CommandRunStartRequest:
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


def _command_request_predicates(
    request: CommandRunStartRequest,
) -> tuple[ColumnElement[bool], ...]:
    cwd_policy = {"logical_path": request.cwd} if request.cwd is not None else None
    return (
        CommandRunModel.command_spec_json == request.command.model_dump(mode="json"),
        (
            CommandRunModel.cwd_policy_json.is_(None)
            if cwd_policy is None
            else CommandRunModel.cwd_policy_json == cwd_policy
        ),
        CommandRunModel.summary == request.summary,
        (
            CommandRunModel.timeout_seconds.is_(None)
            if request.timeout_seconds is None
            else CommandRunModel.timeout_seconds == request.timeout_seconds
        ),
    )


def _command_result_predicates(
    result: PromptCommandResult,
) -> tuple[ColumnElement[bool], ...]:
    return (
        CommandRunModel.state == result.state.value,
        CommandRunModel.terminal_summary == result.summary,
        (
            CommandRunModel.terminal_exit_code.is_(None)
            if result.exit_code is None
            else CommandRunModel.terminal_exit_code == result.exit_code
        ),
        (
            CommandRunModel.started_at.is_(None)
            if result.started_at is None
            else CommandRunModel.started_at == result.started_at
        ),
        CommandRunModel.ended_at == result.ended_at,
        CommandRunModel.output_path == result.output_path,
        CommandRunModel.output_observed_bytes == result.output_observed_bytes,
        CommandRunModel.output_written_bytes == result.output_written_bytes,
        CommandRunModel.output_complete == result.output_complete,
        CommandRunModel.output_encoding == result.output_encoding,
        (
            CommandRunModel.terminal_failure_code.is_(None)
            if result.failure_code is None
            else CommandRunModel.terminal_failure_code == result.failure_code
        ),
        CommandRunModel.terminal_event_source == result.terminal_event_source.value,
        (
            CommandRunModel.terminal_actor_ref.is_(None)
            if result.terminal_actor_ref is None
            else CommandRunModel.terminal_actor_ref == result.terminal_actor_ref
        ),
    )


__all__ = [
    "CommandRunTerminalHandler",
    "claim_command_run_continuation",
    "command_run_continuation_basis",
    "create_command_run_terminal_handler",
    "open_command_run_successor",
    "pause_failed_command_run_continuation",
    "read_command_run_continuation_basis",
]
