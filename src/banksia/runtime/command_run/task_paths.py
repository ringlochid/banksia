from __future__ import annotations

import asyncio
import errno
import fcntl
import os
import stat
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from banksia.runtime.command_run.output_files import (
    CommandOutputFile,
    create_command_output_file,
)
from banksia.runtime.command_run.transitions import CommandRunLaunchClaim
from banksia.runtime.task_root import (
    command_run_output_path,
    read_task_root_paths,
)

type CommandSessionContextFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

_PROC_SELF_FD = Path("/proc/self/fd")


@dataclass(frozen=True, slots=True)
class StableCommandWorkingDirectory:
    """Retained directory identity used as the child process working directory."""

    descriptor: int


class CommandProcessPaths:
    """Resolve command workspace paths and provision controller-owned logs."""

    def __init__(self, session_factory: CommandSessionContextFactory) -> None:
        self._session_factory = session_factory

    async def open_working_directory(
        self,
        claim: CommandRunLaunchClaim,
    ) -> StableCommandWorkingDirectory:
        async with self._session_factory() as session:
            paths = await read_task_root_paths(session, claim.task_id)
        logical_cwd = claim.request.cwd or "."
        return open_stable_command_working_directory(
            paths.workspace_path,
            logical_cwd,
        )

    async def create_output_file(
        self,
        claim: CommandRunLaunchClaim,
    ) -> CommandOutputFile:
        async with self._session_factory() as session:
            paths = await read_task_root_paths(session, claim.task_id)
        expected_path = command_run_output_path(
            task_id=claim.task_id,
            run_id=claim.run_id,
        ).as_posix()
        if claim.output_path != expected_path:
            raise ValueError("command output path does not match its Task and Command IDs")
        return await asyncio.to_thread(
            create_command_output_file,
            paths.workspace_path,
            task_id=claim.task_id,
            run_id=claim.run_id,
        )


def open_stable_command_working_directory(
    workspace: Path,
    logical_cwd: str,
) -> StableCommandWorkingDirectory:
    """Open a no-follow directory chain and retain its exact identity for launch."""

    _require_stable_command_cwd_support()
    normalized = normalize_command_working_directory(logical_cwd)
    components = () if normalized == "." else tuple(normalized.split("/"))

    current_descriptor = _open_absolute_directory(workspace)
    try:
        for component in components:
            next_descriptor = os.open(
                component,
                _directory_open_flags(),
                dir_fd=current_descriptor,
            )
            os.close(current_descriptor)
            current_descriptor = next_descriptor
        current_descriptor = _move_descriptor_above_standard_streams(current_descriptor)
        if not stat.S_ISDIR(os.fstat(current_descriptor).st_mode):
            raise NotADirectoryError("command cwd is not an existing directory")
        return StableCommandWorkingDirectory(descriptor=current_descriptor)
    except BaseException:
        os.close(current_descriptor)
        raise


def normalize_command_working_directory(value: str) -> str:
    """Validate one canonical POSIX-style path relative to the Task workspace."""

    if not value or "\x00" in value or "\\" in value or value.startswith("/"):
        raise ValueError("command cwd must be a normalized workspace-relative directory")
    if len(value) >= 2 and value[0].isalpha() and value[1] == ":":
        raise ValueError("command cwd must be a normalized workspace-relative directory")
    if value == ".":
        return value
    components = tuple(value.split("/"))
    if any(component in {"", ".", ".."} for component in components):
        raise ValueError("command cwd must be a normalized workspace-relative directory")
    return value


def command_working_directory_spawn_path(
    working_directory: StableCommandWorkingDirectory,
) -> str:
    """Return the Linux descriptor path only when it still names the retained directory."""

    _require_stable_command_cwd_support()
    descriptor_metadata = os.fstat(working_directory.descriptor)
    if not stat.S_ISDIR(descriptor_metadata.st_mode):
        raise NotADirectoryError("command cwd descriptor is not a directory")
    spawn_path = _PROC_SELF_FD / str(working_directory.descriptor)
    try:
        spawn_metadata = os.stat(spawn_path)
    except OSError as exc:
        raise OSError(
            errno.ENOTSUP,
            "stable command cwd descriptor path is unavailable",
        ) from exc
    if (
        spawn_metadata.st_dev != descriptor_metadata.st_dev
        or spawn_metadata.st_ino != descriptor_metadata.st_ino
    ):
        raise OSError(
            errno.ESTALE,
            "stable command cwd descriptor path changed identity",
        )
    return spawn_path.as_posix()


def close_command_working_directory(
    working_directory: StableCommandWorkingDirectory,
) -> None:
    """Release one retained command working-directory descriptor."""

    os.close(working_directory.descriptor)


def _open_absolute_directory(path: Path) -> int:
    absolute_path = Path(path)
    if not absolute_path.is_absolute():
        raise ValueError("command workspace must be absolute")

    current_descriptor = os.open(os.path.sep, _directory_open_flags())
    try:
        for component in absolute_path.parts[1:]:
            next_descriptor = os.open(
                component,
                _directory_open_flags(),
                dir_fd=current_descriptor,
            )
            os.close(current_descriptor)
            current_descriptor = next_descriptor
        return current_descriptor
    except BaseException:
        os.close(current_descriptor)
        raise


def _move_descriptor_above_standard_streams(descriptor: int) -> int:
    if descriptor > 2:
        return descriptor
    replacement = fcntl.fcntl(
        descriptor,
        fcntl.F_DUPFD_CLOEXEC,
        3,
    )
    os.close(descriptor)
    return replacement


def _directory_open_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _require_stable_command_cwd_support() -> None:
    required = (
        os.name == "posix",
        hasattr(os, "O_DIRECTORY"),
        hasattr(os, "O_NOFOLLOW"),
        os.open in os.supports_dir_fd,
        _PROC_SELF_FD.is_dir(),
    )
    if not all(required):
        raise OSError(
            errno.ENOTSUP,
            "stable descriptor-backed command cwd is unavailable",
        )


__all__ = [
    "CommandProcessPaths",
    "CommandSessionContextFactory",
    "StableCommandWorkingDirectory",
    "close_command_working_directory",
    "command_working_directory_spawn_path",
    "normalize_command_working_directory",
    "open_stable_command_working_directory",
]
