from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from banksia.platform.workspace_files import (
    DirectoryLease,
    select_workspace_file_operations,
)
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


@dataclass(frozen=True, slots=True, init=False)
class StableCommandWorkingDirectory:
    """Opaque retained native authority for one admitted command directory."""

    _directory: DirectoryLease

    def __init__(self, directory: DirectoryLease) -> None:
        object.__setattr__(self, "_directory", directory)

    @property
    def descriptor(self) -> int:
        """Return the guardian descriptor on a POSIX host."""

        return select_workspace_file_operations().directory_descriptor(self._directory)

    def close(self) -> None:
        self._directory.close()


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
    """Retain a no-follow directory chain until native process ownership exists."""

    normalized = normalize_command_working_directory(logical_cwd)
    components = () if normalized == "." else tuple(normalized.split("/"))
    directory = select_workspace_file_operations().open_command_directory(
        workspace,
        components,
    )
    return StableCommandWorkingDirectory(directory)


def normalize_command_working_directory(value: str) -> str:
    """Validate one canonical path relative to the Task workspace."""

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


def close_command_working_directory(
    working_directory: StableCommandWorkingDirectory,
) -> None:
    """Release one retained native command working-directory authority."""

    working_directory.close()


__all__ = [
    "CommandProcessPaths",
    "CommandSessionContextFactory",
    "StableCommandWorkingDirectory",
    "close_command_working_directory",
    "normalize_command_working_directory",
    "open_stable_command_working_directory",
]
