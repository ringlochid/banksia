from __future__ import annotations

import errno
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.task_root.logical_paths import (
    ResolvedLogicalTaskPath,
    resolve_logical_task_path,
)

DEFAULT_FILE_READ_BYTE_LIMIT = 1_048_576


def read_logical_regular_file_bytes(
    paths: object,
    logical_path: str,
    *,
    byte_limit: int = DEFAULT_FILE_READ_BYTE_LIMIT,
) -> bytes:
    """Read one contained regular file through descriptor-relative traversal."""
    from banksia.runtime.contracts import TaskRootPaths

    if not isinstance(paths, TaskRootPaths):
        raise TypeError("paths must be TaskRootPaths")
    if byte_limit < 0:
        raise ValueError("byte_limit must be non-negative")

    resolved = resolve_logical_task_path(paths, logical_path)
    assert resolved is not None
    _require_descriptor_access()
    with _opened_resolved_target(resolved) as file_fd:
        metadata = os.fstat(file_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise _file_error(
                OperationFailureCode.NOT_A_FILE,
                "task path is not a regular file",
            )
        if metadata.st_size > byte_limit:
            raise _file_read_limit_error()
        payload = _read_bounded_bytes(file_fd, byte_limit=byte_limit)

    if len(payload) > byte_limit:
        raise _file_read_limit_error()
    return payload


def _read_bounded_bytes(file_fd: int, *, byte_limit: int) -> bytes:
    payload = bytearray()
    while len(payload) <= byte_limit:
        remaining = byte_limit + 1 - len(payload)
        chunk = os.read(file_fd, remaining)
        if not chunk:
            break
        payload.extend(chunk)
    return bytes(payload)


@contextmanager
def _opened_resolved_target(
    resolved: ResolvedLogicalTaskPath,
) -> Iterator[int]:
    try:
        file_descriptor = _open_canonical_target(resolved)
    except RuntimeOperationError:
        raise
    except OSError as exc:
        raise _descriptor_error(exc) from exc
    try:
        yield file_descriptor
    finally:
        os.close(file_descriptor)


def _open_canonical_target(
    resolved: ResolvedLogicalTaskPath,
) -> int:
    try:
        relative_target = resolved.physical_path.relative_to(resolved.physical_root)
    except ValueError as exc:
        raise _file_error(
            OperationFailureCode.PATH_ESCAPE,
            "resolved task path leaves its selected logical root",
        ) from exc

    current_fd = _open_absolute_directory(resolved.physical_root)
    try:
        components = relative_target.parts
        for index, component in enumerate(components):
            is_final = index == len(components) - 1
            flags = _file_open_flags() if is_final else _directory_open_flags()
            next_fd = _open_path_component(component, flags=flags, parent_fd=current_fd)
            previous_fd = current_fd
            current_fd = next_fd
            os.close(previous_fd)
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _open_absolute_directory(path: os.PathLike[str]) -> int:
    absolute_path = Path(path)
    if not absolute_path.is_absolute():
        raise _file_error(
            OperationFailureCode.INVALID_TASK_ROOT,
            "physical task root must be absolute",
        )

    current_fd = os.open(os.path.sep, _directory_open_flags())
    try:
        for component in absolute_path.parts[1:]:
            next_fd = _open_path_component(
                component,
                flags=_directory_open_flags(),
                parent_fd=current_fd,
            )
            previous_fd = current_fd
            current_fd = next_fd
            os.close(previous_fd)
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _directory_open_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _file_open_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )


def _open_path_component(component: str, *, flags: int, parent_fd: int) -> int:
    try:
        return os.open(component, flags, dir_fd=parent_fd)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR} and _is_symlink_at(
            component,
            parent_fd=parent_fd,
        ):
            raise OSError(
                errno.ELOOP,
                "task path component changed to a symlink",
                component,
            ) from exc
        raise


def _is_symlink_at(component: str, *, parent_fd: int) -> bool:
    try:
        return stat.S_ISLNK(
            os.stat(
                component,
                dir_fd=parent_fd,
                follow_symlinks=False,
            ).st_mode
        )
    except OSError:
        return False


def _require_descriptor_access() -> None:
    if _descriptor_walk_available():
        return
    raise _file_error(
        OperationFailureCode.INVALID_TASK_ROOT,
        "safe descriptor-relative task file access is unavailable on this platform",
    )


def _descriptor_walk_available() -> bool:
    return (
        os.name == "posix"
        and bool(getattr(os, "O_DIRECTORY", 0))
        and bool(getattr(os, "O_NOFOLLOW", 0))
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
    )


def _descriptor_error(
    exc: OSError,
) -> RuntimeOperationError:
    if isinstance(exc, FileNotFoundError):
        return _file_error(OperationFailureCode.MISSING_RESOURCE, "task path does not exist")
    if exc.errno == errno.ELOOP:
        return _file_error(
            OperationFailureCode.PATH_ESCAPE,
            "task path changed to a symlink while it was being opened",
        )
    return _file_error(
        OperationFailureCode.NOT_A_FILE,
        "task path is not a safely readable regular file",
    )


def _file_read_limit_error() -> RuntimeOperationError:
    return _file_error(
        OperationFailureCode.FILE_READ_LIMIT_EXCEEDED,
        "file exceeds the configured read limit",
    )


def _file_error(code: OperationFailureCode, summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=code,
        summary=summary,
        is_retryable=False,
        suggested_next_step="Reread the logical task path and choose a contained readable target.",
    )


__all__ = [
    "DEFAULT_FILE_READ_BYTE_LIMIT",
    "read_logical_regular_file_bytes",
]
