from __future__ import annotations

import errno
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Literal

from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.task_root.logical_paths import (
    LOGICAL_TASK_ROOTS,
    ResolvedLogicalTaskPath,
    resolve_logical_task_path,
)

DEFAULT_DIRECTORY_ENTRY_LIMIT = 1_000
DEFAULT_FILE_READ_BYTE_LIMIT = 1_048_576
type LogicalDirectoryEntryKind = Literal["file", "directory", "symlink", "other"]
type LogicalDirectoryEntry = tuple[str, str, LogicalDirectoryEntryKind, int | None]


@dataclass(frozen=True, slots=True)
class PublishedLogicalFile:
    source_logical_path: str
    destination_logical_path: str
    size_bytes: int
    source_mtime_ns: int


def list_logical_directory(
    paths: object,
    directory: str,
    *,
    entry_limit: int = DEFAULT_DIRECTORY_ENTRY_LIMIT,
) -> tuple[str, tuple[LogicalDirectoryEntry, ...]]:
    from autoclaw.runtime.contracts import TaskRootPaths

    if not isinstance(paths, TaskRootPaths):
        raise TypeError("paths must be TaskRootPaths")
    if entry_limit < 0:
        raise ValueError("entry_limit must be non-negative")

    resolved = resolve_logical_task_path(paths, directory, is_root_listing_allowed=True)
    if resolved is None:
        root_entries = tuple(LOGICAL_TASK_ROOTS[: entry_limit + 1])
        if len(root_entries) > entry_limit:
            raise _directory_limit_error()
        return ".", tuple((name, name, "directory", None) for name in sorted(root_entries))

    _require_descriptor_access(needs_scandir=True)
    with _opened_resolved_target(resolved, require_directory=True) as directory_fd:
        try:
            with os.scandir(directory_fd) as iterator:
                children = list(islice(iterator, entry_limit + 1))
                if len(children) > entry_limit:
                    raise _directory_limit_error()
                entries = [
                    _logical_directory_entry(resolved.logical_path, child) for child in children
                ]
        except RuntimeOperationError:
            raise
        except OSError as exc:
            raise _descriptor_error(exc, require_directory=True) from exc

    entries.sort(key=lambda entry: entry[0])
    return resolved.logical_path, tuple(entries)


def read_logical_text_file(
    paths: object,
    logical_path: str,
    *,
    start_line: int,
    max_lines: int,
    byte_limit: int = DEFAULT_FILE_READ_BYTE_LIMIT,
) -> tuple[str, str, int, bool, int | None]:
    from autoclaw.runtime.contracts import TaskRootPaths

    if not isinstance(paths, TaskRootPaths):
        raise TypeError("paths must be TaskRootPaths")
    if byte_limit < 0:
        raise ValueError("byte_limit must be non-negative")

    resolved = resolve_logical_task_path(paths, logical_path)
    assert resolved is not None
    _require_descriptor_access(needs_scandir=False)
    with _opened_resolved_target(resolved, require_directory=False) as file_fd:
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
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _file_error(OperationFailureCode.BINARY_FILE, "file is not UTF-8 text") from exc

    lines = text.splitlines(keepends=True)
    selected = lines[start_line - 1 : start_line - 1 + max_lines]
    has_more = start_line - 1 + len(selected) < len(lines)
    next_start_line = start_line + len(selected) if has_more else None
    return resolved.logical_path, "".join(selected), len(selected), has_more, next_start_line


def read_logical_regular_file_bytes(
    paths: object,
    logical_path: str,
    *,
    byte_limit: int = DEFAULT_FILE_READ_BYTE_LIMIT,
) -> bytes:
    """Read one contained regular file through descriptor-relative traversal."""
    from autoclaw.runtime.contracts import TaskRootPaths

    if not isinstance(paths, TaskRootPaths):
        raise TypeError("paths must be TaskRootPaths")
    if byte_limit < 0:
        raise ValueError("byte_limit must be non-negative")

    resolved = resolve_logical_task_path(paths, logical_path)
    assert resolved is not None
    _require_descriptor_access(needs_scandir=False)
    with _opened_resolved_target(resolved, require_directory=False) as file_fd:
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


