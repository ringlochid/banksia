from __future__ import annotations

import asyncio
import errno
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from banksia.runtime.command_run.output_files import (
    CommandOutputFile,
    close_command_output_file,
)
from banksia.runtime.command_run.posix_process import spawn_posix_guardian_process
from banksia.runtime.command_run.task_paths import (
    StableCommandWorkingDirectory,
)
from banksia.runtime.command_run.transitions import CommandRunLaunchClaim
from banksia.runtime.contracts import CommandRunState

if TYPE_CHECKING:
    from banksia.runtime.command_run.owned_process import ManagedCommandProcess

type CommandTerminalCause = Literal["cancelled", "launch_failed", "timed_out"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CommandProcessExitResult:
    terminal_state: CommandRunState
    summary: str
    failure_code: str | None
    expected_states: tuple[CommandRunState, ...]


@dataclass(frozen=True, slots=True)
class CommandOutputCapture:
    observed_bytes: int
    written_bytes: int
    is_complete: bool


@dataclass(frozen=True, slots=True)
class CommandOutputWrite:
    written_bytes: int
    is_complete: bool


async def spawn_command_process(
    claim: CommandRunLaunchClaim,
    *,
    working_directory: StableCommandWorkingDirectory,
    environment: dict[str, str],
) -> ManagedCommandProcess:
    """Spawn in the retained directory identity without resolving the authored path again."""

    if os.name == "posix":
        return await spawn_posix_guardian_process(
            claim,
            working_directory=working_directory,
            environment=environment,
        )
    raise OSError(
        errno.ENOTSUP,
        "Banksia Command Run supervision supports Linux and macOS only",
    )


def resolve_command_environment() -> dict[str, str]:
    """Return the controller-owned non-secret baseline environment."""

    allowed_keys = (
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PATH",
        "TEMP",
        "TMP",
        "TMPDIR",
    )
    environment = {key: value for key in allowed_keys if (value := os.environ.get(key))}
    environment.setdefault("PATH", os.defpath)
    return environment


async def drain_command_output(
    process: ManagedCommandProcess,
    output: CommandOutputFile,
) -> CommandOutputCapture:
    """Drain one combined pipe to EOF while preserving truthful write counts."""

    observed_bytes = 0
    written_bytes = 0
    is_complete = True
    can_write = True
    try:
        while chunk := await process.read_output(64 * 1024):
            observed_bytes += len(chunk)
            if not can_write:
                continue
            try:
                write = await asyncio.to_thread(
                    write_command_output_chunk,
                    output.descriptor,
                    chunk,
                )
            except Exception:
                logger.exception("command output write lane failed")
                is_complete = False
                can_write = False
                continue
            written_bytes += write.written_bytes
            if not write.is_complete:
                is_complete = False
                can_write = False
    except Exception:
        logger.exception("command output pipe drain failed")
        is_complete = False
    finally:
        if can_write:
            try:
                await asyncio.to_thread(os.fsync, output.descriptor)
            except OSError:
                logger.exception("command output flush failed")
                is_complete = False
        try:
            close_command_output_file(output)
        except OSError:
            logger.exception("command output close failed")
            is_complete = False
    return CommandOutputCapture(
        observed_bytes=observed_bytes,
        written_bytes=written_bytes,
        is_complete=is_complete and observed_bytes == written_bytes,
    )


def write_command_output_chunk(
    descriptor: int,
    payload: bytes,
) -> CommandOutputWrite:
    """Write as much of one observed chunk as possible without hiding failure."""

    written_bytes = 0
    view = memoryview(payload)
    try:
        while written_bytes < len(payload):
            count = os.write(descriptor, view[written_bytes:])
            if count < 1:
                return CommandOutputWrite(
                    written_bytes=written_bytes,
                    is_complete=False,
                )
            written_bytes += count
    except OSError:
        logger.exception("command output write failed")
        return CommandOutputWrite(
            written_bytes=written_bytes,
            is_complete=False,
        )
    return CommandOutputWrite(
        written_bytes=written_bytes,
        is_complete=True,
    )


def command_launch_failure_code(exc: Exception) -> str:
    """Classify a launch exception without persisting raw exception text."""

    if isinstance(exc, FileExistsError):
        return "command_log_path_conflict"
    if isinstance(exc, (FileNotFoundError, NotADirectoryError, ValueError)):
        return "command_cwd_or_path_invalid"
    return "command_launch_failed"


def classify_command_process_exit(
    *,
    source_state: str,
    terminal_cause: CommandTerminalCause | None,
    returncode: int,
) -> CommandProcessExitResult:
    """Classify one reaped direct child without consulting provider state."""

    if (
        terminal_cause == "cancelled"
        or source_state == CommandRunState.CANCELLATION_REQUESTED.value
    ):
        return CommandProcessExitResult(
            terminal_state=CommandRunState.CANCELLED,
            summary="The command was cancelled and its child process was reaped.",
            failure_code=None,
            expected_states=(CommandRunState.CANCELLATION_REQUESTED,),
        )
    if terminal_cause == "timed_out":
        return CommandProcessExitResult(
            terminal_state=CommandRunState.TIMED_OUT,
            summary="The command exceeded its controller-owned deadline.",
            failure_code="command_timed_out",
            expected_states=(CommandRunState.RUNNING,),
        )
    if terminal_cause == "launch_failed":
        return CommandProcessExitResult(
            terminal_state=CommandRunState.FAILED,
            summary="The command was reaped after launch-state persistence failed.",
            failure_code="command_launch_state_failed",
            expected_states=(CommandRunState.PENDING_START, CommandRunState.RUNNING),
        )
    if returncode == 0:
        return CommandProcessExitResult(
            terminal_state=CommandRunState.SUCCEEDED,
            summary="The command exited successfully.",
            failure_code=None,
            expected_states=(CommandRunState.RUNNING,),
        )
    return CommandProcessExitResult(
        terminal_state=CommandRunState.FAILED,
        summary="The command exited with a non-zero status.",
        failure_code="command_nonzero_exit",
        expected_states=(CommandRunState.RUNNING,),
    )


__all__ = [
    "CommandOutputCapture",
    "CommandOutputWrite",
    "CommandProcessExitResult",
    "CommandTerminalCause",
    "classify_command_process_exit",
    "command_launch_failure_code",
    "drain_command_output",
    "resolve_command_environment",
    "spawn_command_process",
    "write_command_output_chunk",
]
