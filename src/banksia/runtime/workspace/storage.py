from __future__ import annotations

import errno
import os
import secrets
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

_DIRECTORY_MODE = 0o700
_FILE_MODE = 0o600
_MARKER_READ_LIMIT = 4_096


@dataclass(frozen=True, slots=True)
class WorkspaceIdentity:
    """Stable filesystem identity for one admitted workspace directory."""

    device: int
    inode: int


def capture_workspace_identity(workspace: Path) -> WorkspaceIdentity:
    """Open a real workspace directory and capture its stable identity."""

    _require_safe_workspace_primitives()
    descriptor = os.open(workspace, _directory_open_flags())
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise NotADirectoryError(workspace)
        return WorkspaceIdentity(device=metadata.st_dev, inode=metadata.st_ino)
    finally:
        os.close(descriptor)


def replace_task_text(
    workspace: Path,
    task_id: str,
    name: str,
    text: str,
) -> None:
    """Replace one controller projection in an existing physical Task root."""

    with open_banksia_root(workspace, should_create=False) as banksia_descriptor:
        if banksia_descriptor is None:
            raise FileNotFoundError(workspace / ".banksia")
        with open_task_root(banksia_descriptor, task_id) as task_descriptor:
            replace_text(task_descriptor, name, text)


@contextmanager
def reserve_task_root(
    workspace: Path,
    task_id: str,
    *,
    expected_workspace_identity: WorkspaceIdentity | None = None,
) -> Iterator[tuple[int, int]]:
    """Exclusively create and open one Task root under the workspace."""

    with open_banksia_root(
        workspace,
        should_create=True,
        expected_workspace_identity=expected_workspace_identity,
    ) as banksia_descriptor:
        assert banksia_descriptor is not None
        os.mkdir(task_id, _DIRECTORY_MODE, dir_fd=banksia_descriptor)
        try:
            task_descriptor = os.open(
                task_id,
                _directory_open_flags(),
                dir_fd=banksia_descriptor,
            )
        except BaseException:
            remove_task_tree(banksia_descriptor, task_id)
            raise
        try:
            _set_private_directory_mode(task_descriptor)
            yield banksia_descriptor, task_descriptor
        finally:
            os.close(task_descriptor)


@contextmanager
def open_banksia_root(
    workspace: Path,
    *,
    should_create: bool,
    expected_workspace_identity: WorkspaceIdentity | None = None,
) -> Iterator[int | None]:
    """Open the physical Banksia root without following its final component."""

    _require_safe_workspace_primitives()
    workspace_descriptor = os.open(workspace, _directory_open_flags())
    try:
        if expected_workspace_identity is not None:
            _require_workspace_identity(workspace_descriptor, expected_workspace_identity)
        if should_create:
            ensure_directory(workspace_descriptor, ".banksia")
        try:
            banksia_descriptor = os.open(
                ".banksia",
                _directory_open_flags(),
                dir_fd=workspace_descriptor,
            )
        except FileNotFoundError:
            if should_create:
                raise
            yield None
            return
        try:
            _set_private_directory_mode(banksia_descriptor)
            yield banksia_descriptor
        finally:
            os.close(banksia_descriptor)
    finally:
        os.close(workspace_descriptor)


@contextmanager
def open_task_root(
    banksia_descriptor: int,
    task_id: str,
) -> Iterator[int]:
    """Open one existing real Task directory without following a symlink."""

    with open_child_directory(banksia_descriptor, task_id) as task_descriptor:
        yield task_descriptor


@contextmanager
def open_child_directory(
    parent_descriptor: int,
    name: str,
) -> Iterator[int]:
    """Open one real child directory without following a symlink."""

    descriptor = os.open(
        name,
        _directory_open_flags(),
        dir_fd=parent_descriptor,
    )
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def ensure_directory(parent_descriptor: int, name: str) -> None:
    """Create or validate one private real child directory."""

    try:
        os.mkdir(name, _DIRECTORY_MODE, dir_fd=parent_descriptor)
    except FileExistsError:
        pass
    descriptor = os.open(
        name,
        _directory_open_flags(),
        dir_fd=parent_descriptor,
    )
    try:
        _set_private_directory_mode(descriptor)
    finally:
        os.close(descriptor)