def publish_logical_regular_file(
    paths: object,
    source_logical_path: str,
    destination_logical_path: str,
) -> PublishedLogicalFile:
    """Copy one stable regular file to a new immutable controller-owned path."""
    from autoclaw.runtime.contracts import TaskRootPaths

    if not isinstance(paths, TaskRootPaths):
        raise TypeError("paths must be TaskRootPaths")
    source = resolve_logical_task_path(paths, source_logical_path)
    assert source is not None
    destination = resolve_logical_task_path(paths, destination_logical_path)
    assert destination is not None
    destination_parts = tuple(destination.logical_path.split("/"))
    if destination_parts[0] not in {"outputs", "tmp"}:
        raise _file_error(
            OperationFailureCode.INVALID_TASK_PATH,
            "published bodies must use outputs or tmp",
        )
    _require_publication_descriptor_access()

    with _opened_resolved_target(source, require_directory=False) as source_fd:
        initial = os.fstat(source_fd)
        if not stat.S_ISREG(initial.st_mode):
            raise _file_error(OperationFailureCode.NOT_A_FILE, "task path is not a regular file")
        with _opened_or_created_task_directory(
            paths.task_root,
            destination_parts[:-1],
        ) as parent_fd:
            return _copy_and_publish(
                source_fd=source_fd,
                source_logical_path=source.logical_path,
                destination_logical_path=destination.logical_path,
                destination_name=destination_parts[-1],
                destination_parent_fd=parent_fd,
                initial=initial,
            )


def _copy_and_publish(
    *,
    source_fd: int,
    source_logical_path: str,
    destination_logical_path: str,
    destination_name: str,
    destination_parent_fd: int,
    initial: os.stat_result,
) -> PublishedLogicalFile:
    stage_name = f".stage-{destination_name}-{os.urandom(8).hex()}"
    stage_fd = -1
    linked = False
    try:
        stage_fd = os.open(
            stage_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=destination_parent_fd,
        )
        copied = 0
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            copied += len(chunk)
            _write_all(stage_fd, chunk)
        final = os.fstat(source_fd)
        if (
            copied != initial.st_size
            or final.st_size != initial.st_size
            or final.st_mtime_ns != initial.st_mtime_ns
        ):
            raise RuntimeOperationError(
                code=OperationFailureCode.CONFLICT,
                summary="checkpoint source changed while its body was copied",
                is_retryable=False,
            )
        os.fsync(stage_fd)
        os.close(stage_fd)
        stage_fd = -1
        os.link(
            stage_name,
            destination_name,
            src_dir_fd=destination_parent_fd,
            dst_dir_fd=destination_parent_fd,
            follow_symlinks=False,
        )
        linked = True
        os.unlink(stage_name, dir_fd=destination_parent_fd)
        os.fsync(destination_parent_fd)
    except FileExistsError as exc:
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="immutable checkpoint body path already exists",
            is_retryable=False,
        ) from exc
    finally:
        if stage_fd >= 0:
            os.close(stage_fd)
        if not linked:
            try:
                os.unlink(stage_name, dir_fd=destination_parent_fd)
            except FileNotFoundError:
                pass
    return PublishedLogicalFile(
        source_logical_path=source_logical_path,
        destination_logical_path=destination_logical_path,
        size_bytes=initial.st_size,
        source_mtime_ns=initial.st_mtime_ns,
    )


