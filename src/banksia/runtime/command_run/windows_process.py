from __future__ import annotations

import asyncio
import errno
import os
import sys
from contextlib import suppress
from pathlib import Path

from banksia.platform.workspace_files.workspace_windows import (
    require_windows_directory_lease,
)
from banksia.runtime.command_run.task_paths import StableCommandWorkingDirectory
from banksia.runtime.command_run.transitions import CommandRunLaunchClaim
from banksia.runtime.contracts import CommandArgvSpec, CommandShellSpec

_GUARDIAN_PATH = Path(__file__).with_name("windows_guardian.py")
_LAUNCH_STATUS_LIMIT = 128


class WindowsGuardianProcess:
    """Async controller handle for one Job-owned Windows command family."""

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        *,
        command_pid: int,
    ) -> None:
        self._process = process
        self._command_pid = command_pid

    @property
    def pid(self) -> int:
        return self._command_pid

    @property
    def returncode(self) -> int | None:
        value = self._process.returncode
        return None if value is None else value & 0xFFFF_FFFF

    async def read_output(self, byte_limit: int) -> bytes:
        stream = self._process.stdout
        if stream is None:
            raise RuntimeError("Windows guardian output pipe is unavailable")
        return await stream.read(byte_limit)

    async def wait(self) -> int:
        return (await self._process.wait()) & 0xFFFF_FFFF

    def request_termination(self) -> None:
        self._terminate_guardian(should_kill=False)

    def request_kill(self) -> None:
        self._terminate_guardian(should_kill=True)

    def close_controller_liveness(self) -> None:
        stream = self._process.stdin
        if stream is not None and not stream.is_closing():
            stream.close()

    def _terminate_guardian(self, *, should_kill: bool) -> None:
        with suppress(ProcessLookupError, OSError):
            if should_kill:
                self._process.kill()
            else:
                self._process.terminate()


async def spawn_windows_guardian_process(
    claim: CommandRunLaunchClaim,
    *,
    working_directory: StableCommandWorkingDirectory,
    environment: dict[str, str],
) -> WindowsGuardianProcess:
    """Start a guardian that assigns a suspended child to a kill-on-close Job."""

    if os.name != "nt":
        raise OSError(errno.ENOTSUP, "Windows Command Run supervision is unavailable")
    directory = require_windows_directory_lease(working_directory.directory)
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(_GUARDIAN_PATH),
        str(directory.path),
        *_guardian_command_arguments(claim),
        env=environment,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        creationflags=0x08000000,
    )
    stream = process.stdout
    assert stream is not None
    try:
        status = await stream.readline()
        if len(status) > _LAUNCH_STATUS_LIMIT:
            raise RuntimeError("Windows guardian launch status exceeded its bound")
        command_pid = _parse_launch_status(status)
    except BaseException:
        if process.stdin is not None:
            process.stdin.close()
        await process.wait()
        raise
    return WindowsGuardianProcess(process, command_pid=command_pid)


def _guardian_command_arguments(claim: CommandRunLaunchClaim) -> tuple[str, ...]:
    command = claim.request.command
    if isinstance(command, CommandArgvSpec):
        return ("argv", *command.argv)
    if isinstance(command, CommandShellSpec):
        return ("shell", command.command)
    raise TypeError(f"unsupported command specification: {type(command).__name__}")


def _parse_launch_status(status: bytes) -> int:
    try:
        text = status.decode("ascii", errors="strict").strip()
    except UnicodeError as exc:
        raise RuntimeError("Windows guardian returned an invalid launch status") from exc
    if text.startswith("OK "):
        command_pid = int(text.removeprefix("OK "))
        if command_pid > 0:
            return command_pid
    if text.startswith("ERR "):
        error_number = int(text.removeprefix("ERR "))
        if error_number in {2, 3}:
            raise FileNotFoundError("command executable was not found")
        raise OSError(error_number, "Windows guardian could not launch the command")
    raise RuntimeError("Windows guardian did not confirm command launch")


__all__ = ["WindowsGuardianProcess", "spawn_windows_guardian_process"]
