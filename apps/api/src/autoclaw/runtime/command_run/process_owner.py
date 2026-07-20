from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, suppress
from datetime import datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Self
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from autoclaw.persistence.models import CommandRunModel
from autoclaw.runtime.clock import utc_now
from autoclaw.runtime.command_run.owned_process import OwnedCommandProcess
from autoclaw.runtime.command_run.ownership_recovery import abandon_unowned_command_run
from autoclaw.runtime.command_run.process_resources import (
    CommandTerminalCause,
    classify_command_process_exit,
    command_launch_failure_code,
    drain_command_stream,
    resolve_command_environment,
    spawn_command_process,
)
from autoclaw.runtime.command_run.task_paths import CommandProcessPaths
from autoclaw.runtime.command_run.transitions import (
    CommandRunLaunchClaim,
    claim_command_run_launch,
    mark_command_run_running,
    terminalize_command_run,
)
from autoclaw.runtime.contracts import CommandRunState
from autoclaw.runtime.post_commit import (
    CommandProcessExited,
    CommandRunCancellationRequested,
    CommandRunDue,
    CommandRunPending,
    CommandRunTerminal,
    RuntimeEffectPublisher,
)
from autoclaw.runtime.post_commit.health import RuntimeEffectHealth
from autoclaw.runtime.task_root import (
    command_run_logical_path,
)

logger = logging.getLogger(__name__)

DEFAULT_COMMAND_LOG_BYTE_LIMIT = 1_048_576
DEFAULT_COMMAND_TERMINATE_GRACE_SECONDS = 2.0
DEFAULT_COMMAND_KILL_WAIT_SECONDS = 2.0
DEFAULT_COMMAND_OWNER_SHUTDOWN_SECONDS = 5.0

type AsyncSessionContextFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
type RegisterCommandRunDue = Callable[[CommandRunDue], None]
type CommandOwnerClock = Callable[[], datetime]


