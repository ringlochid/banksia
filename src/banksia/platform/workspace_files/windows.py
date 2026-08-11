from __future__ import annotations

import errno
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from banksia.platform.workspace_files.contracts import (
    DirectoryLease,
    PrivateMutationTimeoutError,
    PrivatePathError,
)
from banksia.platform.workspace_files.windows_native import (
    close_handle,
    open_relative_entry,
    read_handle_range,
)
from banksia.platform.workspace_files.windows_security import protect_private_handle
from banksia.platform.workspace_files.workspace_windows import (
    WindowsWorkspaceFileOperations,
    require_windows_directory_lease,
)


class WindowsPrivateFileOperations:
    """Current-user private text operations for local Windows NTFS paths."""

    def ensure_directory(self, path: Path) -> None:
        _open_or_create_directory(path).close()

    def protect_path(self, path: Path, *, is_directory: bool) -> None:
        _operations, parent = _open_parent(path)
        try:
            handle = open_relative_entry(
                require_windows_directory_lease(parent).native_handle,
                path.name,
                should_be_directory=is_directory,
                should_allow_security_update=True,
            )
            try:
                protect_private_handle(handle)
            finally:
                close_handle(handle)
        finally:
            parent.close()

    def read_text(self, path: Path) -> str | None:
        try:
            operations, parent = _open_parent(path)
        except FileNotFoundError:
            return None
        del operations
        try:
            try:
                handle = open_relative_entry(
                    require_windows_directory_lease(parent).native_handle,
                    path.name,
                    should_be_directory=False,
                )
            except FileNotFoundError:
                return None
            try:
                payload, file_size = read_handle_range(
                    handle,
                    offset=0,
                    byte_limit=16 * 1024 * 1024,
                )
                if len(payload) != file_size:
                    raise PrivatePathError(errno.EFBIG, "private text file exceeds 16 MiB", path)
                return payload.decode("utf-8", errors="strict")
            finally:
                close_handle(handle)
        finally:
            parent.close()

    def replace_text(self, path: Path, text: str) -> None:
        self.ensure_directory(path.parent)
        operations = WindowsWorkspaceFileOperations()
        parent = operations.open_workspace(path.parent)
        try:
            operations.replace_text(parent, path.name, text)
        finally:
            parent.close()

    @contextmanager
    def acquire_mutation_lock(
        self,
        path: Path,
        *,
        timeout_seconds: float,
    ) -> Iterator[None]:
        if os.name != "nt":
            raise PrivatePathError(errno.ENOTSUP, "Windows mutation locks are unavailable")
        import msvcrt

        msvcrt_module: Any = msvcrt

        self.ensure_directory(path.parent)
        operations = WindowsWorkspaceFileOperations()
        parent = operations.open_workspace(path.parent)
        handle = open_relative_entry(
            require_windows_directory_lease(parent).native_handle,
            path.name,
            should_be_directory=False,
            should_open_if=True,
            should_allow_mutation=True,
            should_allow_security_update=True,
        )
        protect_private_handle(handle)
        descriptor = int(
            msvcrt_module.open_osfhandle(
                handle,
                os.O_RDWR | getattr(os, "O_BINARY", 0),
            )
        )
        is_locked = False
        deadline = time.monotonic() + timeout_seconds
        try:
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            while True:
                try:
                    msvcrt_module.locking(descriptor, msvcrt_module.LK_NBLCK, 1)
                    is_locked = True
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise PrivateMutationTimeoutError(
                            f"timed out waiting for private mutation lock: {path}"
                        ) from exc
                    time.sleep(0.05)
            yield
        finally:
            if is_locked:
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt_module.locking(descriptor, msvcrt_module.LK_UNLCK, 1)
            os.close(descriptor)
            parent.close()


def _open_parent(path: Path) -> tuple[WindowsWorkspaceFileOperations, DirectoryLease]:
    if not path.is_absolute() or path == Path(path.anchor):
        raise PrivatePathError(errno.EINVAL, "private file must be an absolute non-root path", path)
    operations = WindowsWorkspaceFileOperations()
    return operations, operations.open_workspace(path.parent)


def _open_or_create_directory(path: Path) -> DirectoryLease:
    if not path.is_absolute() or path == Path(path.anchor):
        raise PrivatePathError(
            errno.EINVAL,
            "private directory must be an absolute non-root path",
            path,
        )
    operations = WindowsWorkspaceFileOperations()
    current = operations.open_workspace(Path(path.anchor))
    try:
        for index, component in enumerate(path.parts[1:]):
            try:
                following = operations.open_child_directory(
                    current,
                    component,
                    should_require_private=index == len(path.parts[1:]) - 1,
                )
            except FileNotFoundError:
                following = operations.create_child_directory(current, component)
            current.close()
            current = following
        return current
    except BaseException:
        current.close()
        raise


__all__ = ["WindowsPrivateFileOperations"]