def replace_text(parent_descriptor: int, name: str, text: str) -> None:
    """Atomically replace one Task projection without following its old entry."""

    temporary = f".{name}.{secrets.token_hex(8)}.repair"
    write_new_text(parent_descriptor, temporary, text)
    try:
        os.replace(
            temporary,
            name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
    except BaseException:
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=parent_descriptor)
        raise


def write_new_text(parent_descriptor: int, name: str, text: str) -> None:
    """Create, flush, and sync one private regular UTF-8 file."""

    descriptor = os.open(
        name,
        _file_create_flags(),
        _FILE_MODE,
        dir_fd=parent_descriptor,
    )
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="",
            closefd=False,
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def read_small_text(parent_descriptor: int, name: str) -> str | None:
    """Read one small real regular file without following a symlink."""

    try:
        descriptor = os.open(
            name,
            _file_read_flags(),
            dir_fd=parent_descriptor,
        )
    except OSError as exc:
        if exc.errno not in {
            errno.ELOOP,
            errno.ENOENT,
            errno.EISDIR,
            errno.ENOTDIR,
        }:
            raise
        return None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MARKER_READ_LIMIT:
            return None
        with os.fdopen(
            descriptor,
            "r",
            encoding="utf-8",
            newline="",
            closefd=False,
        ) as handle:
            try:
                return handle.read(_MARKER_READ_LIMIT + 1)
            except UnicodeError:
                return None
    finally:
        os.close(descriptor)


def remove_task_tree(banksia_descriptor: int, task_id: str) -> bool:
    """Remove one real Task directory using symlink-safe descriptor traversal."""

    try:
        shutil.rmtree(task_id, dir_fd=banksia_descriptor)
    except FileNotFoundError:
        return False
    return True


def unlink_entry(parent_descriptor: int, name: str) -> None:
    os.unlink(name, dir_fd=parent_descriptor)


def task_root_names(banksia_descriptor: int) -> tuple[str, ...]:
    return tuple(os.listdir(banksia_descriptor))


def is_real_directory(parent_descriptor: int, name: str) -> bool:
    try:
        metadata = os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return False
    return stat.S_ISDIR(metadata.st_mode)


def _directory_open_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _file_create_flags() -> int:
    return os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _file_read_flags() -> int:
    return os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _set_private_directory_mode(descriptor: int) -> None:
    if hasattr(os, "fchmod"):
        os.fchmod(descriptor, _DIRECTORY_MODE)


def _require_workspace_identity(
    descriptor: int,
    expected: WorkspaceIdentity,
) -> None:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_dev != expected.device
        or metadata.st_ino != expected.inode
    ):
        raise RuntimeError("Task workspace changed identity during admission")


def _require_safe_workspace_primitives() -> None:
    required = (
        hasattr(os, "O_DIRECTORY"),
        hasattr(os, "O_NOFOLLOW"),
        os.open in os.supports_dir_fd,
        os.mkdir in os.supports_dir_fd,
        os.stat in os.supports_dir_fd,
        os.stat in os.supports_follow_symlinks,
        os.unlink in os.supports_dir_fd,
        shutil.rmtree.avoids_symlink_attacks,
    )
    if not all(required):
        raise RuntimeError("safe Banksia workspace primitives are unavailable")


__all__ = [
    "WorkspaceIdentity",
    "capture_workspace_identity",
    "ensure_directory",
    "is_real_directory",
    "open_banksia_root",
    "open_child_directory",
    "open_task_root",
    "read_small_text",
    "remove_task_tree",
    "replace_task_text",
    "replace_text",
    "reserve_task_root",
    "task_root_names",
    "unlink_entry",
    "write_new_text",
]
