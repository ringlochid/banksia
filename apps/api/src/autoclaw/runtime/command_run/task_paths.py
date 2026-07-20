from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.runtime.command_run.process_resources import (
    create_command_log_pair,
    remove_command_log_pair,
)
from autoclaw.runtime.command_run.transitions import CommandRunLaunchClaim
from autoclaw.runtime.task_root import (
    read_task_root_paths,
    resolve_logical_task_path,
)

logger = logging.getLogger(__name__)

type CommandSessionContextFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class CommandProcessPaths:
    """Resolve command workspace paths and provision controller-owned logs."""

    def __init__(self, session_factory: CommandSessionContextFactory) -> None:
        self._session_factory = session_factory

    async def resolve_working_directory(self, claim: CommandRunLaunchClaim) -> Path:
        async with self._session_factory() as session:
            paths = await read_task_root_paths(session, claim.task_id)
        logical_cwd = claim.request.cwd or "workspace"
        resolved = resolve_logical_task_path(paths, logical_cwd)
        assert resolved is not None
        if resolved.logical_path != "workspace" and not resolved.logical_path.startswith(
            "workspace/"
        ):
            raise ValueError("command cwd is outside the task workspace")
        if not resolved.physical_path.is_dir():
            raise NotADirectoryError("command cwd is not an existing directory")
        return resolved.physical_path

    async def create_log_files(
        self,
        claim: CommandRunLaunchClaim,
    ) -> tuple[Path, Path]:
        async with self._session_factory() as session:
            paths = await read_task_root_paths(session, claim.task_id)
        stdout = resolve_logical_task_path(paths, claim.stdout_log_ref)
        stderr = resolve_logical_task_path(paths, claim.stderr_log_ref)
        assert stdout is not None and stderr is not None
        await asyncio.to_thread(
            create_command_log_pair,
            stdout.physical_path,
            stderr.physical_path,
        )
        return stdout.physical_path, stderr.physical_path

    async def cleanup_unreferenced_log_files(
        self,
        stdout_path: Path,
        stderr_path: Path,
    ) -> None:
        try:
            await asyncio.to_thread(
                remove_command_log_pair,
                stdout_path,
                stderr_path,
            )
        except Exception as exc:
            logger.warning(
                "unreferenced command log cleanup failed",
                extra={"exception_type": type(exc).__name__},
            )


__all__ = ["CommandProcessPaths", "CommandSessionContextFactory"]