def _write_all(file_descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(file_descriptor, view)
        view = view[written:]


@contextmanager
def _opened_or_created_task_directory(
    task_root: Path,
    components: tuple[str, ...],
) -> Iterator[int]:
    current_fd = _open_absolute_directory(task_root)
    try:
        for component in components:
            try:
                next_fd = _open_path_component(
                    component,
                    flags=_directory_open_flags(),
                    parent_fd=current_fd,
                )
            except FileNotFoundError:
                os.mkdir(component, mode=0o700, dir_fd=current_fd)
                os.fsync(current_fd)
                next_fd = _open_path_component(
                    component,
                    flags=_directory_open_flags(),
                    parent_fd=current_fd,
                )
            os.close(current_fd)
            current_fd = next_fd
        yield current_fd
    finally:
        os.close(current_fd)


def _read_bounded_bytes(file_fd: int, *, byte_limit: int) -> bytes:
    payload = bytearray()
    while len(payload) <= byte_limit:
        remaining = byte_limit + 1 - len(payload)
        chunk = os.read(file_fd, remaining)
        if not chunk:
            break
        payload.extend(chunk)
    return bytes(payload)


def _logical_directory_entry(
    logical_directory: str,
    entry: os.DirEntry[str],
) -> LogicalDirectoryEntry:
    metadata = entry.stat(follow_symlinks=False)
    kind, size = _entry_kind_and_size(metadata)
    return entry.name, f"{logical_directory}/{entry.name}", kind, size


def _entry_kind_and_size(
    metadata: os.stat_result,
) -> tuple[LogicalDirectoryEntryKind, int | None]:
    if stat.S_ISLNK(metadata.st_mode):
        return "symlink", None
    if stat.S_ISREG(metadata.st_mode):
        return "file", metadata.st_size
    if stat.S_ISDIR(metadata.st_mode):
        return "directory", None
    return "other", None


@contextmanager
def _opened_resolved_target(
    resolved: ResolvedLogicalTaskPath,
    *,
    require_directory: bool,
) -> Iterator[int]:
    try:
        file_descriptor = _open_canonical_target(
            resolved,
            require_directory=require_directory,
        )
    except RuntimeOperationError:
        raise
    except OSError as exc:
        raise _descriptor_error(exc, require_directory=require_directory) from exc
    try:
        yield file_descriptor
    finally:
        os.close(file_descriptor)


def _open_canonical_target(
    resolved: ResolvedLogicalTaskPath,
    *,
    require_directory: bool,
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
            flags = (
                _directory_open_flags() if not is_final or require_directory else _file_open_flags()
            )
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


def _require_descriptor_access(*, needs_scandir: bool) -> None:
    descriptor_scan_available = not needs_scandir or os.scandir in os.supports_fd
    if _descriptor_walk_available() and descriptor_scan_available:
        return
    raise _file_error(
        OperationFailureCode.INVALID_TASK_ROOT,
        "safe descriptor-relative task file access is unavailable on this platform",
    )


def _require_publication_descriptor_access() -> None:
    if (
        _descriptor_walk_available()
        and os.mkdir in os.supports_dir_fd
        and os.link in os.supports_dir_fd
        and os.unlink in os.supports_dir_fd
        and os.link in os.supports_follow_symlinks
    ):
        return
    raise _file_error(
        OperationFailureCode.INVALID_TASK_ROOT,
        "safe descriptor-relative task file publication is unavailable on this platform",
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
    *,
    require_directory: bool,
) -> RuntimeOperationError:
    if isinstance(exc, FileNotFoundError):
        return _file_error(OperationFailureCode.MISSING_RESOURCE, "task path does not exist")
    if exc.errno == errno.ELOOP:
        return _file_error(
            OperationFailureCode.PATH_ESCAPE,
            "task path changed to a symlink while it was being opened",
        )
    code = (
        OperationFailureCode.NOT_A_DIRECTORY
        if require_directory
        else OperationFailureCode.NOT_A_FILE
    )
    summary = (
        "task path is not a safely readable directory"
        if require_directory
        else "task path is not a safely readable regular file"
    )
    return _file_error(code, summary)


def _directory_limit_error() -> RuntimeOperationError:
    return _file_error(
        OperationFailureCode.DIRECTORY_LIMIT_EXCEEDED,
        "directory exceeds the configured entry limit",
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
    "DEFAULT_DIRECTORY_ENTRY_LIMIT",
    "DEFAULT_FILE_READ_BYTE_LIMIT",
    "LogicalDirectoryEntry",
    "LogicalDirectoryEntryKind",
    "PublishedLogicalFile",
    "list_logical_directory",
    "publish_logical_regular_file",
    "read_logical_text_file",
]
