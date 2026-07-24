from __future__ import annotations

import errno
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


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

    with open_workspace_regular_file(workspace, relative_path) as descriptor:
        metadata = os.fstat(descriptor)
        if offset > metadata.st_size:
            offset = metadata.st_size
        os.lseek(descriptor, offset, os.SEEK_SET)
        payload = _read_bounded_bytes(descriptor, byte_limit=byte_limit)
        file_size = os.fstat(descriptor).st_size

    end_offset = offset + len(payload)
    return WorkspaceFileRead(
        payload=payload,
        file_size=file_size,
        next_offset=end_offset if end_offset < file_size else None,
    )


@contextmanager
def open_workspace_regular_file(
    workspace: Path,
    relative_path: str,
) -> Iterator[int]:
    """Open one existing regular file through an all-component no-follow walk."""

    _require_descriptor_walk()
    components = _normalized_relative_components(relative_path)

    current_descriptor = os.open(workspace, _directory_open_flags())
    try:
        for index, component in enumerate(components):
            flags = (
                _regular_file_open_flags()
                if index == len(components) - 1
                else _directory_open_flags()
            )
            next_descriptor = _open_component(
                current_descriptor,
                component,
                flags=flags,
            )
            os.close(current_descriptor)
            current_descriptor = next_descriptor
        metadata = os.fstat(current_descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise UnsafeWorkspaceFileError(
                errno.EINVAL,
                "workspace path is not a regular file",
                relative_path,
            )
        yield current_descriptor
    finally:
        os.close(current_descriptor)


def _read_bounded_bytes(descriptor: int, *, byte_limit: int) -> bytes:
    payload = bytearray()
    while len(payload) < byte_limit:
        chunk = os.read(descriptor, min(64 * 1024, byte_limit - len(payload)))
        if not chunk:
            break
        payload.extend(chunk)
    return bytes(payload)


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


def _open_component(
    parent_descriptor: int,
    component: str,
    *,
    flags: int,
) -> int:
    try:
        return os.open(component, flags, dir_fd=parent_descriptor)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR} and _is_symlink(
            parent_descriptor,
            component,
        ):
            raise UnsafeWorkspaceFileError(
                errno.ELOOP,
                "workspace path contains a symbolic link",
                component,
            ) from exc
        raise


def _is_symlink(parent_descriptor: int, component: str) -> bool:
    try:
        metadata = os.stat(
            component,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except OSError:
        return False
    return stat.S_ISLNK(metadata.st_mode)


def _directory_open_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _regular_file_open_flags() -> int:
    return os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)


def _require_descriptor_walk() -> None:
    required = (
        os.name == "posix",
        hasattr(os, "O_DIRECTORY"),
        hasattr(os, "O_NOFOLLOW"),
        os.open in os.supports_dir_fd,
        os.stat in os.supports_dir_fd,
        os.stat in os.supports_follow_symlinks,
    )
    if not all(required):
        raise UnsafeWorkspaceFileError(
            errno.ENOTSUP,
            "safe descriptor-relative workspace file access is unavailable",
        )


__all__ = [
    "UnsafeWorkspaceFileError",
    "WorkspaceFileRead",
    "open_workspace_regular_file",
    "read_workspace_regular_file_range",
    "validate_workspace_regular_file",
]
