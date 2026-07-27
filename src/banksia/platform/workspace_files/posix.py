from __future__ import annotations

import errno
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from banksia.platform.private_paths import (
    protect_private_directory_descriptor,
    protect_private_file_descriptor,
)
from banksia.platform.workspace_files.contracts import (
    DirectoryLease,
    PrivateMutationTimeoutError,
    PrivatePathError,
)
from banksia.platform.workspace_files.workspace_posix import PosixWorkspaceFileOperations


class PosixPrivateFileOperations:
    """Owner-only private text operations for Linux and macOS."""

    def ensure_directory(self, path: Path) -> None:
        _open_or_create_directory(path).close()

    def protect_path(self, path: Path, *, is_directory: bool) -> None:
        operations, parent = _open_parent(path)
        try:
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | _no_follow_flag()
            if is_directory:
                flags |= getattr(os, "O_DIRECTORY", 0)
            descriptor = os.open(
                path.name,
                flags,
                dir_fd=operations.directory_descriptor(parent),
            )
            try:
                if is_directory:
                    protect_private_directory_descriptor(descriptor)
                else:
                    protect_private_file_descriptor(descriptor)
            finally:
                os.close(descriptor)
        finally:
            parent.close()

    def read_text(self, path: Path) -> str | None:
        try:
            operations, parent = _open_parent(path)
        except FileNotFoundError:
            return None
        try:
            descriptor = self._open_private_file_for_read(
                operations.directory_descriptor(parent),
                path.name,
            )
            if descriptor is None:
                return None
            try:
                with os.fdopen(
                    descriptor,
                    "r",
                    encoding="utf-8",
                    newline="",
                    closefd=False,
                ) as stream:
                    return stream.read()
            finally:
                os.close(descriptor)
        finally:
            parent.close()

    def replace_text(self, path: Path, text: str) -> None:
        self.ensure_directory(path.parent)
        operations = PosixWorkspaceFileOperations()
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
        self.ensure_directory(path.parent)
        operations = PosixWorkspaceFileOperations()
        parent = operations.open_workspace(path.parent)
        descriptor = self._open_private_lock(
            operations.directory_descriptor(parent),
            path.name,
        )
        is_locked = False
        deadline = time.monotonic() + timeout_seconds
        try:
            import fcntl

            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    is_locked = True
                    break
                except BlockingIOError as exc:
                    if time.monotonic() >= deadline:
                        raise PrivateMutationTimeoutError(
                            f"timed out waiting for private mutation lock: {path}"
                        ) from exc
                    time.sleep(0.05)
            yield
        finally:
            if is_locked:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
            parent.close()

    @staticmethod
    def _open_private_file_for_read(parent_descriptor: int, name: str) -> int | None:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | _no_follow_flag()
        try:
            descriptor = os.open(name, flags, dir_fd=parent_descriptor)
        except FileNotFoundError:
            return None
        try:
            protect_private_file_descriptor(descriptor)
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    @staticmethod
    def _open_private_lock(parent_descriptor: int, name: str) -> int:
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | _no_follow_flag()
        descriptor = os.open(name, flags, 0o600, dir_fd=parent_descriptor)
        try:
            protect_private_file_descriptor(descriptor)
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor


def _no_follow_flag() -> int:
    flag = getattr(os, "O_NOFOLLOW", None)
    if flag is None:
        raise PrivatePathError(
            errno.ENOTSUP,
            "this POSIX host cannot reject a final symlink for private files",
        )
    return int(flag)


def _open_parent(path: Path) -> tuple[PosixWorkspaceFileOperations, DirectoryLease]:
    if not path.is_absolute() or path == Path(path.anchor):
        raise PrivatePathError(
            errno.EINVAL,
            "private file must be an absolute non-root path",
            path,
        )
    operations = PosixWorkspaceFileOperations()
    return operations, operations.open_workspace(path.parent)


def _open_or_create_directory(
    path: Path,
) -> DirectoryLease:
    if not path.is_absolute() or path == Path(path.anchor):
        raise PrivatePathError(
            errno.EINVAL,
            "private directory must be an absolute non-root path",
            path,
        )
    operations = PosixWorkspaceFileOperations()
    current = operations.open_workspace(Path(path.anchor))
    try:
        components = path.parts[1:]
        for index, component in enumerate(components):
            try:
                following = operations.open_child_directory(
                    current,
                    component,
                    should_require_private=index == len(components) - 1,
                )
            except FileNotFoundError:
                following = operations.create_child_directory(current, component)
            current.close()
            current = following
        return current
    except BaseException:
        current.close()
        raise


__all__ = ["PosixPrivateFileOperations"]
