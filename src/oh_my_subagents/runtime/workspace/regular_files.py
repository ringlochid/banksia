from __future__ import annotations

import errno
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from oh_my_subagents.platform.workspace_files import (
    RegularFileLease,
    select_workspace_file_operations,
)


class UnsafeWorkspaceFileError(OSError):
    """Raised when a workspace path cannot be opened without following links."""


@dataclass(frozen=True, slots=True)
class WorkspaceFileRead:
    payload: bytes
    file_size: int
    next_offset: int | None


def validate_workspace_regular_file(
    workspace: Path,
    relative_path: str,
) -> None:
    """Prove that one normalized relative path currently names a real file."""

    with open_workspace_regular_file(workspace, relative_path):
        return


def read_workspace_regular_file_range(
    workspace: Path,
    relative_path: str,
    *,
    offset: int,
    byte_limit: int,
) -> WorkspaceFileRead:
    """Read one bounded current byte range without treating the file as immutable."""

    if offset < 0:
        raise ValueError("workspace file read offset must be non-negative")
    if byte_limit < 1:
        raise ValueError("workspace file read limit must be positive")

    operations = select_workspace_file_operations()
    with open_workspace_regular_file(workspace, relative_path) as file:
        payload, file_size = operations.read_regular_file_range(
            file,
            offset=offset,
            byte_limit=byte_limit,
        )

    selected_offset = min(offset, file_size)
    end_offset = selected_offset + len(payload)
    return WorkspaceFileRead(
        payload=payload,
        file_size=file_size,
        next_offset=end_offset if end_offset < file_size else None,
    )


@contextmanager
def open_workspace_regular_file(
    workspace: Path,
    relative_path: str,
) -> Iterator[RegularFileLease]:
    """Retain one existing regular file through an all-component no-follow walk."""

    components = _normalized_relative_components(relative_path)
    try:
        file = select_workspace_file_operations().open_regular_file(
            workspace,
            components,
        )
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise UnsafeWorkspaceFileError(
                errno.ELOOP,
                "workspace path contains a symbolic link",
                relative_path,
            ) from exc
        raise
    try:
        yield file
    finally:
        file.close()


def _normalized_relative_components(relative_path: str) -> tuple[str, ...]:
    if (
        not relative_path
        or "\x00" in relative_path
        or "\\" in relative_path
        or relative_path.startswith("/")
    ):
        raise UnsafeWorkspaceFileError(
            errno.EINVAL,
            "workspace file path must be normalized and workspace-relative",
            relative_path,
        )
    components = tuple(relative_path.split("/"))
    if any(component in {"", ".", ".."} for component in components):
        raise UnsafeWorkspaceFileError(
            errno.EINVAL,
            "workspace file path must be normalized and workspace-relative",
            relative_path,
        )
    return components


__all__ = [
    "UnsafeWorkspaceFileError",
    "WorkspaceFileRead",
    "open_workspace_regular_file",
    "read_workspace_regular_file_range",
    "validate_workspace_regular_file",
]
