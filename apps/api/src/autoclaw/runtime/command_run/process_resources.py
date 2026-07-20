from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from autoclaw.runtime.command_run.transitions import CommandRunLaunchClaim
from autoclaw.runtime.contracts import (
    CommandArgvSpec,
    CommandRunState,
    CommandShellSpec,
)

type CommandTerminalCause = Literal["cancelled", "launch_failed", "timed_out"]


@dataclass(frozen=True, slots=True)
class CommandProcessExitResult:
    terminal_state: CommandRunState
    summary: str
    failure_code: str | None
    expected_states: tuple[CommandRunState, ...]


class CommandEnvironmentResolutionUnavailableError(RuntimeError):
    """Raised when authored environment refs have no configured resolver owner."""


async def spawn_command_process(
    claim: CommandRunLaunchClaim,
    *,
    cwd: Path,
    environment: dict[str, str],
) -> asyncio.subprocess.Process:
    """Spawn the explicitly discriminated argv or shell command as one direct child."""

    command = claim.request.command
    if isinstance(command, CommandArgvSpec):
        return await asyncio.create_subprocess_exec(
            *command.argv,
            cwd=str(cwd),
            env=environment,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    if isinstance(command, CommandShellSpec):
        return await asyncio.create_subprocess_shell(
            command.command,
            cwd=str(cwd),
            env=environment,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    raise TypeError(f"unsupported command specification: {type(command).__name__}")


def resolve_command_environment(claim: CommandRunLaunchClaim) -> dict[str, str]:
    """Return a non-secret baseline environment or reject unresolved authored refs."""

    if claim.request.environment:
        raise CommandEnvironmentResolutionUnavailableError
    environment = {"PATH": os.defpath}
    if os.name == "nt" and "SystemRoot" in os.environ:
        environment["SystemRoot"] = os.environ["SystemRoot"]
    return environment


async def drain_command_stream(
    stream: asyncio.StreamReader,
    destination: Path,
    *,
    byte_limit: int,
) -> None:
    """Consume one pipe to EOF while retaining only the configured bounded prefix."""

    written = 0
    with destination.open("ab", buffering=0) as output:
        while chunk := await stream.read(64 * 1024):
            if written >= byte_limit:
                continue
            retained = chunk[: byte_limit - written]
            await asyncio.to_thread(output.write, retained)
            written += len(retained)


def create_command_log_pair(stdout_path: Path, stderr_path: Path) -> None:
    """Create a new mode-0600 controller-owned log pair without replacement."""

    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    if stdout_path.parent != stderr_path.parent:
        raise ValueError("command log streams must share one owner directory")
    created: list[Path] = []
    try:
        for path in (stdout_path, stderr_path):
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
                0o600,
            )
            os.close(descriptor)
            created.append(path)
    except Exception:
        for path in created:
            with suppress(FileNotFoundError):
                path.unlink()
        raise


def remove_command_log_pair(stdout_path: Path, stderr_path: Path) -> None:
    """Remove only one unreferenced log pair created before process launch."""

    if stdout_path.parent != stderr_path.parent:
        raise ValueError("command log streams must share one owner directory")
    for path in (stdout_path, stderr_path):
        with suppress(FileNotFoundError):
            path.unlink()
    with suppress(OSError):
        stdout_path.parent.rmdir()


def command_launch_failure_code(exc: Exception) -> str:
    """Classify a launch exception without persisting raw exception text."""

    if isinstance(exc, CommandEnvironmentResolutionUnavailableError):
        return "command_environment_resolution_unavailable"
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
    "CommandEnvironmentResolutionUnavailableError",
    "CommandProcessExitResult",
    "CommandTerminalCause",
    "classify_command_process_exit",
    "command_launch_failure_code",
    "create_command_log_pair",
    "drain_command_stream",
    "remove_command_log_pair",
    "resolve_command_environment",
    "spawn_command_process",
]
