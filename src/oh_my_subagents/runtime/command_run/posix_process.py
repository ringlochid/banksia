from __future__ import annotations

import asyncio
import errno
import os
import sys
from contextlib import suppress
from pathlib import Path

from oh_my_subagents.platform.workspace_files.posix_leases import require_posix_directory_lease
from oh_my_subagents.runtime.command_run.task_paths import StableCommandWorkingDirectory
from oh_my_subagents.runtime.command_run.transitions import CommandRunLaunchClaim
from oh_my_subagents.runtime.contracts import CommandArgvSpec, CommandShellSpec

_GUARDIAN_PATH = Path(__file__).with_name("posix_guardian.py")
_LAUNCH_STATUS_LIMIT = 128


class PosixGuardianProcess:
    """Async controller handle for one POSIX command guardian."""

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        *,
        command_pid: int,
        control_descriptor: int,
    ) -> None:
        self._process = process
        self._command_pid = command_pid
        self._control_descriptor: int | None = control_descriptor

    @property
    def pid(self) -> int:
        return self._command_pid

    @property
    def returncode(self) -> int | None:
        return self._process.returncode

    async def read_output(self, byte_limit: int) -> bytes:
        stream = self._process.stdout
        if stream is None:
            raise RuntimeError("POSIX guardian output pipe is unavailable")
        return await stream.read(byte_limit)

    async def wait(self) -> int:
        returncode = await self._process.wait()
        self.close_controller_liveness()
        return returncode

    def request_termination(self) -> None:
        self._write_control(b"T")

    def request_kill(self) -> None:
        self._write_control(b"K")

    def close_controller_liveness(self) -> None:
        descriptor = self._control_descriptor
        if descriptor is None:
            return
        self._control_descriptor = None
        with suppress(OSError):
            os.close(descriptor)

    def _write_control(self, command: bytes) -> None:
        descriptor = self._control_descriptor
        if descriptor is None:
            return
        try:
            os.write(descriptor, command)
        except OSError as exc:
            if exc.errno not in {errno.EBADF, errno.EPIPE}:
                raise


async def spawn_posix_guardian_process(
    claim: CommandRunLaunchClaim,
    *,
    working_directory: StableCommandWorkingDirectory,
    environment: dict[str, str],
) -> PosixGuardianProcess:
    """Start a guardian that retains cwd identity and owns the command process group."""

    if os.name != "posix":
        raise OSError(errno.ENOTSUP, "POSIX command supervision is unavailable")

    directory_descriptor = require_posix_directory_lease(working_directory.directory).descriptor
    control_read, control_write = os.pipe()
    status_read, status_write = os.pipe()
    process: asyncio.subprocess.Process | None = None
    try:
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(_GUARDIAN_PATH),
                str(directory_descriptor),
                str(control_read),
                str(status_write),
                *_guardian_command_arguments(claim),
                env=environment,
                pass_fds=(
                    directory_descriptor,
                    control_read,
                    status_write,
                ),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except BaseException:
            os.close(control_write)
            os.close(status_read)
            raise
    finally:
        os.close(control_read)
        os.close(status_write)

    try:
        status = await asyncio.to_thread(_read_launch_status, status_read)
        command_pid = _parse_launch_status(status)
    except BaseException:
        with suppress(OSError):
            os.close(control_write)
        if process is not None:
            await process.wait()
        raise
    return PosixGuardianProcess(
        process,
        command_pid=command_pid,
        control_descriptor=control_write,
    )


def _guardian_command_arguments(claim: CommandRunLaunchClaim) -> tuple[str, ...]:
    command = claim.request.command
    if isinstance(command, CommandArgvSpec):
        return ("argv", *command.argv)
    if isinstance(command, CommandShellSpec):
        return ("shell", command.command)
    raise TypeError(f"unsupported command specification: {type(command).__name__}")


def _read_launch_status(descriptor: int) -> bytes:
    try:
        payload = bytearray()
        while len(payload) <= _LAUNCH_STATUS_LIMIT:
            chunk = os.read(descriptor, _LAUNCH_STATUS_LIMIT + 1 - len(payload))
            if not chunk:
                return bytes(payload)
            payload.extend(chunk)
        raise RuntimeError("POSIX guardian launch status exceeded its bound")
    finally:
        os.close(descriptor)


def _parse_launch_status(status: bytes) -> int:
    try:
        text = status.decode("ascii", errors="strict").strip()
    except UnicodeError as exc:
        raise RuntimeError("POSIX guardian returned an invalid launch status") from exc
    if text.startswith("OK "):
        command_pid = int(text.removeprefix("OK "))
        if command_pid > 0:
            return command_pid
    if text.startswith("ERR "):
        error_number = int(text.removeprefix("ERR "))
        if error_number == errno.ENOENT:
            raise FileNotFoundError("command executable was not found")
        raise OSError(error_number, "POSIX guardian could not launch the command")
    raise RuntimeError("POSIX guardian did not confirm command launch")


__all__ = [
    "PosixGuardianProcess",
    "spawn_posix_guardian_process",
]
