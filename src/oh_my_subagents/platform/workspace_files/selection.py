from __future__ import annotations

import errno
import os
from contextlib import AbstractContextManager
from functools import cache
from pathlib import Path

from oh_my_subagents.platform.workspace_files.contracts import (
    PrivateFileOperations,
    PrivatePathError,
    WorkspaceFileOperations,
)


def ensure_private_directory(path: Path) -> None:
    select_private_file_operations().ensure_directory(path)


def protect_private_path(path: Path, *, is_directory: bool) -> None:
    select_private_file_operations().protect_path(path, is_directory=is_directory)


def read_private_text(path: Path) -> str | None:
    return select_private_file_operations().read_text(path)


def replace_private_text(path: Path, text: str) -> None:
    select_private_file_operations().replace_text(path, text)


def acquire_private_mutation_lock(
    path: Path,
    *,
    timeout_seconds: float,
) -> AbstractContextManager[None]:
    return select_private_file_operations().acquire_mutation_lock(
        path,
        timeout_seconds=timeout_seconds,
    )


def select_private_file_operations(
    platform_name: str | None = None,
) -> PrivateFileOperations:
    """Select the native private-file implementation for one host family."""

    return _select_private_file_operations(platform_name or os.name)


def select_workspace_file_operations(
    platform_name: str | None = None,
) -> WorkspaceFileOperations:
    """Select retained native Task-workspace operations for one host family."""

    return _select_workspace_file_operations(platform_name or os.name)


@cache
def _select_private_file_operations(platform_name: str) -> PrivateFileOperations:
    if platform_name == "posix":
        from oh_my_subagents.platform.workspace_files.posix import PosixPrivateFileOperations

        return PosixPrivateFileOperations()
    if platform_name == "nt":
        from oh_my_subagents.platform.workspace_files.windows import WindowsPrivateFileOperations

        return WindowsPrivateFileOperations()
    raise PrivatePathError(
        errno.ENOTSUP,
        "Oh My Subagents private filesystem operations support Linux, macOS, and Windows only; "
        f"platform '{platform_name}' is unsupported",
    )


@cache
def _select_workspace_file_operations(platform_name: str) -> WorkspaceFileOperations:
    if platform_name == "posix":
        from oh_my_subagents.platform.workspace_files.workspace_posix import (
            PosixWorkspaceFileOperations,
        )

        return PosixWorkspaceFileOperations()
    if platform_name == "nt":
        from oh_my_subagents.platform.workspace_files.workspace_windows import (
            WindowsWorkspaceFileOperations,
        )

        return WindowsWorkspaceFileOperations()
    raise PrivatePathError(
        errno.ENOTSUP,
        "Oh My Subagents Task workspace operations support Linux, macOS, and Windows only; "
        f"platform '{platform_name}' is unsupported",
    )


__all__ = [
    "acquire_private_mutation_lock",
    "ensure_private_directory",
    "protect_private_path",
    "read_private_text",
    "replace_private_text",
    "select_private_file_operations",
    "select_workspace_file_operations",
]