class CommandProcessOwner:
    """Lifespan owner for exact command child processes and their pipe resources."""

    def __init__(
        self,
        *,
        session_factory: AsyncSessionContextFactory,
        runtime_effect_publisher: RuntimeEffectPublisher,
        register_due: RegisterCommandRunDue,
        health: RuntimeEffectHealth | None = None,
        clock: CommandOwnerClock = utc_now,
        log_byte_limit: int = DEFAULT_COMMAND_LOG_BYTE_LIMIT,
        terminate_grace_seconds: float = DEFAULT_COMMAND_TERMINATE_GRACE_SECONDS,
        kill_wait_seconds: float = DEFAULT_COMMAND_KILL_WAIT_SECONDS,
        shutdown_seconds: float = DEFAULT_COMMAND_OWNER_SHUTDOWN_SECONDS,
    ) -> None:
        if log_byte_limit < 0:
            raise ValueError("command log byte limit must be non-negative")
        for label, value in (
            ("terminate grace", terminate_grace_seconds),
            ("kill wait", kill_wait_seconds),
            ("shutdown", shutdown_seconds),
        ):
            if value <= 0:
                raise ValueError(f"command {label} seconds must be positive")
        self._session_factory = session_factory
        self._process_paths = CommandProcessPaths(session_factory)
        self._runtime_effect_publisher = runtime_effect_publisher
        self._register_due = register_due
        self._health = health or RuntimeEffectHealth()
        self._clock = clock
        self._log_byte_limit = log_byte_limit
        self._terminate_grace_seconds = terminate_grace_seconds
        self._kill_wait_seconds = kill_wait_seconds
        self._shutdown_seconds = shutdown_seconds
        self._owner_ref = f"command-owner.{uuid4().hex}"
        self._owned: dict[str, OwnedCommandProcess] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._is_active = False
        self._is_shutting_down = False

    async def __aenter__(self) -> Self:
        if self._is_active:
            raise RuntimeError("command process owner lifespan cannot be re-entered")
        self._is_active = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        del exc_type, exc_value, traceback
        self._is_shutting_down = True
        await self._shutdown_owned_processes()
        self._is_active = False
        return None

    async def launch_pending_command(
        self,
        session: AsyncSession,
        signal: CommandRunPending,
    ) -> None:
        if self._is_shutting_down:
            return
        self._require_active()
        stdout_ref = command_run_logical_path(
            run_id=signal.run_id,
            stream="stdout",
        ).as_posix()
        stderr_ref = command_run_logical_path(
            run_id=signal.run_id,
            stream="stderr",
        ).as_posix()
        claim = await claim_command_run_launch(
            session,
            run_id=signal.run_id,
            owner_ref=self._owner_ref,
            stdout_log_ref=stdout_ref,
            stderr_log_ref=stderr_ref,
            claimed_at=self._clock(),
        )
        if claim is None:
            await self._recover_unowned_command(session, signal.run_id)
            return
        owned = OwnedCommandProcess(claim=claim)
        self._owned[claim.run_id] = owned
        self._track_task(
            asyncio.create_task(
                self._launch_owned(owned),
                name=f"autoclaw-command-launch-{claim.run_id}",
            )
        )

    async def enforce_command_deadline(
        self,
        session: AsyncSession,
        signal: CommandRunDue,
    ) -> None:
        if self._is_shutting_down:
            return
        source = await session.scalar(
            select(CommandRunModel)
            .options(raiseload("*"))
            .where(
                CommandRunModel.run_id == signal.run_id,
                CommandRunModel.state == CommandRunState.RUNNING.value,
                CommandRunModel.due_at == signal.due_at,
                CommandRunModel.due_at <= self._clock(),
            )
        )
        if source is None:
            return
        owned = self._owned.get(signal.run_id)
        if owned is None or owned.claim.ownership_revision != source.ownership_revision:
            if await abandon_unowned_command_run(session, source, ended_at=self._clock()):
                self._publish_terminal(source.run_id)
            return
        await self._request_owned_termination(owned, cause="timed_out")

    async def terminate_cancelled_command(
        self,
        session: AsyncSession,
        signal: CommandRunCancellationRequested,
    ) -> None:
        if self._is_shutting_down:
            return
        source = await session.scalar(
            select(CommandRunModel)
            .options(raiseload("*"))
            .where(
                CommandRunModel.run_id == signal.run_id,
                CommandRunModel.state == CommandRunState.CANCELLATION_REQUESTED.value,
                CommandRunModel.ownership_revision == signal.ownership_revision,
            )
        )
        if source is None:
            return
        owned = self._owned.get(signal.run_id)
        if owned is not None and owned.claim.ownership_revision == signal.ownership_revision:
            await self._request_owned_termination(owned, cause="cancelled")
            return
        if signal.ownership_revision == 0:
            won = await terminalize_command_run(
                session,
                task_id=source.task_id,
                run_id=source.run_id,
                expected_ownership_revision=0,
                expected_states=(CommandRunState.CANCELLATION_REQUESTED,),
                terminal_state=CommandRunState.CANCELLED,
                summary="Command cancellation completed before process launch.",
                ended_at=self._clock(),
            )
        else:
            won = await abandon_unowned_command_run(
                session,
                source,
                ended_at=self._clock(),
            )
        if won:
            self._publish_terminal(source.run_id)

    async def record_command_process_exit(
        self,
        session: AsyncSession,
        signal: CommandProcessExited,
    ) -> None:
        if self._is_shutting_down:
            return
        owned = self._owned.get(signal.run_id)
        if owned is None or owned.claim.ownership_revision != signal.ownership_revision:
            return
        process = owned.process
        if process is None or process.returncode is None:
            return
        source = await session.scalar(
            select(CommandRunModel)
            .options(raiseload("*"))
            .where(
                CommandRunModel.run_id == signal.run_id,
                CommandRunModel.ownership_revision == signal.ownership_revision,
            )
        )
        if source is None:
            self._owned.pop(signal.run_id, None)
            return

        result = classify_command_process_exit(
            source_state=source.state,
            terminal_cause=owned.terminal_cause,
            returncode=process.returncode,
        )
        won = await terminalize_command_run(
            session,
            task_id=source.task_id,
            run_id=source.run_id,
            expected_ownership_revision=signal.ownership_revision,
            expected_states=result.expected_states,
            terminal_state=result.terminal_state,
            summary=result.summary,
            exit_code=process.returncode,
            failure_code=result.failure_code,
            ended_at=self._clock(),
            expected_due_at=source.due_at,
            should_match_due_at=result.terminal_state == CommandRunState.TIMED_OUT,
        )
        self._owned.pop(signal.run_id, None)
        if won:
            self._publish_terminal(signal.run_id)

    async def _launch_owned(self, owned: OwnedCommandProcess) -> None:
        claim = owned.claim
        stdout_path: Path | None = None
        stderr_path: Path | None = None
        try:
            if await self._finish_unlaunched_cancellation(owned):
                return
            cwd = await self._process_paths.resolve_working_directory(claim)
            environment = resolve_command_environment(claim)
            stdout_path, stderr_path = await self._process_paths.create_log_files(claim)
            if await self._finish_unlaunched_cancellation(owned):
                await self._process_paths.cleanup_unreferenced_log_files(
                    stdout_path,
                    stderr_path,
                )
                return
            process = await spawn_command_process(
                claim,
                cwd=cwd,
                environment=environment,
            )
            owned.process = process
            self._track_task(
                asyncio.create_task(
                    self._supervise_process(
                        owned,
                        stdout_path=stdout_path,
                        stderr_path=stderr_path,
                    ),
                    name=f"autoclaw-command-supervise-{claim.run_id}",
                )
            )
            await self._record_owned_process_start(owned)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "command process launch failed",
                extra={"run_id": claim.run_id, "exception_type": type(exc).__name__},
            )
            if owned.process is None and stdout_path is not None and stderr_path is not None:
                await self._process_paths.cleanup_unreferenced_log_files(
                    stdout_path,
                    stderr_path,
                )
            if self._is_shutting_down:
                return
            if owned.process is not None:
                if owned.terminal_cause is None:
                    owned.terminal_cause = "launch_failed"
                owned.launch_state_resolved.set()
                await self._request_owned_termination(
                    owned,
                    cause=owned.terminal_cause,
                )
            else:
                await self._terminalize_launch_failure(
                    claim,
                    failure_code=command_launch_failure_code(exc),
                )

    async def _record_owned_process_start(self, owned: OwnedCommandProcess) -> None:
        claim = owned.claim
        process = owned.process
        assert process is not None
        started_at = self._clock()
        due_at = (
            started_at + timedelta(seconds=claim.request.timeout_seconds)
            if claim.request.timeout_seconds is not None
            else None
        )
        async with self._session_factory() as session:
            running = await mark_command_run_running(
                session,
                claim=claim,
                owner_ref=self._owner_ref,
                pid=process.pid,
                started_at=started_at,
                due_at=due_at,
            )
        if running is None:
            if owned.terminal_cause is None:
                owned.terminal_cause = "cancelled"
            owned.launch_state_resolved.set()
            await self._request_owned_termination(owned, cause="cancelled")
            return
        owned.launch_state_resolved.set()
        if running.due_at is not None:
            self._register_due(CommandRunDue(claim.run_id, running.due_at))
        if owned.terminal_cause is not None:
            await self._request_owned_termination(owned, cause=owned.terminal_cause)

    async def _supervise_process(
        self,
        owned: OwnedCommandProcess,
        *,
        stdout_path: Path,
        stderr_path: Path,
    ) -> None:
        process = owned.process
        assert process is not None
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_task = asyncio.create_task(
            drain_command_stream(
                process.stdout,
                stdout_path,
                byte_limit=self._log_byte_limit,
            ),
            name=f"autoclaw-command-stdout-{owned.claim.run_id}",
        )
        stderr_task = asyncio.create_task(
            drain_command_stream(
                process.stderr,
                stderr_path,
                byte_limit=self._log_byte_limit,
            ),
            name=f"autoclaw-command-stderr-{owned.claim.run_id}",
        )
        try:
            await process.wait()
            drain_results = await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            for result in drain_results:
                if isinstance(result, BaseException):
                    logger.error(
                        "command log drain failed",
                        extra={
                            "run_id": owned.claim.run_id,
                            "exception_type": type(result).__name__,
                        },
                    )
        finally:
            for task in (stdout_task, stderr_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        if not self._is_shutting_down:
            await owned.launch_state_resolved.wait()
            self._runtime_effect_publisher.publish(
                CommandProcessExited(
                    run_id=owned.claim.run_id,
                    ownership_revision=owned.claim.ownership_revision,
                )
            )

    async def _request_owned_termination(
        self,
        owned: OwnedCommandProcess,
        *,
        cause: CommandTerminalCause,
    ) -> None:
        if owned.terminal_cause is None:
            owned.terminal_cause = cause
        self._track_task(
            asyncio.create_task(
                self._terminate_owned_process(owned),
                name=f"autoclaw-command-terminate-{owned.claim.run_id}",
            )
        )

    async def _terminate_owned_process(self, owned: OwnedCommandProcess) -> None:
        async with owned.termination_lock:
            process = owned.process
            if process is None or process.returncode is not None:
                return
            with suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.wait_for(
                    asyncio.shield(process.wait()),
                    timeout=self._terminate_grace_seconds,
                )
                return
            except TimeoutError:
                pass
            with suppress(ProcessLookupError):
                process.kill()
            await asyncio.wait_for(
                asyncio.shield(process.wait()),
                timeout=self._kill_wait_seconds,
            )

    async def _finish_unlaunched_cancellation(self, owned: OwnedCommandProcess) -> bool:
        if owned.terminal_cause != "cancelled":
            return False
        claim = owned.claim
        async with self._session_factory() as session:
            won = await terminalize_command_run(
                session,
                task_id=claim.task_id,
                run_id=claim.run_id,
                expected_ownership_revision=claim.ownership_revision,
                expected_states=(CommandRunState.CANCELLATION_REQUESTED,),
                terminal_state=CommandRunState.CANCELLED,
                summary="Command cancellation completed before process launch.",
                ended_at=self._clock(),
            )
        if won:
            self._owned.pop(claim.run_id, None)
            self._publish_terminal(claim.run_id)
        return won

    async def _terminalize_launch_failure(
        self,
        claim: CommandRunLaunchClaim,
        *,
        failure_code: str,
    ) -> None:
        async with self._session_factory() as session:
            won = await terminalize_command_run(
                session,
                task_id=claim.task_id,
                run_id=claim.run_id,
                expected_ownership_revision=claim.ownership_revision,
                expected_states=(CommandRunState.PENDING_START,),
                terminal_state=CommandRunState.FAILED,
                summary="The controller could not launch the requested command.",
                failure_code=failure_code,
                ended_at=self._clock(),
            )
        if won:
            self._owned.pop(claim.run_id, None)
            self._publish_terminal(claim.run_id)
            return
        owned = self._owned.get(claim.run_id)
        if owned is not None:
            await self._finish_unlaunched_cancellation(owned)

    async def _recover_unowned_command(self, session: AsyncSession, run_id: str) -> None:
        source = await session.scalar(
            select(CommandRunModel).options(raiseload("*")).where(CommandRunModel.run_id == run_id)
        )
        if source is None or source.state in {
            CommandRunState.SUCCEEDED.value,
            CommandRunState.FAILED.value,
            CommandRunState.TIMED_OUT.value,
            CommandRunState.CANCELLED.value,
            CommandRunState.ABANDONED.value,
        }:
            return
        owned = self._owned.get(run_id)
        if owned is not None and owned.claim.ownership_revision == source.ownership_revision:
            return
        if (
            source.state == CommandRunState.CANCELLATION_REQUESTED.value
            and source.ownership_revision == 0
        ):
            won = await terminalize_command_run(
                session,
                task_id=source.task_id,
                run_id=source.run_id,
                expected_ownership_revision=0,
                expected_states=(CommandRunState.CANCELLATION_REQUESTED,),
                terminal_state=CommandRunState.CANCELLED,
                summary="Command cancellation completed before process launch.",
                ended_at=self._clock(),
            )
        else:
            won = await abandon_unowned_command_run(
                session,
                source,
                ended_at=self._clock(),
            )
        if won:
            self._publish_terminal(source.run_id)

    async def _shutdown_owned_processes(self) -> None:
        termination_tasks = [
            asyncio.create_task(self._terminate_owned_process(owned))
            for owned in tuple(self._owned.values())
            if owned.process is not None
        ]
        if termination_tasks:
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    asyncio.gather(*termination_tasks, return_exceptions=True),
                    timeout=self._shutdown_seconds,
                )
        pending_tasks = tuple(task for task in self._tasks if not task.done())
        if pending_tasks:
            for task in pending_tasks:
                task.cancel()
            await asyncio.gather(*pending_tasks, return_exceptions=True)
        self._owned.clear()

    def _publish_terminal(self, run_id: str) -> None:
        self._runtime_effect_publisher.publish(CommandRunTerminal(run_id))

    def _track_task(self, task: asyncio.Task[None]) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._task_finished)

    def _task_finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exception = task.exception()
        if exception is not None:
            self._health.mark_failure(
                failure_kind="command_owner_task_failed",
                signal=None,
                exception_type=type(exception).__name__,
            )
            logger.error(
                "command process owner task failed",
                extra={"exception_type": type(exception).__name__},
                exc_info=exception,
            )

    def _require_active(self) -> None:
        if not self._is_active or self._is_shutting_down:
            raise RuntimeError("command process owner is not accepting work")


__all__ = [
    "DEFAULT_COMMAND_KILL_WAIT_SECONDS",
    "DEFAULT_COMMAND_LOG_BYTE_LIMIT",
    "DEFAULT_COMMAND_OWNER_SHUTDOWN_SECONDS",
    "DEFAULT_COMMAND_TERMINATE_GRACE_SECONDS",
    "CommandOwnerClock",
    "CommandProcessOwner",
    "RegisterCommandRunDue",
]
